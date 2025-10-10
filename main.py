from fastapi import FastAPI, HTTPException, BackgroundTasks, Request
from pydantic import BaseModel
from datetime import datetime
from typing import Dict, Any, Optional
import uuid
import os
import requests
import json
import redis
import logging
from groq import Groq

# Import the fixed rate limiter
from rate_limiter import RateLimiter, rate_limit

# Logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

app = FastAPI(title="AI Code Review Agent")

# Redis setup
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

# Storage fallback
tasks_store: Dict[str, Dict[str, Any]] = {}

class PRRequest(BaseModel):
    repo_url: str
    pr_number: int
    github_token: Optional[str] = None

def save_task(task_id: str, data: Dict[str, Any]):
    if redis_client:
        try:
            redis_client.set(f"task:{task_id}", json.dumps(data), ex=86400)
        except Exception as e:
            logger.error(f"Redis save error: {e}")
            tasks_store[task_id] = data
    else:
        tasks_store[task_id] = data

def get_task(task_id: str) -> Optional[Dict[str, Any]]:
    if redis_client:
        try:
            data = redis_client.get(f"task:{task_id}")
            return json.loads(data) if data else None
        except Exception as e:
            logger.error(f"Redis get error: {e}")
            return tasks_store.get(task_id)
    return tasks_store.get(task_id)


# ------------------------------------------------------
#  Core Code Review Agent
# ------------------------------------------------------
class CodeReviewAgent:
    def __init__(self, github_token: str = None):
        self.github_token = github_token or os.getenv("GITHUB_TOKEN")
        groq_api_key = os.getenv("GROQ_API_KEY")
        if not groq_api_key:
            raise ValueError("GROQ_API_KEY not found")
        self.groq_client = Groq(api_key=groq_api_key)
        self.headers = {"Authorization": f"token {self.github_token}"} if self.github_token else {}

    def fetch_pr_data(self, repo_url: str, pr_number: int) -> Dict[str, Any]:
        parts = repo_url.rstrip("/").split("github.com/")[-1].split("/")
        owner, repo = parts[0], parts[1]
        logger.info(f"Fetching PR data for {owner}/{repo} #{pr_number}")

        pr_url = f"https://api.github.com/repos/{owner}/{repo}/pulls/{pr_number}"
        files_url = f"https://api.github.com/repos/{owner}/{repo}/pulls/{pr_number}/files"

        pr_data = requests.get(pr_url, headers=self.headers).json()
        files_data = requests.get(files_url, headers=self.headers).json()
        return {"pr": pr_data, "files": files_data}

    def analyze_file_diff(self, file_data: Dict[str, Any]) -> Dict[str, Any]:
        filename = file_data.get("filename", "")
        patch = file_data.get("patch", "")
        if not patch:
            return {"name": filename, "issues": []}

        prompt = f"""
You are a strict code reviewer. Analyze this diff and list all issues in JSON.

File: {filename}
Diff:
{patch}
"""
        try:
            response = self.groq_client.chat.completions.create(
                model="llama-3.3-70b-versatile",
                messages=[
                    {"role": "system", "content": "Return only valid JSON"},
                    {"role": "user", "content": prompt},
                ],
                temperature=0.2,
                max_tokens=2048,
            )
            text = response.choices[0].message.content.strip()
            if text.startswith("```json"):
                text = text[7:]
            if text.endswith("```"):
                text = text[:-3]
            issues = json.loads(text.strip())
            return {"name": filename, "issues": issues if isinstance(issues, list) else []}
        except Exception as e:
            logger.error(f"Error analyzing {filename}: {e}")
            return {"name": filename, "issues": [], "error": str(e)}

    def analyze_pr(self, repo_url: str, pr_number: int) -> Dict[str, Any]:
        pr_data = self.fetch_pr_data(repo_url, pr_number)
        analyzed, total, critical = [], 0, 0

        for f in pr_data["files"]:
            result = self.analyze_file_diff(f)
            analyzed.append(result)
            for issue in result.get("issues", []):
                total += 1
                if issue.get("type") in ["bug", "security"]:
                    critical += 1

        return {
            "pr_title": pr_data["pr"].get("title", ""),
            "pr_url": pr_data["pr"].get("html_url", ""),
            "analyzed_at": datetime.utcnow().isoformat(),
            "files": analyzed,
            "summary": {
                "total_files": len(analyzed),
                "total_issues": total,
                "critical_issues": critical,
            },
        }


# ------------------------------------------------------
#  Background Processing
# ------------------------------------------------------
def process_pr_analysis(task_id: str, repo_url: str, pr_number: int, github_token: Optional[str]):
    try:
        task = get_task(task_id)
        if task:
            task["status"] = "processing"
            save_task(task_id, task)

        agent = CodeReviewAgent(github_token)
        result = agent.analyze_pr(repo_url, pr_number)

        task["status"] = "completed"
        task["results"] = result
        save_task(task_id, task)
        logger.info(f"Task {task_id} completed")
    except Exception as e:
        logger.error(f"Task {task_id} failed: {e}")
        task = get_task(task_id)
        if task:
            task["status"] = "failed"
            task["error"] = str(e)
            save_task(task_id, task)


# ------------------------------------------------------
#  Routes
# ------------------------------------------------------
@app.post("/analyze-pr")
@rate_limit(max_requests=10, window_seconds=60)
async def analyze_pr(request: Request, pr_request: PRRequest, background_tasks: BackgroundTasks):
    task_id = str(uuid.uuid4())
    task = {
        "status": "pending",
        "created_at": datetime.utcnow().isoformat(),
        "repo_url": pr_request.repo_url,
        "pr_number": pr_request.pr_number,
    }
    save_task(task_id, task)
    background_tasks.add_task(process_pr_analysis, task_id, pr_request.repo_url, pr_request.pr_number, pr_request.github_token)
    return {"task_id": task_id, "status": "pending", "message": "PR analysis started"}


@app.get("/status/{task_id}")
async def get_status(task_id: str):
    task = get_task(task_id)
    if not task:
        raise HTTPException(status_code=404, detail="Task not found")
    return task


@app.get("/results/{task_id}")
async def get_results(task_id: str):
    task = get_task(task_id)
    if not task:
        raise HTTPException(status_code=404, detail="Task not found")
    if task.get("status") in ["pending", "processing"]:
        raise HTTPException(status_code=202, detail=f"Task is {task['status']}")
    if task.get("status") == "failed":
        raise HTTPException(status_code=500, detail=f"Task failed: {task['error']}")
    return {"task_id": task_id, "results": task["results"]}


@app.get("/")
async def root():
    return {
        "message": "AI Code Review Agent (Groq-powered)",
        "storage": "Redis" if redis_client else "In-memory",
        "version": "1.0.0",
    }


@app.get("/health")
async def health():
    redis_status = "connected"
    try:
        if redis_client:
            redis_client.ping()
        else:
            redis_status = "disabled"
    except:
        redis_status = "error"
    return {
        "status": "healthy",
        "redis": redis_status,
        "ai": "groq-llama-3.3-70b",
        "timestamp": datetime.utcnow().isoformat(),
    }
