import pytest
from fastapi.testclient import TestClient
from unittest.mock import patch, MagicMock
from main import app
import json

client = TestClient(app)

@pytest.fixture
def mock_redis():
    with patch('main.redis_client') as mock:
        yield mock

@pytest.fixture
def mock_task():
    with patch('main.analyze_pr_task') as mock:
        task = MagicMock()
        task.id = 'test-task-123'
        mock.delay.return_value = task
        yield mock

def test_root():
    response = client.get("/")
    assert response.status_code == 200
    assert "message" in response.json()

def test_analyze_pr_success(mock_redis, mock_task):
    response = client.post("/analyze-pr", json={
        "repo_url": "https://github.com/test/repo",
        "pr_number": 1
    })
    assert response.status_code == 200
    data = response.json()
    assert "task_id" in data
    assert data["status"] == "pending"

def test_analyze_pr_invalid_data():
    response = client.post("/analyze-pr", json={
        "repo_url": "https://github.com/test/repo"
    })
    assert response.status_code == 422

@patch('main.AsyncResult')
def test_get_status_pending(mock_async_result, mock_redis):
    task_id = "test-task-123"
    mock_result = MagicMock()
    mock_result.state = "PENDING"
    mock_async_result.return_value = mock_result
    
    mock_redis.get.return_value = json.dumps({
        "status": "pending",
        "created_at": "2024-01-01T00:00:00"
    })
    
    response = client.get(f"/status/{task_id}")
    assert response.status_code == 200
    data = response.json()
    assert data["status"] == "pending"

@patch('main.AsyncResult')
def test_get_status_not_found(mock_async_result, mock_redis):
    task_id = "nonexistent-task"
    mock_redis.get.return_value = None
    
    response = client.get(f"/status/{task_id}")
    assert response.status_code == 404

@patch('main.AsyncResult')
def test_get_results_success(mock_async_result, mock_redis):
    task_id = "test-task-123"
    mock_result = MagicMock()
    mock_result.state = "SUCCESS"
    mock_result.get.return_value = {
        "files": [],
        "summary": {"total_files": 0, "total_issues": 0, "critical_issues": 0}
    }
    mock_async_result.return_value = mock_result
    
    response = client.get(f"/results/{task_id}")
    assert response.status_code == 200
    data = response.json()
    assert data["status"] == "completed"
    assert "results" in data

@patch('main.AsyncResult')
def test_get_results_pending(mock_async_result):
    task_id = "test-task-123"
    mock_result = MagicMock()
    mock_result.state = "PENDING"
    mock_async_result.return_value = mock_result
    
    response = client.get(f"/results/{task_id}")
    assert response.status_code == 202