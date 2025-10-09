from celery import Celery
from agent import CodeReviewAgent
import logging
import os

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

REDIS_URL = os.getenv("REDIS_URL", "redis://localhost:6379/0")

celery_app = Celery(
    'code_review',
    broker=REDIS_URL,
    backend=REDIS_URL
)

celery_app.conf.update(
    task_serializer='json',
    accept_content=['json'],
    result_serializer='json',
    timezone='UTC',
    enable_utc=True,
    task_track_started=True,
    task_time_limit=600,
    task_soft_time_limit=540,
    broker_connection_retry_on_startup=True,
)

@celery_app.task(bind=True, name='tasks.analyze_pr_task')
def analyze_pr_task(self, repo_url: str, pr_number: int, github_token: str = None):
    try:
        logger.info(f"Starting PR analysis for {repo_url} #{pr_number}")
        
        self.update_state(state='STARTED', meta={'status': 'Initializing agent'})
        
        agent = CodeReviewAgent(github_token)
        
        self.update_state(state='STARTED', meta={'status': 'Analyzing PR'})
        
        results = agent.analyze_pr(repo_url, pr_number)
        
        logger.info(f"Completed PR analysis for {repo_url} #{pr_number}")
        
        return results
    except Exception as e:
        logger.error(f"Error analyzing PR: {str(e)}")
        raise