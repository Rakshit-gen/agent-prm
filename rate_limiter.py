from fastapi import HTTPException, Request
from typing import Optional
import time
import redis
import logging
from functools import wraps

logger = logging.getLogger(__name__)

class RateLimiter:
    def __init__(self, redis_client: Optional[redis.Redis] = None):
        self.redis_client = redis_client
        self.in_memory_store = {}
    
    def is_rate_limited(self, identifier: str, max_requests: int, window_seconds: int) -> bool:
        current_time = int(time.time())
        window_start = current_time - window_seconds
        
        if self.redis_client:
            try:
                key = f"rate_limit:{identifier}"
                pipe = self.redis_client.pipeline()
                pipe.zremrangebyscore(key, 0, window_start)
                pipe.zadd(key, {str(current_time): current_time})
                pipe.zcard(key)
                pipe.expire(key, window_seconds)
                results = pipe.execute()
                
                request_count = results[2]
                
                if request_count > max_requests:
                    logger.warning(f"Rate limit exceeded for {identifier}: {request_count}/{max_requests}")
                    return True
                
                return False
            
            except Exception as e:
                logger.error(f"Redis error in rate limiting: {e}")
                return self._in_memory_rate_limit(identifier, max_requests, window_seconds, current_time, window_start)
        else:
            return self._in_memory_rate_limit(identifier, max_requests, window_seconds, current_time, window_start)
    
    def _in_memory_rate_limit(self, identifier: str, max_requests: int, window_seconds: int, current_time: int, window_start: int) -> bool:
        if identifier not in self.in_memory_store:
            self.in_memory_store[identifier] = []
        
        timestamps = self.in_memory_store[identifier]
        timestamps = [ts for ts in timestamps if ts > window_start]
        timestamps.append(current_time)
        self.in_memory_store[identifier] = timestamps
        
        if len(timestamps) > max_requests:
            logger.warning(f"Rate limit exceeded for {identifier}: {len(timestamps)}/{max_requests}")
            return True
        
        return False
    
    def get_client_identifier(self, request: Request) -> str:
        forwarded = request.headers.get("X-Forwarded-For")
        if forwarded:
            return forwarded.split(",")[0].strip()
        
        client_host = request.client.host if request.client else "unknown"
        return client_host

def rate_limit(max_requests: int = 10, window_seconds: int = 60):
    def decorator(func):
        @wraps(func)
        async def wrapper(*args, **kwargs):
            request: Optional[Request] = None
            
            for arg in args:
                if isinstance(arg, Request):
                    request = arg
                    break
            
            if not request:
                request = kwargs.get("request")
            
            if not request:
                return await func(*args, **kwargs)
            
            rate_limiter = request.app.state.rate_limiter
            client_id = rate_limiter.get_client_identifier(request)
            
            if rate_limiter.is_rate_limited(client_id, max_requests, window_seconds):
                raise HTTPException(
                    status_code=429,
                    detail=f"Rate limit exceeded. Maximum {max_requests} requests per {window_seconds} seconds."
                )
            
            return await func(*args, **kwargs)
        
        return wrapper
    return decorator
