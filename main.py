from fastapi import FastAPI, HTTPException, BackgroundTasks, Request
from pydantic import BaseModel
import uuid
import os
from datetime import datetime
from typing import Dict, Any
import requests
from groq import Groq
import logging
import json
import redis
from rate_limiter import RateLimiter, rate_limit
from fastapi.middleware.cors import CORSMiddleware

# ============================================================
# LOGGING CONFIG
# ============================================================
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("ai-pr-review")

# ============================================================
# FASTAPI INIT
# ============================================================
app = FastAPI(title="AI Code Review Agent (Ruthless Mode)")

origins = [
    "http://localhost:3000",
    "https://code-bot-rho.vercel.app",
]
app.add_middleware(
    CORSMiddleware,
    allow_origins=origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# ============================================================
# REDIS CONNECTION
# ============================================================
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

# ============================================================
# REQUEST MODEL
# ============================================================
class PRRequest(BaseModel):
    repo_url: str
    pr_number: int
    github_token: str = None

# ============================================================
# CODE REVIEW AGENT
# ============================================================
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

    # ------------------------------------------------------------
    # FETCH PR + FILES
    # ------------------------------------------------------------
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

    # ------------------------------------------------------------
    # ULTRA-STRICT DIFF ANALYSIS
    # ------------------------------------------------------------
    def analyze_file_diff(self, file_data: Dict[str, Any]) -> Dict[str, Any]:
        filename = file_data.get("filename", "")
        patch = file_data.get("patch", "")

        if not patch:
            return {"name": filename, "issues": []}

        logger.info(f"Analyzing file: {filename} (STRICT MODE)")

        prompt = f"""
You are a **ruthless, detail-obsessed senior code reviewer**.  
You review code like a military auditor — find **every** possible issue, from the smallest nitpick to the biggest bug.  
You never say “looks good”. If you find nothing critical, complain about structure, readability, naming, spacing, or missing docs.  
No mercy.

Analyze this GitHub diff:

File: {filename}

Diff:
{patch}

Report even the smallest problems.  

Return **ONLY a valid JSON array** of issues.  
Each issue must have:
- "file": file name  
- "line": approximate line number (integer or null)  
- "type": one of ["bug", "style", "performance", "security", "maintainability", "readability"]  
- "description": concise but specific explanation  
- "suggestion": clear recommendation for fixing or improving  

### Examples
[
  {{
    "file": "{filename}",
    "line": 12,
    "type": "style",
    "description": "Missing space after comma; inconsistent indentation.",
    "suggestion": "Use proper PEP8 spacing and re-indent code."
  }},
  {{
    "file": "{filename}",
    "line": 42,
    "type": "bug",
    "description": "Division by zero risk not handled.",
    "suggestion": "Add a check before division to avoid runtime error."
  }}
]

If code looks fine, **still return style and best-practice feedback**.  
Never return an empty list unless the diff is completely empty.
"""

        try:
            response = self.groq_client.chat.completions.create(
                model="llama-3.3-70b-versatile",
                messages=[
                    {
                        "role": "system",
                        "content": "You are an unforgiving, ultra-strict code reviewer. Output only valid JSON. Never skip small issues.",
                    },
                    {"role": "user", "content": prompt},
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

            issues = json.loads(response_text)
            formatted_issues = []
            for issue in issues if isinstance(issues, list) else []:
                formatted_issues.append({
                    "file": filename,
                    "line": issue.get("line"),
                    "type": issue.get("type"),
                    "description": issue.get("description"),
                    "suggestion": issue.get("suggestion"),
                })

            # If no issues returned (model too lenient), inject forced feedback
            if not formatted_issues:
                formatted_issues = [{
                    "file": filename,
                    "line": None,
                    "type": "readability",
                    "description": "Model returned no issues — likely false negative. Manually mark for readability review.",
                    "suggestion": "Review file structure, variable naming, and consistency manually."
                }]

            return {"name": filename, "issues": formatted_issues}

        except Exception as e:
            logger.error(f"Error analyzing file {filename}: {str(e)}")
            return {"name": filename, "issues": [], "error": str(e)}

    # ------------------------------------------------------------
    # ANALYZE ENTIRE PR
    # ------------------------------------------------------------
    def analyze_pr(self, repo_url: str, pr_number: int) -> Dict[str, Any]:
        try:
            pr_data = self.fetch_pr_data(repo_url, pr_number)
            analyzed_files = []
            total_issues = 0
            critical_issues = 0

            for file_data in pr_data["files"]:
                file_analysis = self.analyze_file_diff(file_data)
                analyzed_files.append(file_analysis)

                for issue in file_analysis.get("issues", []):
                    total_issues += 1
                    if issue.get("type") in ["bug", "security"]:
                        critical_issues += 1

            return {
                "pr_title": pr_data["pr"].get("title", ""),
                "pr_url": pr_data["pr"].get("html_url", ""),
                "analyzed_at": datetime.utcnow().isoformat(),
                "files": analyzed_files,
                "summary": {
                    "total_files": len(analyzed_files),
                    "total_issues": total_issues,
                    "critical_issues": critical_issues,
                },
            }

        except requests.exceptions.HTTPError as e:
            logger.error(f"HTTP error fetching PR data: {str(e)}")
            raise Exception(f"Failed to fetch PR data: {str(e)}")
        except Exception as e:
            logger.error(f"Error in analyze_pr: {str(e)}")
            raise

# ============================================================
# TASK STORAGE HELPERS
# ============================================================
def save_task(task_id: str, data: Dict[str, Any]):
    if redis_client:
        try:
            redis_client.set(f"task:{task_id}", json.dumps(data), ex=86400)
        except Exception as e:
            logger.error(f"Redis save error: {e}")
            tasks_store[task_id] = data
    else:
        tasks_store[task_id] = data


def get_task(task_id: str) -> Dict[str, Any]:
    if redis_client:
        try:
            data = redis_client.get(f"task:{task_id}")
            return json.loads(data) if data else None
        except Exception as e:
            logger.error(f"Redis get error: {e}")
            return tasks_store.get(task_id)
    else:
        return tasks_store.get(task_id)

# ============================================================
# BACKGROUND PROCESS
# ============================================================
def process_pr_analysis(task_id: str, repo_url: str, pr_number: int, github_token: str = None):
    try:
        task_data = get_task(task_id)
        if task_data:
            task_data["status"] = "processing"
            save_task(task_id, task_data)

        logger.info(f"Starting PR analysis for task {task_id}")
        agent = CodeReviewAgent(github_token)
        results = agent.analyze_pr(repo_url, pr_number)

        task_data = get_task(task_id)
        if task_data:
            task_data["status"] = "completed"
            task_data["results"] = results
            save_task(task_id, task_data)

        logger.info(f"Completed PR analysis for task {task_id}")

    except Exception as e:
        logger.error(f"Failed PR analysis for task {task_id}: {str(e)}")
        task_data = get_task(task_id)
        if task_data:
            task_data["status"] = "failed"
            task_data["error"] = str(e)
            save_task(task_id, task_data)

# ============================================================
# ROUTES
# ============================================================
@app.post("/analyze-pr")
@rate_limit(max_requests=10, window_seconds=60)
async def analyze_pr(request: Request, pr_request: PRRequest, background_tasks: BackgroundTasks):
    try:
        task_id = str(uuid.uuid4())
        task_data = {
            "status": "pending",
            "created_at": datetime.utcnow().isoformat(),
            "repo_url": pr_request.repo_url,
            "pr_number": pr_request.pr_number,
        }
        save_task(task_id, task_data)

        background_tasks.add_task(
            process_pr_analysis,
            task_id,
            pr_request.repo_url,
            pr_request.pr_number,
            pr_request.github_token,
        )

        logger.info(f"Created task {task_id}")
        return {"task_id": task_id, "status": "pending", "message": "PR analysis task created successfully"}

    except Exception as e:
        logger.error(f"Error creating task: {str(e)}")
        raise HTTPException(status_code=500, detail=str(e))

@app.get("/status/{task_id}")
async def get_status(task_id: str):
    task_data = get_task(task_id)
    if not task_data:
        raise HTTPException(status_code=404, detail="Task not found")

    response = {
        "task_id": task_id,
        "status": task_data.get("status", "unknown"),
        "created_at": task_data.get("created_at"),
    }
    if task_data.get("status") == "failed":
        response["error"] = task_data.get("error")
    return response

@app.get("/results/{task_id}")
async def get_results(task_id: str):
    task_data = get_task(task_id)
    if not task_data:
        raise HTTPException(status_code=404, detail="Task not found")

    status = task_data.get("status")
    if status in ["pending", "processing"]:
        raise HTTPException(status_code=202, detail=f"Task {status}")
    elif status == "failed":
        raise HTTPException(status_code=500, detail=f"Task failed: {task_data.get('error')}")
    elif status == "completed":
        return {"task_id": task_id, "status": "completed", "results": task_data.get("results", {})}
    else:
        raise HTTPException(status_code=500, detail=f"Unknown task state: {status}")

@app.get("/")
async def root():
    return {
        "message": "AI Code Review Agent (Ruthless Mode, Powered by Groq)",
        "version": "2.1.0",
        "storage": "Redis" if redis_client else "In-Memory",
        "endpoints": {
            "POST /analyze-pr": "Submit a PR for strict AI review",
            "GET /status/{task_id}": "Check task status",
            "GET /results/{task_id}": "Get strict analysis results",
        },
    }

# ============================================================
# ENTRY POINT
# ============================================================
if __name__ == "__main__":
    import uvicorn
    uvicorn.run("main:app", host="0.0.0.0", port=int(os.getenv("PORT", 8000)), reload=True)
