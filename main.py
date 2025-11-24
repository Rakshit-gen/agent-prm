from fastapi import FastAPI, HTTPException, BackgroundTasks, Request, WebSocket, WebSocketDisconnect
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, Field, field_validator, model_validator
from typing import Dict, Any, List, Optional
from datetime import datetime
from enum import Enum
import uuid
import os
import requests
import logging
import json
import redis
from rate_limiter import RateLimiter, rate_limit
from agents.orchestrator import AgentOrchestrator

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("multiagent-pr-review")

class IssueType(str, Enum):
    BUG = "bug"
    STYLE = "style"
    PERFORMANCE = "performance"
    SECURITY = "security"
    MAINTAINABILITY = "maintainability"
    READABILITY = "readability"
    ARCHITECTURE = "architecture"
    QUALITY = "quality"

class TaskStatus(str, Enum):
    PENDING = "pending"
    PROCESSING = "processing"
    COMPLETED = "completed"
    FAILED = "failed"

class PRRequest(BaseModel):
    repo_url: str = Field(..., description="GitHub repository URL", examples=["https://github.com/owner/repo"])
    pr_number: int = Field(..., gt=0, description="Pull request number", examples=[123])
    github_token: Optional[str] = Field(None, description="GitHub personal access token")

    @field_validator('repo_url')
    @classmethod
    def validate_github_url(cls, v):
        if "github.com" not in v:
            raise ValueError("Must be a valid GitHub repository URL")
        return v

class Issue(BaseModel):
    file: str = Field(..., description="File name where issue was found")
    line: Optional[int] = Field(None, description="Line number in file")
    type: str = Field(..., description="Type of issue")
    description: str = Field(..., min_length=1, description="Issue description")
    suggestion: str = Field(..., min_length=1, description="Suggested fix")
    detected_by: Optional[str] = Field(None, description="Agent that detected the issue")
    severity: Optional[str] = Field(None, description="Severity level")
    impact: Optional[str] = Field(None, description="Impact level")
    
    @field_validator('line')
    @classmethod
    def validate_line(cls, v):
        """Convert invalid line numbers (0 or negative) to None"""
        if v is not None and (v < 1 or v == 0):
            return None
        return v

class FileAnalysis(BaseModel):
    name: str = Field(..., description="File name")
    issues: List[Issue] = Field(default_factory=list, description="List of issues found")
    error: Optional[str] = Field(None, description="Error message if analysis failed")
    agent_breakdown: Optional[Dict[str, int]] = Field(default_factory=dict, description="Issues by agent")
    code_content: Optional[str] = Field(None, description="File code content or patch")

class AgentProgress(BaseModel):
    agent: str
    status: str
    progress: float
    message: str
    timestamp: str

class AnalysisSummary(BaseModel):
    total_files: int = Field(..., ge=0, description="Total number of files analyzed")
    total_issues: int = Field(..., ge=0, description="Total number of issues found")
    critical_issues: int = Field(..., ge=0, description="Number of critical issues")
    high_priority_issues: int = Field(..., ge=0, description="Number of high priority issues")
    total_agents: int = Field(..., ge=0, description="Total number of agents")
    agents_completed: int = Field(..., ge=0, description="Number of agents completed")

class PRAnalysisResult(BaseModel):
    pr_title: str = Field(..., description="Pull request title")
    pr_url: str = Field(..., description="Pull request URL")
    analyzed_at: str = Field(..., description="Analysis timestamp")
    files: List[FileAnalysis] = Field(default_factory=list, description="File analysis results")
    summary: AnalysisSummary = Field(..., description="Analysis summary")
    agents: Optional[Dict[str, Any]] = Field(default_factory=dict, description="Agent-specific results")

class TaskResponse(BaseModel):
    task_id: str = Field(..., description="Unique task identifier")
    status: TaskStatus = Field(..., description="Current task status")
    message: str = Field(..., description="Response message")

class TaskStatusResponse(BaseModel):
    task_id: str
    status: TaskStatus
    created_at: Optional[str] = None
    error: Optional[str] = None
    progress: Optional[List[AgentProgress]] = None

class TaskResultResponse(BaseModel):
    task_id: str
    status: TaskStatus
    results: Optional[PRAnalysisResult] = None

class TaskData(BaseModel):
    status: TaskStatus
    created_at: str
    repo_url: str
    pr_number: int
    results: Optional[PRAnalysisResult] = None
    error: Optional[str] = None
    progress: List[AgentProgress] = Field(default_factory=list)

