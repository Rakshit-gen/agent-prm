from fastapi import HTTPException, Request
from typing import Optional
from functools import wraps
import redis
import time
import logging
import asyncio

logger = logging.getLogger(__name__)

class RateLimiter:
    def __init__(self, redis_client: Optional[redis.Redis] = None):
        self.redis_client = redis_client
        self.in_memory_store = {}

    def check_rate_limit(
        self,
        key: str,
        max_requests: int,
        window_seconds: int
    ) -> tuple[bool, int]:
        if self.redis_client:
            return self._check_redis(key, max_requests, window_seconds)
        else:
            return self._check_memory(key, max_requests, window_seconds)

    def _check_redis(self, key: str, max_requests: int, window_seconds: int) -> tuple[bool, int]:
        try:
            current = int(time.time())
            window_start = current - window_seconds

            pipe = self.redis_client.pipeline()
            pipe.zremrangebyscore(key, 0, window_start)
            pipe.zadd(key, {str(current): current})
            pipe.zcard(key)
            pipe.expire(key, window_seconds)
            results = pipe.execute()

            request_count = results[2]
            return (request_count <= max_requests, request_count)
        except Exception as e:
            logger.error(f"Redis rate limit error: {e}")
            return True, 0

    def _check_memory(self, key: str, max_requests: int, window_seconds: int) -> tuple[bool, int]:
        current = time.time()
        window_start = current - window_seconds

        if key not in self.in_memory_store:
            self.in_memory_store[key] = []

        # Remove old timestamps
        self.in_memory_store[key] = [
            t for t in self.in_memory_store[key] if t > window_start
        ]
        self.in_memory_store[key].append(current)

        request_count = len(self.in_memory_store[key])
        return (request_count <= max_requests, request_count)

    def get_remaining_requests(self, key: str, max_requests: int, window_seconds: int) -> int:
        _, current_count = self.check_rate_limit(key, max_requests, window_seconds)
        return max(0, max_requests - current_count)


# ✅ FIXED decorator preserving FastAPI function signature
def rate_limit(
    max_requests: int = 10,
    window_seconds: int = 60,
    key_func=None
):
    def decorator(func):
        @wraps(func)
        async def wrapper(*args, **kwargs):
            # Extract FastAPI request object
            request: Request = kwargs.get("request")
            if not request:
                for arg in args:
                    if isinstance(arg, Request):
                        request = arg
                        break
            if not request:
                raise HTTPException(status_code=500, detail="Request object not found")

            rate_limiter = request.app.state.rate_limiter
            limit_key = key_func(request) if key_func else f"rate_limit:{request.client.host}"

            allowed, count = rate_limiter.check_rate_limit(limit_key, max_requests, window_seconds)
            if not allowed:
                raise HTTPException(
                    status_code=429,
                    detail={
                        "error": "Rate limit exceeded",
                        "message": f"Too many requests. Max {max_requests} per {window_seconds}s.",
                        "retry_after": window_seconds,
                    },
                    headers={
                        "X-RateLimit-Limit": str(max_requests),
                        "X-RateLimit-Remaining": "0",
                        "X-RateLimit-Reset": str(int(time.time()) + window_seconds),
                        "Retry-After": str(window_seconds),
                    },
                )

            remaining = rate_limiter.get_remaining_requests(limit_key, max_requests, window_seconds)

            # Call the actual route handler
            if asyncio.iscoroutinefunction(func):
                response = await func(*args, **kwargs)
            else:
                response = func(*args, **kwargs)

            # Add rate-limit headers to response
            if hasattr(response, "headers"):
                response.headers["X-RateLimit-Limit"] = str(max_requests)
                response.headers["X-RateLimit-Remaining"] = str(remaining - 1)
                response.headers["X-RateLimit-Reset"] = str(int(time.time()) + window_seconds)

            return response

        return wrapper
    return decorator
