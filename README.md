# agent-prm

Point it at a GitHub pull request and four review agents go through the diff: one for security, one for performance, one for architecture, one for code quality. You get back a list of issues per file, each with a line number, a severity and a suggested fix.

It runs as a FastAPI service. You submit a PR, get a task id straight away, and poll (or open a WebSocket) while the agents work.

Live instance: https://agent-prm.onrender.com (API docs at [`/docs`](https://agent-prm.onrender.com/docs)). It is on Render's free tier, so the first request after a quiet spell can take a while to wake up.

## How a review runs

```
POST /analyze-pr
      |
      v
 save task (pending) -> return task_id
      |
      v  (FastAPI background task)
 fetch PR title + changed files and patches from the GitHub API
      |
      v
 AgentOrchestrator
   SecurityAgent      --+
   PerformanceAgent     |  run one after another, 2s apart (Groq rate limits)
   ArchitectureAgent    |  each agent reviews up to 5 files in parallel
   QualityAgent       --+
      |
      v
 merge issues by file, tag each with the agent that found it, count severities
      |
      v
 save task (completed) -> GET /results/{task_id}
```

What each agent does with a file:

- Sends the patch (first 2,000 characters) to Llama 3.3 70B on Groq with a prompt focused on its area, and asks for a JSON array of issues, at most 10.
- The security agent also runs regexes for hardcoded API keys, passwords, tokens, AWS keys and private keys. Those hits do not depend on the model.
- LLM calls retry up to 5 times with exponential backoff when Groq returns a rate limit.

If one agent fails, its error is stored and the others still finish.

## Quickstart

You need Python 3.11+ and a [Groq API key](https://console.groq.com/keys). Redis is optional; without it tasks live in process memory.

```bash
git clone https://github.com/Rakshit-gen/agent-prm.git
cd agent-prm
python -m venv venv && source venv/bin/activate
pip install -r requirements.txt tenacity
cp .env.example .env   # then fill in GROQ_API_KEY
uvicorn main:app --reload
```

`tenacity` is used by the agents but is missing from `requirements.txt`, so install it by hand for now.

Or with Docker (starts Redis too):

```bash
GROQ_API_KEY=gsk_... docker-compose up --build
```

Then review a PR:

```bash
curl -X POST http://localhost:8000/analyze-pr \
  -H "Content-Type: application/json" \
  -d '{"repo_url": "https://github.com/facebook/react", "pr_number": 29061}'
```

## Configuration

| Variable | Required | What it does |
|---|---|---|
| `GROQ_API_KEY` | yes | Groq key for the review model |
| `GROQ_MODEL` | no | Model name, default `llama-3.3-70b-versatile` |
| `GITHUB_TOKEN` | no | Used when the request does not pass its own token. Needed for private repos and to avoid GitHub's low anonymous rate limit |
| `REDIS_URL` | no | Task storage and rate limiting. Falls back to memory if unset or unreachable |
| `PORT` | no | Only used when running `python main.py` |

## API

| Method | Path | What it returns |
|---|---|---|
| `POST` | `/analyze-pr` | `{task_id, status, message}`. Body: `repo_url`, `pr_number`, optional `github_token` |
| `GET` | `/status/{task_id}` | Status (`pending`, `processing`, `completed`, `failed`) plus per-agent progress events |
| `GET` | `/results/{task_id}` | Full result when done. `202` while still running, `500` if it failed |
| `WS` | `/ws/{task_id}` | Pushes status and progress every 2 seconds until the task finishes |
| `GET` | `/` | Service info and the list of agents |

`POST /analyze-pr` is limited to 10 requests per minute per client IP, using a sliding window in a Redis sorted set (in memory without Redis). Going over returns `429`.

A trimmed result looks like this:

```json
{
  "task_id": "…",
  "status": "completed",
  "results": {
    "pr_title": "…",
    "pr_url": "https://github.com/owner/repo/pull/123",
    "files": [
      {
        "name": "src/db.py",
        "issues": [
          {
            "file": "src/db.py",
            "line": 42,
            "type": "security",
            "severity": "critical",
            "description": "SQL built with string formatting",
            "suggestion": "Use a parameterised query",
            "detected_by": "security"
          }
        ],
        "agent_breakdown": {"security": 1}
      }
    ],
    "summary": {
      "total_files": 1, "total_issues": 1, "critical_issues": 1,
      "high_priority_issues": 0, "total_agents": 4, "agents_completed": 4
    }
  }
}
```

Tasks are kept in Redis for 24 hours.

## Layout

```
main.py                    FastAPI app, task storage, GitHub fetch, endpoints
rate_limiter.py            sliding-window limiter (Redis or in-memory)
agents/base_agent.py       Groq client, retry logic, JSON parsing
agents/orchestrator.py     runs the four agents and merges their issues
agents/*_agent.py          one file per review area
tests/                     pytest tests for the API and the rate limiter
```

Run the tests with `pytest -v`.

## Design choices

- **Background tasks, not Celery.** An earlier version used Celery and RabbitMQ. That needed a separate paid worker on Render, so it moved to FastAPI `BackgroundTasks`. The cost: work runs inside the web process, so a restart drops tasks in flight and there is no horizontal scaling.
- **Groq, not OpenAI.** Free tier and low latency were the reasons. The price is tight rate limits, which is why agents run in sequence with a pause between them.
- **One LLM call per file per agent.** Each agent builds a LangChain ReAct executor, but `analyze()` calls the model directly instead of going through the tool loop. That keeps a review to a predictable number of calls.

## Limits

- Only the diff is reviewed, not the full file, and only its first 2,000 characters. Large changes get a partial review.
- Line numbers come from the model and can be off.
- Severity totals are added up from whatever keys each agent returns, so they are a rough count.
- Progress is also kept in a process-local dict, so with more than one worker, `/status` can look different depending on which worker answers.
- There is no auth. Anyone who can reach the service can spend your Groq quota, so keep it private or put it behind a gateway.