app = FastAPI(title="Multiagentic AI Code Review System", version="4.0.0")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
    expose_headers=["*"],
)

REDIS_URL = os.getenv("REDIS_URL")
if REDIS_URL:
    try:
        redis_client = redis.from_url(REDIS_URL, decode_responses=True)
        redis_client.ping()
        logger.info("Redis connected successfully")
    except Exception as e:
        logger.error(f"Redis connection failed: {e}")
        redis_client = None
else:
    logger.warning("REDIS_URL not set, using in-memory storage")
    redis_client = None

app.state.rate_limiter = RateLimiter(redis_client)
tasks_store: Dict[str, Dict[str, Any]] = {}
task_progress: Dict[str, List[Dict[str, Any]]] = {}

def fetch_pr_data(repo_url: str, pr_number: int, github_token: str = None) -> Dict[str, Any]:
    """Fetch PR data from GitHub"""
    headers = {}
    if github_token:
        headers["Authorization"] = f"token {github_token}"
    elif os.getenv("GITHUB_TOKEN"):
        headers["Authorization"] = f"token {os.getenv('GITHUB_TOKEN')}"
    
    parts = repo_url.rstrip("/").split("github.com/")[-1].split("/")
    owner, repo = parts[0], parts[1]
    
    logger.info(f"Fetching PR data for {owner}/{repo} #{pr_number}")
    
    pr_url = f"https://api.github.com/repos/{owner}/{repo}/pulls/{pr_number}"
    response = requests.get(pr_url, headers=headers)
    response.raise_for_status()
    pr_data = response.json()
    
    files_url = f"https://api.github.com/repos/{owner}/{repo}/pulls/{pr_number}/files"
    response = requests.get(files_url, headers=headers)
    response.raise_for_status()
    files_data = response.json()
    
    return {
        "pr_title": pr_data.get("title", ""),
        "pr_url": pr_data.get("html_url", ""),
        "files": [{"filename": f.get("filename"), "patch": f.get("patch", "")} for f in files_data]
    }

def save_task(task_id: str, data: TaskData):
    data_dict = data.model_dump(mode='json')
    if redis_client:
        try:
            redis_client.set(f"task:{task_id}", json.dumps(data_dict), ex=86400)
        except Exception as e:
            logger.error(f"Redis save error: {e}")
            tasks_store[task_id] = data_dict
    else:
        tasks_store[task_id] = data_dict

def get_task(task_id: str) -> Optional[TaskData]:
    if redis_client:
        try:
            data = redis_client.get(f"task:{task_id}")
            return TaskData(**json.loads(data)) if data else None
        except Exception as e:
            logger.error(f"Redis get error: {e}")
            data_dict = tasks_store.get(task_id)
            return TaskData(**data_dict) if data_dict else None
    else:
        data_dict = tasks_store.get(task_id)
        return TaskData(**data_dict) if data_dict else None

def update_progress(task_id: str, progress_data: Dict[str, Any]):
    """Update progress for a task"""
    if task_id not in task_progress:
        task_progress[task_id] = []
    task_progress[task_id].append(progress_data)
    
    # Also update in task data
    task_data = get_task(task_id)
    if task_data:
        task_data.progress.append(AgentProgress(**progress_data))
        save_task(task_id, task_data)

