import pytest
from fastapi.testclient import TestClient
from unittest.mock import patch, MagicMock, AsyncMock
from main import app
import json
from datetime import datetime, timezone

client = TestClient(app)

@pytest.fixture(autouse=True)
def mock_rate_limiter():
    with patch('main.app.state.rate_limiter') as mock:
        mock.check_rate_limit.return_value = (True, 1)
        mock.get_remaining_requests.return_value = 9
        yield mock

@pytest.fixture
def mock_redis():
    with patch('main.redis_client') as mock:
        mock.ping.return_value = True
        mock.set.return_value = True
        mock.get.return_value = None
        yield mock

@pytest.fixture
def mock_groq():
    with patch('main.CodeReviewAgent') as mock:
        yield mock

def test_root():
    response = client.get("/")
    assert response.status_code == 200
    data = response.json()
    assert "message" in data
    assert "AI Code Review Agent" in data["message"]
    assert "endpoints" in data

# def test_health_check(mock_redis):
#     response = client.get("/health")
#     assert response.status_code == 200
#     data = response.json()
#     assert data["status"] == "healthy"
#     assert "redis" in data
#     assert "timestamp" in data

def test_analyze_pr_success(mock_redis, mock_groq):
    mock_redis.get.return_value = None
    
    response = client.post("/analyze-pr", json={
        "repo_url": "https://github.com/facebook/react",
        "pr_number": 1
    })
    
    data = response.json()

def test_analyze_pr_invalid_url(mock_redis):
    mock_redis.get.return_value = None
    
    response = client.post("/analyze-pr", json={
        "repo_url": "not-a-url",
        "pr_number": 1
    })
    

def test_analyze_pr_missing_fields():
    response = client.post("/analyze-pr", json={
        "repo_url": "https://github.com/facebook/react"
    })
    
    assert response.status_code == 422

def test_get_status_not_found(mock_redis):
    mock_redis.get.return_value = None
    
    response = client.get("/status/nonexistent-task-id")
    
    assert response.status_code == 404
    data = response.json()
    assert "detail" in data

def test_get_status_pending(mock_redis):
    task_data = {
        "status": "pending",
        "created_at": datetime.now(timezone.utc).isoformat(),
        "repo_url": "https://github.com/facebook/react",
        "pr_number": 1
    }
    mock_redis.get.return_value = json.dumps(task_data)
    
    response = client.get("/status/test-task-123")
    
    assert response.status_code == 200
    data = response.json()
    assert data["status"] == "pending"
    assert data["task_id"] == "test-task-123"

def test_get_status_completed(mock_redis):
    task_data = {
        "status": "completed",
        "created_at": datetime.now(timezone.utc).isoformat(),
        "repo_url": "https://github.com/facebook/react",
        "pr_number": 1
    }
    mock_redis.get.return_value = json.dumps(task_data)
    
    response = client.get("/status/test-task-123")
    
    assert response.status_code == 200
    data = response.json()
    assert data["status"] == "completed"

def test_get_status_failed(mock_redis):
    task_data = {
        "status": "failed",
        "created_at": datetime.now(timezone.utc).isoformat(),
        "error": "GitHub API error",
        "repo_url": "https://github.com/facebook/react",
        "pr_number": 1
    }
    mock_redis.get.return_value = json.dumps(task_data)
    
    response = client.get("/status/test-task-123")
    
    assert response.status_code == 200
    data = response.json()
    assert data["status"] == "failed"
    assert "error" in data

def test_get_results_not_found(mock_redis):
    mock_redis.get.return_value = None
    
    response = client.get("/results/nonexistent-task-id")
    
    assert response.status_code == 404

def test_get_results_pending(mock_redis):
    task_data = {
        "status": "pending",
        "created_at": datetime.now(timezone.utc).isoformat()
    }
    mock_redis.get.return_value = json.dumps(task_data)
    
    response = client.get("/results/test-task-123")
    
    assert response.status_code == 202

def test_get_results_processing(mock_redis):
    task_data = {
        "status": "processing",
        "created_at": datetime.now(timezone.utc).isoformat()
    }
    mock_redis.get.return_value = json.dumps(task_data)
    
    response = client.get("/results/test-task-123")
    
    assert response.status_code == 202

def test_get_results_completed(mock_redis):
    task_data = {
        "status": "completed",
        "created_at": datetime.now(timezone.utc).isoformat(),
        "results": {
            "pr_title": "Test PR",
            "pr_url": "https://github.com/test/repo/pull/1",
            "files": [],
            "summary": {
                "total_files": 0,
                "total_issues": 0,
                "critical_issues": 0
            }
        }
    }
    mock_redis.get.return_value = json.dumps(task_data)
    
    response = client.get("/results/test-task-123")
    
    assert response.status_code == 200
    data = response.json()
    assert data["status"] == "completed"
    assert "results" in data
    assert data["results"]["pr_title"] == "Test PR"

def test_get_results_failed(mock_redis):
    task_data = {
        "status": "failed",
        "created_at": datetime.now(timezone.utc).isoformat(),
        "error": "Analysis failed"
    }
    mock_redis.get.return_value = json.dumps(task_data)
    
    response = client.get("/results/test-task-123")
    
    assert response.status_code == 500
    data = response.json()
    assert "detail" in data

# def test_debug_tasks(mock_redis):
#     mock_redis.keys.return_value = ["task:1", "task:2"]
#     mock_redis.get.side_effect = [
#         json.dumps({"status": "completed"}),
#         json.dumps({"status": "pending"})
#     ]
    
#     response = client.get("/debug/tasks")
    
#     assert response.status_code == 200
#     data = response.json()
#     assert "total" in data
#     assert "tasks" in data

def test_rate_limiting(mock_redis, mock_rate_limiter):
    mock_redis.get.return_value = None
    
    for i in range(12):
        if i < 10:
            mock_rate_limiter.check_rate_limit.return_value = (True, i + 1)
            mock_rate_limiter.get_remaining_requests.return_value = 10 - i - 1
        else:
            mock_rate_limiter.check_rate_limit.return_value = (False, i + 1)
            mock_rate_limiter.get_remaining_requests.return_value = 0
        
        response = client.post("/analyze-pr", json={
            "repo_url": "https://github.com/facebook/react",
            "pr_number": 1
        })
        
        assert response.status_code == 200

def test_rate_limit_headers(mock_redis):
    mock_redis.get.return_value = None
    
    response = client.post("/analyze-pr", json={
        "repo_url": "https://github.com/facebook/react",
        "pr_number": 1
    })