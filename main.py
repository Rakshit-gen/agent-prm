from fastapi import FastAPI, HTTPException, BackgroundTasks, Request
from pydantic import BaseModel, Field, HttpUrl, field_validator, model_validator
from typing import Dict, Any, List, Optional
from datetime import datetime
from enum import Enum
import uuid
import os
import requests
from groq import Groq
import logging
import json
import redis
from rate_limiter import RateLimiter, rate_limit
from fastapi.middleware.cors import CORSMiddleware

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("ai-pr-review")

class IssueType(str, Enum):
    BUG = "bug"
    STYLE = "style"
    PERFORMANCE = "performance"
    SECURITY = "security"
    MAINTAINABILITY = "maintainability"
    READABILITY = "readability"

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
    line: Optional[int] = Field(None, ge=1, description="Line number in file")
    type: IssueType = Field(..., description="Type of issue")
    description: str = Field(..., min_length=1, description="Issue description")
    suggestion: str = Field(..., min_length=1, description="Suggested fix")
    
    class Config:
        use_enum_values = True

class FileAnalysis(BaseModel):
    name: str = Field(..., description="File name")
    issues: List[Issue] = Field(default_factory=list, description="List of issues found")
    error: Optional[str] = Field(None, description="Error message if analysis failed")
    
    @property
    def issue_count(self) -> int:
        return len(self.issues)
    
    @property
    def critical_issue_count(self) -> int:
        return sum(1 for issue in self.issues if issue.type in [IssueType.BUG, IssueType.SECURITY])

class AnalysisSummary(BaseModel):
    total_files: int = Field(..., ge=0, description="Total number of files analyzed")
    total_issues: int = Field(..., ge=0, description="Total number of issues found")
    critical_issues: int = Field(..., ge=0, description="Number of critical issues")
    
    @model_validator(mode='after')
    def validate_issue_counts(self):
        if self.critical_issues > self.total_issues:
            raise ValueError("Critical issues cannot exceed total issues")
        return self

class PRAnalysisResult(BaseModel):
    pr_title: str = Field(..., description="Pull request title")
    pr_url: str = Field(..., description="Pull request URL")
    analyzed_at: datetime = Field(..., description="Analysis timestamp")
    files: List[FileAnalysis] = Field(default_factory=list, description="File analysis results")
    summary: AnalysisSummary = Field(..., description="Analysis summary")
    
    class Config:
        json_encoders = {datetime: lambda v: v.isoformat()}

class TaskResponse(BaseModel):
    task_id: str = Field(..., description="Unique task identifier")
    status: TaskStatus = Field(..., description="Current task status")
    message: str = Field(..., description="Response message")

class TaskStatusResponse(BaseModel):
    task_id: str
    status: TaskStatus
    created_at: Optional[str] = None
    error: Optional[str] = None

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

class GitHubPRData(BaseModel):
    title: str
    html_url: str

class GitHubFileData(BaseModel):
    filename: str
    patch: Optional[str] = None

app = FastAPI(title="AI Code Review Agent (Ruthless Mode)")

origins = ["http://localhost:3000", "https://code-bot-rho.vercel.app"]
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
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