def process_pr_analysis(task_id: str, repo_url: str, pr_number: int, github_token: str = None):
    """Process PR analysis using multiagentic system"""
    try:
        task_data = get_task(task_id)
        if task_data:
            task_data.status = TaskStatus.PROCESSING
            save_task(task_id, task_data)
        
        logger.info(f"Starting multiagentic PR analysis for task {task_id}")
        
        # Fetch PR data
        update_progress(task_id, {
            "agent": "System",
            "status": "fetching",
            "progress": 0.1,
            "message": "Fetching PR data from GitHub",
            "timestamp": datetime.utcnow().isoformat()
        })
        
        pr_data = fetch_pr_data(repo_url, pr_number, github_token)
        
        # Create orchestrator with progress callback
        def progress_callback(progress: Dict[str, Any]):
            update_progress(task_id, progress)
        
        orchestrator = AgentOrchestrator(github_token, progress_callback)
        
        # Run multiagentic analysis
        update_progress(task_id, {
            "agent": "System",
            "status": "analyzing",
            "progress": 0.2,
            "message": "Initializing multiagentic analysis system",
            "timestamp": datetime.utcnow().isoformat()
        })
        
        analysis_results = orchestrator.analyze_pr(pr_data)
        
        # Store original PR data for code content
        pr_files_map = {f.get("filename"): f.get("patch", "") for f in pr_data.get("files", [])}
        
        # Convert to PRAnalysisResult format
        files_analysis = []
        for file_data in analysis_results.get("files", []):
            filename = file_data.get("name", "unknown")
            code_content = pr_files_map.get(filename, "")
            
            issues = []
            for issue_data in file_data.get("issues", []):
                # Map issue types
                issue_type = issue_data.get("type", "readability")
                if "security" in issue_type.lower():
                    issue_type = "security"
                elif "performance" in issue_type.lower():
                    issue_type = "performance"
                elif "architecture" in issue_type.lower() or "design" in issue_type.lower():
                    issue_type = "architecture"
                elif "quality" in issue_type.lower() or "smell" in issue_type.lower():
                    issue_type = "quality"
                
                # Sanitize line number - convert 0 or negative to None
                line_num = issue_data.get("line")
                if line_num is not None:
                    try:
                        line_num = int(line_num)
                        if line_num < 1 or line_num == 0:
                            line_num = None
                    except (ValueError, TypeError):
                        line_num = None
                
                # Sanitize description and suggestion - ensure they're not empty
                description = str(issue_data.get("description", "")).strip()
                if not description:
                    description = "Issue detected"
                
                suggestion = str(issue_data.get("suggestion", "")).strip()
                if not suggestion:
                    suggestion = "Review and fix the issue"
                
                # Ensure file name is valid
                file_name = str(issue_data.get("file", file_data.get("name", "unknown"))).strip()
                if not file_name:
                    file_name = "unknown"
                
                issue = Issue(
                    file=file_name,
                    line=line_num,
                    type=str(issue_type).strip() or "readability",
                    description=description,
                    suggestion=suggestion,
                    detected_by=issue_data.get("detected_by"),
                    severity=issue_data.get("severity") or issue_data.get("impact"),
                    impact=issue_data.get("impact") or issue_data.get("severity")
                )
                issues.append(issue)
            
            file_analysis = FileAnalysis(
                name=file_data.get("name", "unknown"),
                issues=issues,
                agent_breakdown=file_data.get("agent_breakdown", {}),
                code_content=code_content
            )
            files_analysis.append(file_analysis)
        
        summary = AnalysisSummary(
            total_files=analysis_results.get("summary", {}).get("total_files", 0),
            total_issues=analysis_results.get("summary", {}).get("total_issues", 0),
            critical_issues=analysis_results.get("summary", {}).get("critical_issues", 0),
            high_priority_issues=analysis_results.get("summary", {}).get("high_priority_issues", 0),
            total_agents=analysis_results.get("summary", {}).get("total_agents", 0),
            agents_completed=analysis_results.get("summary", {}).get("agents_completed", 0)
        )
        
        result = PRAnalysisResult(
            pr_title=analysis_results.get("pr_title", ""),
            pr_url=analysis_results.get("pr_url", ""),
            analyzed_at=analysis_results.get("analyzed_at", datetime.utcnow().isoformat()),
            files=files_analysis,
            summary=summary,
            agents=analysis_results.get("agents", {})
        )
        
        task_data = get_task(task_id)
        if task_data:
            task_data.status = TaskStatus.COMPLETED
            task_data.results = result
            save_task(task_id, task_data)
        
        update_progress(task_id, {
            "agent": "System",
            "status": "completed",
            "progress": 1.0,
            "message": "Multiagentic analysis completed",
            "timestamp": datetime.utcnow().isoformat()
        })
        
        logger.info(f"Completed multiagentic PR analysis for task {task_id}")
    
    except Exception as e:
        logger.error(f"Failed PR analysis for task {task_id}: {str(e)}")
        task_data = get_task(task_id)
        if task_data:
            task_data.status = TaskStatus.FAILED
            task_data.error = str(e)
            save_task(task_id, task_data)
        
        update_progress(task_id, {
            "agent": "System",
            "status": "error",
            "progress": 0.0,
            "message": f"Analysis failed: {str(e)}",
            "timestamp": datetime.utcnow().isoformat()
        })

