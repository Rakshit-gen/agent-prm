from fastapi import FastAPI, HTTPException, BackgroundTasks, Request
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
from fastapi.middleware.cors import CORSMiddleware
from langchain.agents import AgentExecutor, create_structured_chat_agent
from langchain.tools import StructuredTool
from langchain.memory import ConversationBufferMemory
from langchain_groq import ChatGroq
from langchain.prompts import ChatPromptTemplate, MessagesPlaceholder
from langchain.schema import SystemMessage, HumanMessage
from pydantic import BaseModel as PydanticBaseModel

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

app = FastAPI(title="AI Code Review Agent (Agentic Architecture)")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=False,
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

class FetchPRToolInput(PydanticBaseModel):
    repo_url: str = Field(description="GitHub repository URL")
    pr_number: int = Field(description="Pull request number")

class AnalyzeCodeToolInput(PydanticBaseModel):
    filename: str = Field(description="Name of the file being analyzed")
    patch: str = Field(description="Git diff patch content")

class SecurityScanToolInput(PydanticBaseModel):
    code: str = Field(description="Code content to scan for security vulnerabilities")
    filename: str = Field(description="Name of the file being scanned")

class PerformanceAnalysisToolInput(PydanticBaseModel):
    code: str = Field(description="Code content to analyze for performance issues")
    language: str = Field(description="Programming language of the code")

