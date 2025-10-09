from fastapi import FastAPI, HTTPException
from pydantic import BaseModel
from celery.result import AsyncResult
import os
from datetime import datetime
from tasks import analyze_pr_task
from database import engine, Base, SessionLocal, Task
import logging

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

Base.metadata.create_all(bind=engine)

app = FastAPI(title="AI Code Review Agent - Production")

class PRRequest(BaseModel):
    repo_url: str
    pr_number: int
    github_token: str = None

def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()

@app.post("/analyze-pr")
async def analyze_pr(request: PRRequest):
    try:
        logger.info(f"Received PR analysis request: {request.repo_url} #{request.pr_number}")
        
        celery_task = analyze_pr_task.delay(
            request.repo_url,
            request.pr_number,
            request.github_token
        )
        
        db = SessionLocal()
        try:
            task = Task(
                task_id=celery_task.id,
                status="pending",
                repo_url=request.repo_url,
                pr_number=request.pr_number,
                created_at=datetime.utcnow()
            )
            db.add(task)
            db.commit()
            db.refresh(task)
        finally:
            db.close()
        
        logger.info(f"Created task {celery_task.id}")
        
        return {
            "task_id": celery_task.id,
            "status": "pending",
            "message": "PR analysis task created successfully"
        }
    except Exception as e:
        logger.error(f"Error creating task: {str(e)}")
        raise HTTPException(status_code=500, detail=str(e))

@app.get("/status/{task_id}")
async def get_status(task_id: str):
    try:
        db = SessionLocal()
        try:
            task = db.query(Task).filter(Task.task_id == task_id).first()
            if not task:
                raise HTTPException(status_code=404, detail="Task not found")
            
            celery_task = AsyncResult(task_id)
            
            status_map = {
                "PENDING": "pending",
                "STARTED": "processing",
                "SUCCESS": "completed",
                "FAILURE": "failed"
            }
            
            current_status = status_map.get(celery_task.state, celery_task.state.lower())
            
            if task.status != current_status:
                task.status = current_status
                if current_status == "failed" and celery_task.state == "FAILURE":
                    task.error = str(celery_task.info)
                db.commit()
            
            response = {
                "task_id": task_id,
                "status": task.status,
                "created_at": task.created_at.isoformat() if task.created_at else None
            }
            
            if task.error:
                response["error"] = task.error
            
            return response
        finally:
            db.close()
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error getting status: {str(e)}")
        raise HTTPException(status_code=500, detail=str(e))

@app.get("/results/{task_id}")
async def get_results(task_id: str):
    try:
        db = SessionLocal()
        try:
            task = db.query(Task).filter(Task.task_id == task_id).first()
            if not task:
                raise HTTPException(status_code=404, detail="Task not found")
            
            celery_task = AsyncResult(task_id)
            
            if celery_task.state == "PENDING":
                raise HTTPException(status_code=202, detail="Task is still pending")
            elif celery_task.state == "STARTED":
                raise HTTPException(status_code=202, detail="Task is being processed")
            elif celery_task.state == "FAILURE":
                error_msg = str(celery_task.info)
                task.status = "failed"
                task.error = error_msg
                db.commit()
                raise HTTPException(status_code=500, detail=f"Task failed: {error_msg}")
            elif celery_task.state == "SUCCESS":
                results = celery_task.get()
                
                task.status = "completed"
                task.results = results
                db.commit()
                
                return {
                    "task_id": task_id,
                    "status": "completed",
                    "results": results
                }
            else:
                raise HTTPException(status_code=500, detail=f"Unknown task state: {celery_task.state}")
        finally:
            db.close()
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error getting results: {str(e)}")
        raise HTTPException(status_code=500, detail=str(e))

@app.get("/")
async def root():
    return {
        "message": "AI Code Review Agent API - Production",
        "version": "1.0.0",
        "endpoints": {
            "POST /analyze-pr": "Submit a PR for analysis",
            "GET /status/{task_id}": "Check task status",
            "GET /results/{task_id}": "Get analysis results"
        }
    }

@app.get("/health")
async def health_check():
    return {"status": "healthy", "timestamp": datetime.utcnow().isoformat()}