@app.post("/analyze-pr", response_model=TaskResponse)
@rate_limit(max_requests=10, window_seconds=60)
async def analyze_pr(request: Request, pr_request: PRRequest, background_tasks: BackgroundTasks):
    try:
        task_id = str(uuid.uuid4())
        
        task_data = TaskData(
            status=TaskStatus.PENDING,
            created_at=datetime.utcnow().isoformat(),
            repo_url=pr_request.repo_url,
            pr_number=pr_request.pr_number
        )
        save_task(task_id, task_data)
        
        background_tasks.add_task(
            process_pr_analysis,
            task_id,
            pr_request.repo_url,
            pr_request.pr_number,
            pr_request.github_token
        )
        
        logger.info(f"Created multiagentic task {task_id}")
        
        return TaskResponse(
            task_id=task_id,
            status=TaskStatus.PENDING,
            message="Multiagentic PR analysis task created successfully"
        )
    
    except Exception as e:
        logger.error(f"Error creating task: {str(e)}")
        raise HTTPException(status_code=500, detail=str(e))

@app.get("/status/{task_id}", response_model=TaskStatusResponse)
async def get_status(task_id: str):
    task_data = get_task(task_id)
    if not task_data:
        raise HTTPException(status_code=404, detail="Task not found")
    
    progress_list = task_progress.get(task_id, [])
    if not progress_list and task_data.progress:
        progress_list = [p.model_dump() for p in task_data.progress]
    
    return TaskStatusResponse(
        task_id=task_id,
        status=task_data.status,
        created_at=task_data.created_at,
        error=task_data.error,
        progress=[AgentProgress(**p) for p in progress_list] if progress_list else None
    )

@app.get("/results/{task_id}", response_model=TaskResultResponse)
async def get_results(task_id: str):
    task_data = get_task(task_id)
    if not task_data:
        raise HTTPException(status_code=404, detail="Task not found")
    
    if task_data.status in [TaskStatus.PENDING, TaskStatus.PROCESSING]:
        raise HTTPException(status_code=202, detail=f"Task {task_data.status.value}")
    elif task_data.status == TaskStatus.FAILED:
        raise HTTPException(status_code=500, detail=f"Task failed: {task_data.error}")
    elif task_data.status == TaskStatus.COMPLETED:
        return TaskResultResponse(
            task_id=task_id,
            status=TaskStatus.COMPLETED,
            results=task_data.results
        )
    else:
        raise HTTPException(status_code=500, detail=f"Unknown task state: {task_data.status}")

@app.websocket("/ws/{task_id}")
async def websocket_endpoint(websocket: WebSocket, task_id: str):
    """WebSocket endpoint for real-time progress updates"""
    await websocket.accept()
    try:
        while True:
            task_data = get_task(task_id)
            if not task_data:
                await websocket.send_json({"error": "Task not found"})
                break
            
            progress_list = task_progress.get(task_id, [])
            if not progress_list and task_data.progress:
                progress_list = [p.model_dump() for p in task_data.progress]
            
            await websocket.send_json({
                "status": task_data.status.value,
                "progress": progress_list,
                "error": task_data.error
            })
            
            if task_data.status in [TaskStatus.COMPLETED, TaskStatus.FAILED]:
                break
            
            import asyncio
            await asyncio.sleep(2)  # Update every 2 seconds
    
    except WebSocketDisconnect:
        logger.info(f"WebSocket disconnected for task {task_id}")

@app.get("/")
async def root():
    return {
        "message": "Multiagentic AI Code Review System",
        "version": "4.0.0",
        "architecture": "Multiagentic with Agent Orchestration",
        "storage": "Redis" if redis_client else "In-Memory",
        "agents": [
            "SecurityAgent - Vulnerability detection and security analysis",
            "PerformanceAgent - Performance optimization and analysis",
            "ArchitectureAgent - Design patterns and architecture review",
            "QualityAgent - Code quality and maintainability"
        ],
        "features": [
            "Real-time progress tracking",
            "WebSocket support for live updates",
            "Parallel agent execution",
            "Deep analysis with multiple specialized agents",
            "Comprehensive issue detection"
        ],
        "endpoints": {
            "POST /analyze-pr": "Submit a PR for multiagentic AI review",
            "GET /status/{task_id}": "Check task status and progress",
            "GET /results/{task_id}": "Get comprehensive analysis results",
            "WS /ws/{task_id}": "WebSocket for real-time progress updates"
        }
    }

if __name__ == "__main__":
    import uvicorn
    uvicorn.run("main:app", host="0.0.0.0", port=int(os.getenv("PORT", 8000)), reload=True)
