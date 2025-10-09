# AI Code Review Agent

An autonomous code review agent system that uses AI to analyze GitHub pull requests asynchronously.

## Features

- Asynchronous PR analysis using Celery
- AI-powered code review with Claude
- RESTful API with FastAPI
- Redis for task queue and caching
- Docker support for easy deployment
- Comprehensive test coverage

## Architecture

- **FastAPI**: REST API endpoints
- **Celery**: Asynchronous task processing
- **Redis**: Message broker and result backend
- **Anthropic Claude**: AI code analysis
- **GitHub API**: Fetch PR data and diffs

## Setup

### Prerequisites

- Python 3.11+
- Redis
- Anthropic API key
- GitHub token (optional, for private repos)

### Local Setup

1. Clone the repository

```bash
git clone <repo-url>
cd code-review-agent
```

2. Install dependencies

```bash
pip install -r requirements.txt
```

3. Configure environment variables

```bash
cp .env.example .env
```

Edit `.env` and add your API keys:

```
ANTHROPIC_API_KEY=your_anthropic_api_key
GITHUB_TOKEN=your_github_token
```

4. Start Redis

```bash
redis-server
```

5. Start Celery worker

```bash
celery -A tasks worker --loglevel=info
```

6. Start FastAPI server

```bash
uvicorn main:app --reload
```

The API will be available at `http://localhost:8000`

### Docker Setup

1. Build and start services

```bash
docker-compose up --build
```

This starts:
- Redis on port 6379
- API server on port 8000
- Celery worker

## API Documentation

### POST /analyze-pr

Submit a PR for analysis.

**Request:**

```bash
curl -X POST http://localhost:8000/analyze-pr \
  -H "Content-Type: application/json" \
  -d '{
    "repo_url": "https://github.com/user/repo",
    "pr_number": 123,
    "github_token": "optional_token"
  }'
```

**Response:**

```json
{
  "task_id": "abc123",
  "status": "pending",
  "message": "PR analysis task created successfully"
}
```

### GET /status/{task_id}

Check the status of an analysis task.

**Request:**

```bash
curl http://localhost:8000/status/abc123
```

**Response:**

```json
{
  "task_id": "abc123",
  "status": "processing",
  "created_at": "2024-01-01T00:00:00"
}
```

Status values: `pending`, `processing`, `completed`, `failed`

### GET /results/{task_id}

Retrieve analysis results.

**Request:**

```bash
curl http://localhost:8000/results/abc123
```

**Response:**

```json
{
  "task_id": "abc123",
  "status": "completed",
  "results": {
    "pr_title": "Add new feature",
    "pr_url": "https://github.com/user/repo/pull/123",
    "analyzed_at": "2024-01-01T00:00:00",
    "files": [
      {
        "name": "main.py",
        "issues": [
          {
            "type": "style",
            "line": 15,
            "description": "Line too long",
            "suggestion": "Break line into multiple lines"
          },
          {
            "type": "bug",
            "line": 23,
            "description": "Potential null pointer",
            "suggestion": "Add null check"
          }
        ]
      }
    ],
    "summary": {
      "total_files": 1,
      "total_issues": 2,
      "critical_issues": 1
    }
  }
}
```

## Running Tests

```bash
pytest -v
```

With coverage:

```bash
pytest --cov=. --cov-report=html
```

## Design Decisions

### Technology Choices

1. **FastAPI**: Modern, fast framework with automatic API documentation
2. **Celery + Redis**: Robust asynchronous task processing with result persistence
3. **Anthropic Claude**: Advanced AI for nuanced code analysis
4. **GitHub API**: Direct access to PR data without cloning repos

### Architecture Patterns

1. **Separation of Concerns**: API, tasks, and agent logic are separated
2. **Async Processing**: Long-running analysis doesn't block API responses
3. **Caching**: Redis stores task metadata and results for quick access
4. **Error Handling**: Comprehensive error handling at each layer

### AI Agent Design

The agent follows a goal-oriented approach:
1. Fetch PR data from GitHub API
2. Analyze each file's diff independently
3. Use Claude to identify issues with structured prompts
4. Aggregate results with summary statistics

Issue types analyzed:
- **style**: Code formatting and style violations
- **bug**: Potential bugs and errors
- **performance**: Performance optimization opportunities
- **best_practice**: Violations of coding best practices

## Future Improvements

1. **Multi-language Support**: Language-specific analysis rules
2. **Custom Rules**: Allow users to define custom review criteria
3. **GitHub Integration**: Webhook support for automatic PR reviews
4. **Rate Limiting**: Protect API from abuse
5. **Authentication**: User authentication and authorization
6. **Database**: PostgreSQL for persistent storage
7. **Batch Processing**: Analyze multiple PRs simultaneously
8. **Incremental Analysis**: Only analyze changed lines
9. **ML Model Fine-tuning**: Train custom models on historical reviews
10. **Comment Integration**: Post results directly to GitHub PR comments
11. **Comparison Reports**: Compare with previous PR versions
12. **Team Analytics**: Aggregate insights across team PRs

## Project Structure

```
.
├── main.py              # FastAPI application
├── tasks.py             # Celery tasks
├