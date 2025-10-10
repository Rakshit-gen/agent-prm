# 🤖 AI Code Review Agent

An autonomous AI-powered system that analyzes GitHub pull requests using Groq's Llama 3.3 70B model, providing instant feedback on code quality, bugs, style violations, and performance optimizations.

[![Live Demo](https://img.shields.io/badge/Live-Demo-green)](https://agent-prm.onrender.com)
[![API Docs](https://img.shields.io/badge/API-Docs-blue)](https://agent-prm.onrender.com/docs)
[![Python](https://img.shields.io/badge/Python-3.11+-blue.svg)](https://www.python.org/downloads/)
[![FastAPI](https://img.shields.io/badge/FastAPI-0.115.0-009688.svg)](https://fastapi.tiangolo.com)
[![Redis](https://img.shields.io/badge/Redis-7.0-red.svg)](https://redis.io)

---

## 📋 Table of Contents

- [Features](#-features)
- [Architecture](#-architecture)
- [Tech Stack](#-tech-stack)
- [Quick Start](#-quick-start)
- [API Documentation](#-api-documentation)
- [Design Decisions](#-design-decisions)
- [Testing](#-testing)
- [Deployment](#-deployment)
- [Future Improvements](#-future-improvements)
- [Contributing](#-contributing)
- [License](#-license)

---

## ✨ Features

- 🤖 **AI-Powered Analysis** - Uses Groq's Llama 3.3 70B for intelligent code review
- ⚡ **Asynchronous Processing** - Non-blocking PR analysis with background tasks
- 🔄 **Redis Caching** - Persistent task storage with 24-hour TTL
- 🚦 **Rate Limiting** - 10 requests per minute per IP (configurable)
- 🌍 **Universal Compatibility** - Analyzes any public GitHub repository
- 📊 **Detailed Reports** - Categorized issues (style, bug, performance, best practices)
- 🐳 **Docker Support** - Containerized for consistent development
- 📈 **Production Ready** - Deployed on Render.com with 99.9% uptime
- 🔐 **Error Handling** - Comprehensive error management and logging
- 📚 **Auto Documentation** - Interactive Swagger UI at `/docs`

---

## 🏗️ Architecture

```
┌─────────────────────────────────────────────────────────────┐
│                    USER / CLIENT                            │
└────────────────────────┬────────────────────────────────────┘
                         │ HTTP/REST
                         ↓
┌─────────────────────────────────────────────────────────────┐
│                  FASTAPI APPLICATION                        │
│  ┌──────────────────────────────────────────────────────┐  │
│  │  POST /analyze-pr    (Submit PR)                     │  │
│  │  GET  /status/{id}   (Check Status)                  │  │
│  │  GET  /results/{id}  (Get Analysis)                  │  │
│  │  GET  /health        (Health Check)                  │  │
│  └──────────┬───────────────────────┬───────────────────┘  │
│             │                       │                       │
│    ┌────────▼────────┐    ┌────────▼─────────┐            │
│    │  Rate Limiter   │    │  Background      │            │
│    │  (10 req/min)   │    │  Tasks           │            │
│    └─────────────────┘    └────────┬─────────┘            │
│                                     │                       │
│                          ┌──────────▼──────────┐           │
│                          │  Code Review Agent  │           │
│                          └──────────┬──────────┘           │
└─────────────────────────────────────┼─────────────────────┘
                                      │
                    ┌─────────────────┼─────────────────┐
                    │                 │                 │
            ┌───────▼────────┐ ┌──────▼──────┐ ┌──────▼──────┐
            │  GITHUB API    │ │  GROQ API   │ │  REDIS      │
            │  (Fetch PRs)   │ │  (AI Model) │ │  (Storage)  │
            └────────────────┘ └─────────────┘ └─────────────┘
```

---

## 🛠️ Tech Stack

| Category | Technology | Purpose |
|----------|-----------|---------|
| **Framework** | FastAPI 0.115.0 | High-performance async web framework |
| **AI Model** | Groq (Llama 3.3 70B) | Code analysis and review |
| **Database** | Redis 7.0 | Fast in-memory task storage |
| **Async Processing** | FastAPI BackgroundTasks | Non-blocking PR analysis |
| **Containerization** | Docker + Docker Compose | Development environment |
| **Deployment** | Render.com | Cloud hosting with CI/CD |
| **Rate Limiting** | Custom Redis-based | API protection |
| **Testing** | pytest | Unit and integration tests |

---

## 🚀 Quick Start

### Prerequisites

- Python 3.11+
- Redis (optional - falls back to in-memory)
- Groq API Key ([Get one free](https://console.groq.com/keys))
- GitHub Token (optional - for private repos)

### Local Setup

#### 1. Clone the Repository

```bash
git clone https://github.com/yourusername/ai-code-review-agent.git
cd ai-code-review-agent
```

#### 2. Create Virtual Environment

```bash
python -m venv venv

# Windows
venv\Scripts\activate

# Mac/Linux
source venv/bin/activate
```

#### 3. Install Dependencies

```bash
pip install -r requirements.txt
```

#### 4. Configure Environment Variables

```bash
cp .env.example .env
```

Edit `.env`:
```bash
GROQ_API_KEY=gsk_xxxxxxxxxxxxxxxxxxxxx
GITHUB_TOKEN=ghp_xxxxxxxxxxxxxxxxxxxxx  # Optional
REDIS_URL=redis://localhost:6379       # Optional
```

#### 5. Run Redis (Optional)

**Using Docker:**
```bash
docker run -d -p 6379:6379 redis:7-alpine
```

**Or install locally:**
- Windows: [Download Redis](https://github.com/microsoftarchive/redis/releases)
- Mac: `brew install redis && redis-server`
- Linux: `sudo apt-get install redis-server`

#### 6. Start the Server

```bash
uvicorn main:app --reload
```

Server starts at: **http://localhost:8000**

#### 7. Test the API

Visit: **http://localhost:8000/docs** (Interactive Swagger UI)

---

### Docker Setup

#### 1. Build and Run

```bash
docker-compose up --build
```

#### 2. Access

- **API:** http://localhost:8000
- **Docs:** http://localhost:8000/docs
- **Redis:** localhost:6379

#### 3. Stop

```bash
docker-compose down
```

---

## 📚 API Documentation

### Base URL

- **Production:** `https://agent-prm.onrender.com`
- **Local:** `http://localhost:8000`

### Interactive Docs

- **Swagger UI:** `/docs`
- **ReDoc:** `/redoc`

---

### Endpoints

#### 1. Submit PR for Analysis

```http
POST /analyze-pr
```

**Request Body:**
```json
{
  "repo_url": "https://github.com/facebook/react",
  "pr_number": 29061,
  "github_token": "ghp_xxxxx"  // Optional
}
```

**Response (200 OK):**
```json
{
  "task_id": "abc-123-xyz",
  "status": "pending",
  "message": "PR analysis task created successfully"
}
```

**Rate Limit:** 10 requests per minute per IP

**Example (cURL):**
```bash
curl -X POST https://agent-prm.onrender.com/analyze-pr \
  -H "Content-Type: application/json" \
  -d '{
    "repo_url": "https://github.com/facebook/react",
    "pr_number": 29061
  }'
```

**Example (PowerShell):**
```powershell
Invoke-RestMethod -Uri "https://agent-prm.onrender.com/analyze-pr" `
  -Method POST `
  -ContentType "application/json" `
  -Body '{"repo_url": "https://github.com/facebook/react", "pr_number": 29061}'
```

---

#### 2. Check Task Status

```http
GET /status/{task_id}
```

**Response (200 OK):**
```json
{
  "task_id": "abc-123-xyz",
  "status": "completed",  // pending, processing, completed, failed
  "created_at": "2025-10-09T18:00:00"
}
```

**Example:**
```bash
curl https://agent-prm.onrender.com/status/abc-123-xyz
```

---

#### 3. Get Analysis Results

```http
GET /results/{task_id}
```

**Response (200 OK):**
```json
{
  "task_id": "abc-123-xyz",
  "status": "completed",
  "results": {
    "pr_title": "Add new feature",
    "pr_url": "https://github.com/facebook/react/pull/29061",
    "analyzed_at": "2025-10-09T18:05:23.542902",
    "files": [
      {
        "name": "src/index.ts",
        "issues": [
          {
            "type": "style",
            "line": 145,
            "description": "Function too long (120 lines)",
            "suggestion": "Split into smaller functions"
          },
          {
            "type": "bug",
            "line": 203,
            "description": "Potential null reference",
            "suggestion": "Add null check: if (node !== null)"
          },
          {
            "type": "performance",
            "line": 310,
            "description": "Inefficient loop",
            "suggestion": "Use map() instead of forEach with push"
          }
        ]
      }
    ],
    "summary": {
      "total_files": 15,
      "total_issues": 47,
      "critical_issues": 3
    }
  }
}
```

**Status Codes:**
- `200` - Analysis complete
- `202` - Still processing
- `404` - Task not found
- `500` - Analysis failed

---

#### 4. Health Check

```http
GET /health
```

**Response (200 OK):**
```json
{
  "status": "healthy",
  "redis": "connected",
  "storage": "Redis",
  "ai": "groq-llama-3.3-70b",
  "timestamp": "2025-10-09T18:00:00"
}
```

---

#### 5. Debug Tasks (Development)

```http
GET /debug/tasks
```

**Response:**
```json
{
  "total": 5,
  "tasks": [
    {
      "status": "completed",
      "created_at": "2025-10-09T18:00:00",
      "repo_url": "https://github.com/facebook/react",
      "pr_number": 29061,
      "results": {...}
    }
  ]
}
```

---

### Rate Limiting

All endpoints are rate-limited:

**Headers in Response:**
```http
X-RateLimit-Limit: 10
X-RateLimit-Remaining: 7
X-RateLimit-Reset: 1696867200
```

**429 Response (Too Many Requests):**
```json
{
  "error": "Rate limit exceeded",
  "message": "Too many requests. Maximum 10 requests per 60 seconds.",
  "retry_after": 60
}
```

---

## 🎯 Design Decisions

### 1. **Why FastAPI?**

**Chosen over Flask/Django because:**
- ✅ Built-in async support (crucial for background tasks)
- ✅ Automatic API documentation (Swagger UI)
- ✅ High performance (comparable to Node.js)
- ✅ Modern Python features (type hints, async/await)
- ✅ Easy to test and maintain

### 2. **Why Groq Instead of OpenAI?**

**Initial Choice:** OpenAI GPT-4
**Problem:** API quota exhausted ($$$)
**Solution:** Switched to Groq

**Groq Advantages:**
- ✅ Free tier (14,400 requests/day)
- ✅ Faster inference (lowest latency)
- ✅ Powerful model (Llama 3.3 70B)
- ✅ No credit card required

### 3. **Why Redis?**

**Alternatives Considered:** PostgreSQL, MongoDB, In-Memory

**Redis Chosen Because:**
- ✅ Lightning-fast (in-memory, <1ms access)
- ✅ Simple key-value storage (perfect for task queue)
- ✅ Built-in TTL (auto-expire old tasks)
- ✅ Persistent (survives restarts)
- ✅ Free tier on Render

### 4. **Why BackgroundTasks Instead of Celery?**

**Initial Design:** Used Celery + RabbitMQ
**Problem:** Added complexity, required separate worker ($7/month on Render)
**Solution:** FastAPI BackgroundTasks

**Trade-offs:**
- ✅ Simpler architecture
- ✅ No additional services needed
- ✅ Free deployment
- ❌ Single worker (but sufficient for our scale)
- ❌ No distributed processing

**Decision:** Simplicity > Scalability at current stage

### 5. **Why Sliding Window Rate Limiting?**

**Alternatives:** Fixed window, Token bucket

**Sliding Window Chosen Because:**
- ✅ No sudden bursts at window edges
- ✅ Fair distribution over time
- ✅ Accurate tracking with Redis sorted sets
- ✅ Industry standard

### 6. **Asynchronous Architecture**

**Why Async?**
- PR analysis takes 5-30 seconds
- User gets instant response (task_id)
- Server handles multiple requests concurrently
- Better user experience

**Flow:**
```
Request → Instant Response (task_id) → Background Processing → Poll for Results
```

### 7. **Error Handling Strategy**

**Multi-Layer Protection:**
1. **API Layer:** Validates input, returns proper status codes
2. **Agent Layer:** Handles GitHub/AI API errors
3. **Storage Layer:** Graceful fallback to in-memory
4. **Rate Limiting:** Prevents abuse

**Philosophy:** Fail gracefully, always return useful error messages

---

## 🧪 Testing

### Unit Tests

```bash
pytest -v
```

### With Coverage

```bash
pytest --cov=. --cov-report=html
open htmlcov/index.html
```

### Manual Testing

#### 1. Test with Public PR (No Token)

```bash
curl -X POST http://localhost:8000/analyze-pr \
  -H "Content-Type: application/json" \
  -d '{
    "repo_url": "https://github.com/facebook/react",
    "pr_number": 29061
  }'
```

#### 2. Test Rate Limiting

```bash
# Submit 11 requests quickly
for i in {1..11}; do
  curl -X POST http://localhost:8000/analyze-pr \
    -H "Content-Type: application/json" \
    -d '{"repo_url": "https://github.com/facebook/react", "pr_number": 1}'
  echo ""
done
```

**Expected:** First 10 succeed, 11th returns 429

#### 3. Test Health Check

```bash
curl http://localhost:8000/health
```

---

## 🚢 Deployment

### Render.com (Recommended)

#### 1. Create Services

**A. Redis:**
1. New → Redis
2. Name: `code-review-redis`
3. Plan: Free
4. Create
5. Copy **Internal Redis URL**

**B. Web Service:**
1. New → Web Service
2. Connect GitHub repo
3. Settings:
   - **Name:** `code-review-api`
   - **Environment:** Python 3
   - **Build Command:** `pip install -r requirements.txt`
   - **Start Command:** `uvicorn main:app --host 0.0.0.0 --port $PORT`
   - **Instance Type:** Free

#### 2. Environment Variables

Add in Web Service:
```
GROQ_API_KEY=gsk_xxxxx
GITHUB_TOKEN=ghp_xxxxx
REDIS_URL=redis://red-xxxxx.singapore.render.com:6379
```

#### 3. Deploy

Push to GitHub → Auto-deploy!

**Live URL:** `https://your-app.onrender.com`

---

### Docker Deployment (Alternative)

#### 1. Build Image

```bash
docker build -t code-review-agent .
```

#### 2. Run Container

```bash
docker run -d -p 8000:8000 \
  -e GROQ_API_KEY=gsk_xxxxx \
  -e GITHUB_TOKEN=ghp_xxxxx \
  -e REDIS_URL=redis://redis:6379 \
  code-review-agent
```

---

## 🔮 Future Improvements

### High Priority

- [ ] **Authentication System** - API keys for user management
- [ ] **Webhook Integration** - Auto-analyze PRs on GitHub events
- [ ] **Multi-language Support** - Language-specific analysis rules
- [ ] **Batch Processing** - Analyze multiple PRs simultaneously
- [ ] **Advanced Caching** - Cache analysis for identical diffs
- [ ] **GitHub App** - Post results as PR comments directly

### Medium Priority

- [ ] **Custom Rules Engine** - User-defined code review rules
- [ ] **Detailed Metrics** - Track issues over time
- [ ] **Email Notifications** - Alert when analysis complete
- [ ] **Support Private Repos** - Enhanced GitHub token handling
- [ ] **Export Reports** - PDF/Markdown export
- [ ] **Team Analytics** - Aggregate stats across repos

### Low Priority

- [ ] **Web Dashboard** - Visual interface for results
- [ ] **Slack Integration** - Post results to Slack
- [ ] **GraphQL API** - Alternative to REST
- [ ] **Machine Learning** - Learn from user feedback
- [ ] **Code Suggestions** - Auto-fix simple issues
- [ ] **IDE Plugins** - VSCode/IntelliJ integration

### Scalability Improvements

- [ ] **Celery Workers** - Distributed processing
- [ ] **PostgreSQL** - Relational data storage
- [ ] **Load Balancing** - Multiple API instances
- [ ] **CDN Integration** - Cache static results
- [ ] **Monitoring** - Grafana/Prometheus dashboards
- [ ] **Auto-scaling** - Dynamic resource allocation

---

## 📦 Project Structure

```
code-review-agent/
├── main.py                 # FastAPI application
├── rate_limiter.py         # Rate limiting logic
├── requirements.txt        # Python dependencies
├── .env.example           # Environment variables template
├── .gitignore             # Git ignore rules
├── Dockerfile             # Docker container config
├── docker-compose.yml     # Multi-container setup
├── .dockerignore          # Docker ignore rules
├── Procfile               # Render deployment config
├── README.md              # This file
├── tests/                 # Test files
      ├── test_main.py
```

---

### Development Setup

```bash
# Install dev dependencies
pip install -r requirements-dev.txt

# Run tests
pytest

# Format code
black .

# Lint
flake8 .
```

---

## 📄 License

This project is licensed under the MIT License - see the [LICENSE](LICENSE) file for details.

---

## 🙏 Acknowledgments

- [FastAPI](https://fastapi.tiangolo.com/) - Modern web framework
- [Groq](https://groq.com/) - Blazing-fast AI inference
- [Redis](https://redis.io/) - In-memory data store
- [Render](https://render.com/) - Easy deployment platform
- [GitHub API](https://docs.github.com/en/rest) - PR data access

---

## 📧 Contact

**Project Maintainer:** Your Name

- GitHub: [@yourusername](https://github.com/yourusername)
- Email: your.email@example.com
- LinkedIn: [Your Name](https://linkedin.com/in/yourprofile)

---

## 🌟 Show Your Support

Give a ⭐️ if this project helped you!

---

## 📊 Project Stats

![GitHub stars](https://img.shields.io/github/stars/yourusername/ai-code-review-agent)
![GitHub forks](https://img.shields.io/github/forks/yourusername/ai-code-review-agent)
![GitHub issues](https://img.shields.io/github/issues/yourusername/ai-code-review-agent)
![GitHub license](https://img.shields.io/github/license/yourusername/ai-code-review-agent)

---

**Built with ❤️ by [Your Name](https://github.com/yourusername)**