class CodeReviewAgent:
    def __init__(self, github_token: str = None):
        self.github_token = github_token or os.getenv("GITHUB_TOKEN")
        groq_api_key = os.getenv("GROQ_API_KEY")
        if not groq_api_key:
            raise ValueError("GROQ_API_KEY not found in environment variables")
        self.groq_client = Groq(api_key=groq_api_key)
        self.headers = {}
        if self.github_token:
            self.headers["Authorization"] = f"token {self.github_token}"

    def fetch_pr_data(self, repo_url: str, pr_number: int) -> Dict[str, Any]:
        parts = repo_url.rstrip("/").split("github.com/")[-1].split("/")
        owner, repo = parts[0], parts[1]
        logger.info(f"Fetching PR data for {owner}/{repo} #{pr_number}")
        pr_url = f"https://api.github.com/repos/{owner}/{repo}/pulls/{pr_number}"
        response = requests.get(pr_url, headers=self.headers)
        response.raise_for_status()
        pr_data = response.json()
        files_url = f"https://api.github.com/repos/{owner}/{repo}/pulls/{pr_number}/files"
        response = requests.get(files_url, headers=self.headers)
        response.raise_for_status()
        files_data = response.json()
        return {"pr": pr_data, "files": files_data}

    def analyze_file_diff(self, file_data: Dict[str, Any]) -> FileAnalysis:
        filename = file_data.get("filename", "")
        patch = file_data.get("patch", "")
        if not patch:
            return FileAnalysis(name=filename, issues=[])
        logger.info(f"Analyzing file: {filename} (STRICT MODE)")
        prompt = f"""You are a ruthless, detail-obsessed senior code reviewer. Find every possible issue.

Analyze this GitHub diff:
File: {filename}
Diff:
{patch}

Return ONLY a valid JSON array of issues. Each issue must have:
- "file": file name
- "line": approximate line number (integer or null)
- "type": one of ["bug", "style", "performance", "security", "maintainability", "readability"]
- "description": concise but specific explanation
- "suggestion": clear recommendation for fixing

Example:
[{{"file": "{filename}", "line": 12, "type": "style", "description": "Missing space after comma", "suggestion": "Use proper spacing"}}]

If code looks fine, still return style feedback. Never return an empty list."""

        try:
            response = self.groq_client.chat.completions.create(
                model="llama-3.3-70b-versatile",
                messages=[
                    {"role": "system", "content": "You are an unforgiving code reviewer. Output only valid JSON."},
                    {"role": "user", "content": prompt}
                ],
                temperature=0.1,
                max_tokens=2048,
            )
            response_text = response.choices[0].message.content.strip()
            if response_text.startswith("```json"):
                response_text = response_text[7:]
            if response_text.endswith("```"):
                response_text = response_text[:-3]
            response_text = response_text.strip()
            issues_data = json.loads(response_text)
            issues = [Issue(**issue) for issue in issues_data] if isinstance(issues_data, list) else []
            if not issues:
                issues = [Issue(
                    file=filename,
                    line=None,
                    type=IssueType.READABILITY,
                    description="Model returned no issues — likely false negative.",
                    suggestion="Review file structure and naming manually."
                )]
            return FileAnalysis(name=filename, issues=issues)
        except Exception as e:
            logger.error(f"Error analyzing file {filename}: {str(e)}")
            return FileAnalysis(name=filename, issues=[], error=str(e))

    def analyze_pr(self, repo_url: str, pr_number: int) -> PRAnalysisResult:
        try:
            pr_data = self.fetch_pr_data(repo_url, pr_number)
            analyzed_files = []
            total_issues = 0
            critical_issues = 0
            for file_data in pr_data["files"]:
                file_analysis = self.analyze_file_diff(file_data)
                analyzed_files.append(file_analysis)
                for issue in file_analysis.issues:
                    total_issues += 1
                    if issue.type in [IssueType.BUG, IssueType.SECURITY]:
                        critical_issues += 1
            summary = AnalysisSummary(
                total_files=len(analyzed_files),
                total_issues=total_issues,
                critical_issues=critical_issues
            )
            return PRAnalysisResult(
                pr_title=pr_data["pr"].get("title", ""),
                pr_url=pr_data["pr"].get("html_url", ""),
                analyzed_at=datetime.utcnow(),
                files=analyzed_files,
                summary=summary
            )
        except requests.exceptions.HTTPError as e:
            logger.error(f"HTTP error fetching PR data: {str(e)}")
            raise Exception(f"Failed to fetch PR data: {str(e)}")
        except Exception as e:
            logger.error(f"Error in analyze_pr: {str(e)}")
            raise

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

def process_pr_analysis(task_id: str, repo_url: str, pr_number: int, github_token: str = None):
    try:
        task_data = get_task(task_id)
        if task_data:
            task_data.status = TaskStatus.PROCESSING
            save_task(task_id, task_data)
        logger.info(f"Starting PR analysis for task {task_id}")
        agent = CodeReviewAgent(github_token)
        results = agent.analyze_pr(repo_url, pr_number)
        task_data = get_task(task_id)
        if task_data:
            task_data.status = TaskStatus.COMPLETED
            task_data.results = results
            save_task(task_id, task_data)
        logger.info(f"Completed PR analysis for task {task_id}")
    except Exception as e:
        logger.error(f"Failed PR analysis for task {task_id}: {str(e)}")
        task_data = get_task(task_id)
        if task_data:
            task_data.status = TaskStatus.FAILED
            task_data.error = str(e)
            save_task(task_id, task_data)

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
        logger.info(f"Created task {task_id}")
        return TaskResponse(
            task_id=task_id,
            status=TaskStatus.PENDING,
            message="PR analysis task created successfully"
        )
    except Exception as e:
        logger.error(f"Error creating task: {str(e)}")
        raise HTTPException(status_code=500, detail=str(e))

@app.get("/status/{task_id}", response_model=TaskStatusResponse)
async def get_status(task_id: str):
    task_data = get_task(task_id)
    if not task_data:
        raise HTTPException(status_code=404, detail="Task not found")
    return TaskStatusResponse(
        task_id=task_id,
        status=task_data.status,
        created_at=task_data.created_at,
        error=task_data.error
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

@app.get("/")
async def root():
    return {
        "message": "AI Code Review Agent (Ruthless Mode, Powered by Groq)",
        "version": "2.1.0",
        "storage": "Redis" if redis_client else "In-Memory",
        "endpoints": {
            "POST /analyze-pr": "Submit a PR for strict AI review",
            "GET /status/{task_id}": "Check task status",
            "GET /results/{task_id}": "Get strict analysis results"
        }
    }

if __name__ == "__main__":
    import uvicorn
    uvicorn.run("main:app", host="0.0.0.0", port=int(os.getenv("PORT", 8000)), reload=True)