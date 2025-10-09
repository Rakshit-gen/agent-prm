from fastapi import FastAPI, HTTPException, BackgroundTasks
from pydantic import BaseModel
import uuid
import os
from datetime import datetime
from typing import Dict, Any
import requests
from openai import OpenAI
import logging
import json
import redis

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

app = FastAPI(title="AI Code Review Agent")

REDIS_URL = os.getenv("REDIS_URL")
if not REDIS_URL:
    raise Exception("REDIS_URL environment variable not set!")

redis_client = redis.from_url(REDIS_URL, decode_responses=True)

class PRRequest(BaseModel):
    repo_url: str
    pr_number: int
    github_token: str = None

class CodeReviewAgent:
    def __init__(self, github_token: str = None):
        self.github_token = github_token or os.getenv('GITHUB_TOKEN')
        self.openai_client = OpenAI(api_key=os.getenv('OPENAI_API_KEY'))
        self.headers = {}
        if self.github_token:
            self.headers['Authorization'] = f'token {self.github_token}'
        
    def fetch_pr_data(self, repo_url: str, pr_number: int) -> Dict[str, Any]:
        parts = repo_url.rstrip('/').split('github.com/')[-1].split('/')
        owner = parts[0]
        repo = parts[1]
        
        logger.info(f"Fetching PR data for {owner}/{repo} #{pr_number}")
        
        pr_url = f"https://api.github.com/repos/{owner}/{repo}/pulls/{pr_number}"
        response = requests.get(pr_url, headers=self.headers)
        response.raise_for_status()
        pr_data = response.json()
        
        files_url = f"https://api.github.com/repos/{owner}/{repo}/pulls/{pr_number}/files"
        response = requests.get(files_url, headers=self.headers)
        response.raise_for_status()
        files_data = response.json()
        
        return {
            'pr': pr_data,
            'files': files_data
        }
    
    def analyze_file_diff(self, file_data: Dict[str, Any]) -> Dict[str, Any]:
        filename = file_data.get('filename', '')
        patch = file_data.get('patch', '')
        
        if not patch:
            return {
                'name': filename,
                'issues': []
            }
        
        logger.info(f"Analyzing file: {filename}")
        
        prompt = f"""You are an expert code reviewer. Analyze the following code diff and identify issues.

File: {filename}
Diff:
{patch}

Provide a structured analysis focusing on:
1. Code style and formatting issues
2. Potential bugs or errors
3. Performance improvements
4. Best practices violations

For each issue found, provide:
- type: "style", "bug", "performance", or "best_practice"
- line: the line number (extract from diff context)
- description: brief description of the issue
- suggestion: how to fix it

Return ONLY a JSON array of issues. If no issues, return an empty array.
Example format:
[
  {{"type": "style", "line": 15, "description": "Line too long", "suggestion": "Break into multiple lines"}},
  {{"type": "bug", "line": 23, "description": "Potential null pointer", "suggestion": "Add null check"}}
]"""

        try:
            response = self.openai_client.chat.completions.create(
                model="gpt-4o",
                messages=[
                    {"role": "system", "content": "You are an expert code reviewer. Return only valid JSON."},
                    {"role": "user", "content": prompt}
                ],
                temperature=0.3,
                max_tokens=2048
            )
            
            response_text = response.choices[0].message.content.strip()
            
            if response_text.startswith('```json'):
                response_text = response_text[7:]
            if response_text.endswith('```'):
                response_text = response_text[:-3]
            response_text = response_text.strip()
            
            issues = json.loads(response_text)
            
            return {
                'name': filename,
                'issues': issues if isinstance(issues, list) else []
            }
        except Exception as e:
            logger.error(f"Error analyzing file {filename}: {str(e)}")
            return {
                'name': filename,
                'issues': []
            }
    
    def analyze_pr(self, repo_url: str, pr_number: int) -> Dict[str, Any]:
        try:
            pr_data = self.fetch_pr_data(repo_url, pr_number)
            
            analyzed_files = []
            total_issues = 0
            critical_issues = 0
            
            for file_data in pr_data['files']:
                file_analysis = self.analyze_file_diff(file_data)
                analyzed_files.append(file_analysis)
                
                for issue in file_analysis['issues']:
                    total_issues += 1
                    if issue.get('type') in ['bug', 'security']:
                        critical_issues += 1
            
            return {
                'pr_title': pr_data['pr'].get('title', ''),
                'pr_url': pr_data['pr'].get('html_url', ''),
                'analyzed_at': datetime.utcnow().isoformat(),
                'files': analyzed_files,
                'summary': {
                    'total_files': len(analyzed_files),
                    'total_issues': total_issues,
                    'critical_issues': critical_issues
                }
            }
        except requests.exceptions.HTTPError as e:
            logger.error(f"HTTP error fetching PR data: {str(e)}")
            raise Exception(f"Failed to fetch PR data: {str(e)}")
        except Exception as e:
            logger.error(f"Error in analyze_pr: {str(e)}")
            raise

