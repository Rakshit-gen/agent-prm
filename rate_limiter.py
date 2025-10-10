from fastapi import HTTPException, Request
from typing import Optional
import redis
import time
import logging

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
            
            if request_count > max_requests:
                return False, request_count
            
            return True, request_count
            
        except Exception as e:
            logger.error(f"Redis rate limit error: {e}")
            return True, 0
    
    def _check_memory(self, key: str, max_requests: int, window_seconds: int) -> tuple[bool, int]:
        current = time.time()
        window_start = current - window_seconds
        
        if key not in self.in_memory_store:
            self.in_memory_store[key] = []
        
        self.in_memory_store[key] = [
            timestamp for timestamp in self.in_memory_store[key]
            if timestamp > window_start
        ]
        
        self.in_memory_store[key].append(current)
        
        request_count = len(self.in_memory_store[key])
        
        if request_count > max_requests:
            return False, request_count
        
        return True, request_count
    
    def get_remaining_requests(self, key: str, max_requests: int, window_seconds: int) -> int:
        _, current_count = self.check_rate_limit(key, max_requests, window_seconds)
        return max(0, max_requests - current_count)


def rate_limit(
    max_requests: int = 10,
    window_seconds: int = 60,
    key_func = None
):
    def decorator(func):
        async def wrapper(request: Request, *args, **kwargs):
            rate_limiter = request.app.state.rate_limiter
            
            if key_func:
                limit_key = key_func(request)
            else:
                limit_key = f"rate_limit:{request.client.host}"
            
            allowed, current_count = rate_limiter.check_rate_limit(
                limit_key,
                max_requests,
                window_seconds
            )
            
            if not allowed:
                raise HTTPException(
                    status_code=429,
                    detail={
                        "error": "Rate limit exceeded",
                        "message": f"Too many requests. Maximum {max_requests} requests per {window_seconds} seconds.",
                        "retry_after": window_seconds
                    },
                    headers={
                        "X-RateLimit-Limit": str(max_requests),
                        "X-RateLimit-Remaining": "0",
                        "X-RateLimit-Reset": str(int(time.time()) + window_seconds),
                        "Retry-After": str(window_seconds)
                    }
                )
            
            remaining = rate_limiter.get_remaining_requests(limit_key, max_requests, window_seconds)
            
            response = await func(request, *args, **kwargs)
            
            if hasattr(response, 'headers'):
                response.headers["X-RateLimit-Limit"] = str(max_requests)
                response.headers["X-RateLimit-Remaining"] = str(remaining - 1)
                response.headers["X-RateLimit-Reset"] = str(int(time.time()) + window_seconds)
            
            return response
        
        return wrapper
    return decorator