class CodeReviewAgentSystem:
    def __init__(self, github_token: str = None):
        self.github_token = github_token or os.getenv("GITHUB_TOKEN")
        groq_api_key = os.getenv("GROQ_API_KEY")
        if not groq_api_key:
            raise ValueError("GROQ_API_KEY not found in environment variables")
        
        self.llm = ChatGroq(
            model="llama-3.3-70b-versatile",
            temperature=0.1,
            groq_api_key=groq_api_key
        )
        
        self.headers = {}
        if self.github_token:
            self.headers["Authorization"] = f"token {self.github_token}"
        
        self.tools = self._create_tools()
        self.agent_executor = self._create_agent()

    def _fetch_pr_data_tool(self, repo_url: str, pr_number: int) -> str:
        try:
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
            
            result = {
                "pr_title": pr_data.get("title", ""),
                "pr_url": pr_data.get("html_url", ""),
                "files": [{"filename": f.get("filename"), "patch": f.get("patch", "")} for f in files_data]
            }
            
            return json.dumps(result)
        except Exception as e:
            return json.dumps({"error": str(e)})

    def _analyze_code_tool(self, filename: str, patch: str) -> str:
        if not patch:
            return json.dumps({"issues": []})
        
        logger.info(f"Analyzing file: {filename}")
        
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
            response = self.llm.invoke([
                SystemMessage(content="You are an unforgiving code reviewer. Output only valid JSON."),
                HumanMessage(content=prompt)
            ])
            
            response_text = response.content.strip()
            
            if response_text.startswith("```json"):
                response_text = response_text[7:]
            if response_text.endswith("```"):
                response_text = response_text[:-3]
            response_text = response_text.strip()
            
            issues_data = json.loads(response_text)
            
            if not isinstance(issues_data, list) or len(issues_data) == 0:
                issues_data = [{
                    "file": filename,
                    "line": None,
                    "type": "readability",
                    "description": "Model returned no issues — likely false negative.",
                    "suggestion": "Review file structure and naming manually."
                }]
            
            return json.dumps({"issues": issues_data})
        except Exception as e:
            logger.error(f"Error analyzing file {filename}: {str(e)}")
            return json.dumps({"error": str(e), "issues": []})

    def _security_scan_tool(self, code: str, filename: str) -> str:
        logger.info(f"Running security scan on: {filename}")
        
        prompt = f"""You are a security expert. Scan this code for security vulnerabilities.

File: {filename}
Code:
{code}

Focus on:
- SQL injection vulnerabilities
- XSS vulnerabilities
- Authentication/authorization issues
- Sensitive data exposure
- Insecure dependencies
- Hardcoded credentials

Return a JSON array of security issues found:
[{{"type": "security", "severity": "high|medium|low", "description": "...", "suggestion": "..."}}]"""

        try:
            response = self.llm.invoke([
                SystemMessage(content="You are a security auditor. Output only valid JSON."),
                HumanMessage(content=prompt)
            ])
            
            response_text = response.content.strip()
            if response_text.startswith("```json"):
                response_text = response_text[7:]
            if response_text.endswith("```"):
                response_text = response_text[:-3]
            
            return response_text.strip()
        except Exception as e:
            return json.dumps({"error": str(e)})

    def _performance_analysis_tool(self, code: str, language: str) -> str:
        logger.info(f"Running performance analysis on {language} code")
        
        prompt = f"""You are a performance optimization expert. Analyze this {language} code for performance issues.

Code:
{code}

Focus on:
- Time complexity issues
- Memory leaks
- Inefficient algorithms
- Unnecessary computations
- Database query optimization
- Caching opportunities

Return a JSON array of performance issues:
[{{"type": "performance", "impact": "high|medium|low", "description": "...", "suggestion": "..."}}]"""

        try:
            response = self.llm.invoke([
                SystemMessage(content="You are a performance optimization expert. Output only valid JSON."),
                HumanMessage(content=prompt)
            ])
            
            response_text = response.content.strip()
            if response_text.startswith("```json"):
                response_text = response_text[7:]
            if response_text.endswith("```"):
                response_text = response_text[:-3]
            
            return response_text.strip()
        except Exception as e:
            return json.dumps({"error": str(e)})

    def _create_tools(self) -> List[StructuredTool]:
        fetch_pr_tool = StructuredTool.from_function(
            func=self._fetch_pr_data_tool,
            name="fetch_pr_data",
            description="Fetches pull request data from GitHub including title, URL, and file changes",
            args_schema=FetchPRToolInput
        )
        
        analyze_code_tool = StructuredTool.from_function(
            func=self._analyze_code_tool,
            name="analyze_code",
            description="Analyzes code diff and identifies bugs, style issues, performance problems, and security vulnerabilities",
            args_schema=AnalyzeCodeToolInput
        )
        
        security_scan_tool = StructuredTool.from_function(
            func=self._security_scan_tool,
            name="security_scan",
            description="Performs deep security vulnerability scanning on code",
            args_schema=SecurityScanToolInput
        )
        
        performance_tool = StructuredTool.from_function(
            func=self._performance_analysis_tool,
            name="performance_analysis",
            description="Analyzes code for performance bottlenecks and optimization opportunities",
            args_schema=PerformanceAnalysisToolInput
        )
        
        return [fetch_pr_tool, analyze_code_tool, security_scan_tool, performance_tool]

    def _create_agent(self) -> AgentExecutor:
        system_template = """You are an expert code review agent with access to specialized tools.

Your task is to perform comprehensive code reviews on GitHub pull requests.

Available tools:
- fetch_pr_data: Fetch PR information and file changes from GitHub
- analyze_code: Analyze code diffs for issues
- security_scan: Perform security vulnerability scanning
- performance_analysis: Analyze performance bottlenecks

Process:
1. Use fetch_pr_data to get the PR information
2. For each file with changes, use analyze_code to identify issues
3. Use security_scan on critical files
4. Use performance_analysis on code with potential bottlenecks
5. Compile all findings into a comprehensive report

Be thorough and use all available tools to provide the best review possible."""

        prompt = ChatPromptTemplate.from_messages([
            ("system", system_template),
            MessagesPlaceholder(variable_name="chat_history", optional=True),
            ("human", "{input}"),
            MessagesPlaceholder(variable_name="agent_scratchpad"),
        ])
        
        agent = create_structured_chat_agent(
            llm=self.llm,
            tools=self.tools,
            prompt=prompt
        )
        
        memory = ConversationBufferMemory(
            memory_key="chat_history",
            return_messages=True
        )
        
        agent_executor = AgentExecutor(
            agent=agent,
            tools=self.tools,
            memory=memory,
            verbose=True,
            handle_parsing_errors=True,
            max_iterations=15
        )
        
        return agent_executor

    def analyze_pr(self, repo_url: str, pr_number: int) -> PRAnalysisResult:
        try:
            input_text = f"Analyze pull request #{pr_number} from repository {repo_url}. Use all available tools to perform a comprehensive code review."
            
            result = self.agent_executor.invoke({"input": input_text})
            
            pr_data_str = self._fetch_pr_data_tool(repo_url, pr_number)
            pr_data = json.loads(pr_data_str)
            
            if "error" in pr_data:
                raise Exception(pr_data["error"])
            
            analyzed_files = []
            total_issues = 0
            critical_issues = 0
            
            for file_data in pr_data["files"]:
                filename = file_data["filename"]
                patch = file_data["patch"]
                
                analysis_result = self._analyze_code_tool(filename, patch)
                analysis_data = json.loads(analysis_result)
                
                issues = []
                for issue_data in analysis_data.get("issues", []):
                    issue = Issue(
                        file=issue_data.get("file", filename),
                        line=issue_data.get("line"),
                        type=issue_data.get("type", "readability"),
                        description=issue_data.get("description", ""),
                        suggestion=issue_data.get("suggestion", "")
                    )
                    issues.append(issue)
                    total_issues += 1
                    if issue.type in [IssueType.BUG, IssueType.SECURITY]:
                        critical_issues += 1
                
                file_analysis = FileAnalysis(
                    name=filename,
                    issues=issues,
                    error=analysis_data.get("error")
                )
                analyzed_files.append(file_analysis)
            
            summary = AnalysisSummary(
                total_files=len(analyzed_files),
                total_issues=total_issues,
                critical_issues=critical_issues
            )
            
            return PRAnalysisResult(
                pr_title=pr_data["pr_title"],
                pr_url=pr_data["pr_url"],
                analyzed_at=datetime.utcnow(),
                files=analyzed_files,
                summary=summary
            )
        
        except Exception as e:
            logger.error(f"Error in agent analysis: {str(e)}")
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
        
        logger.info(f"Starting agentic PR analysis for task {task_id}")
        
        agent_system = CodeReviewAgentSystem(github_token)
        results = agent_system.analyze_pr(repo_url, pr_number)
        
        task_data = get_task(task_id)
        if task_data:
            task_data.status = TaskStatus.COMPLETED
            task_data.results = results
            save_task(task_id, task_data)
        
        logger.info(f"Completed agentic PR analysis for task {task_id}")
    
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
        
        logger.info(f"Created agentic task {task_id}")
        
        return TaskResponse(
            task_id=task_id,
            status=TaskStatus.PENDING,
            message="PR analysis task created successfully with agentic framework"
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
        "message": "AI Code Review Agent (Agentic Architecture with LangChain)",
        "version": "3.0.0",
        "framework": "LangChain Agent Framework",
        "storage": "Redis" if redis_client else "In-Memory",
        "tools": [
            "fetch_pr_data - GitHub PR data retrieval",
            "analyze_code - Code diff analysis",
            "security_scan - Security vulnerability detection",
            "performance_analysis - Performance optimization analysis"
        ],
        "endpoints": {
            "POST /analyze-pr": "Submit a PR for agentic AI review",
            "GET /status/{task_id}": "Check task status",
            "GET /results/{task_id}": "Get comprehensive analysis results"
        }
    }

if __name__ == "__main__":
    import uvicorn
    uvicorn.run("main:app", host="0.0.0.0", port=int(os.getenv("PORT", 8000)), reload=True)