def process_pr_analysis(task_id: str, repo_url: str, pr_number: int, github_token: str = None):
    try:
        redis_client.hset(f"task:{task_id}", "status", "processing")
        logger.info(f"Starting PR analysis for task {task_id}")
        
        agent = CodeReviewAgent(github_token)
        results = agent.analyze_pr(repo_url, pr_number)
        
        redis_client.hset(f"task:{task_id}", "status", "completed")
        redis_client.hset(f"task:{task_id}", "results", json.dumps(results))
        logger.info(f"Completed PR analysis for task {task_id}")
    except Exception as e:
        redis_client.hset(f"task:{task_id}", "status", "failed")
        redis_client.hset(f"task:{task_id}", "error", str(e))
        logger.error(f"Failed PR analysis for task {task_id}: {str(e)}")

@app.post("/analyze-pr")
async def analyze_pr(request: PRRequest, background_tasks: BackgroundTasks):
    try:
        task_id = str(uuid.uuid4())
        
        redis_client.hset(f"task:{task_id}", mapping={
            "status": "pending",
            "created_at": datetime.utcnow().isoformat(),
            "repo_url": request.repo_url,
            "pr_number": str(request.pr_number)
        })
        redis_client.expire(f"task:{task_id}", 86400)
        
        background_tasks.add_task(
            process_pr_analysis,
            task_id,
            request.repo_url,
            request.pr_number,
            request.github_token
        )
        
        logger.info(f"Created task {task_id}")
        
        return {
            "task_id": task_id,
            "status": "pending",
            "message": "PR analysis task created successfully"
        }
    except Exception as e:
        logger.error(f"Error creating task: {str(e)}")
        raise HTTPException(status_code=500, detail=str(e))

@app.get("/status/{task_id}")
async def get_status(task_id: str):
    try:
        task_data = redis_client.hgetall(f"task:{task_id}")
        
        if not task_data:
            raise HTTPException(status_code=404, detail="Task not found")
        
        response = {
            "task_id": task_id,
            "status": task_data.get('status', 'unknown'),
            "created_at": task_data.get('created_at')
        }
        
        if task_data.get('status') == 'failed':
            response['error'] = task_data.get('error')
        
        return response
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error getting status: {str(e)}")
        raise HTTPException(status_code=500, detail=str(e))

@app.get("/results/{task_id}")
async def get_results(task_id: str):
    try:
        task_data = redis_client.hgetall(f"task:{task_id}")
        
        if not task_data:
            raise HTTPException(status_code=404, detail="Task not found")
        
        status = task_data.get('status')
        
        if status == 'pending':
            raise HTTPException(status_code=202, detail="Task is still pending")
        elif status == 'processing':
            raise HTTPException(status_code=202, detail="Task is being processed")
        elif status == 'failed':
            raise HTTPException(status_code=500, detail=f"Task failed: {task_data.get('error')}")
        elif status == 'completed':
            results = json.loads(task_data.get('results', '{}'))
            return {
                "task_id": task_id,
                "status": "completed",
                "results": results
            }
        else:
            raise HTTPException(status_code=500, detail=f"Unknown task state: {status}")
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error getting results: {str(e)}")
        raise HTTPException(status_code=500, detail=str(e))

@app.get("/")
async def root():
    return {
        "message": "AI Code Review Agent API",
        "version": "1.0.0",
        "endpoints": {
            "POST /analyze-pr": "Submit a PR for analysis",
            "GET /status/{task_id}": "Check task status",
            "GET /results/{task_id}": "Get analysis results"
        }
    }

@app.get("/health")
async def health_check():
    try:
        redis_client.ping()
        return {
            "status": "healthy",
            "redis": "connected",
            "timestamp": datetime.utcnow().isoformat()
        }
    except Exception as e:
        return {
            "status": "unhealthy",
            "redis": "disconnected",
            "error": str(e),
            "timestamp": datetime.utcnow().isoformat()
        }
