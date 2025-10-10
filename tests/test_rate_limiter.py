import pytest
import time
from unittest.mock import MagicMock, patch
from rate_limiter import RateLimiter

@pytest.fixture
def mock_redis():
    mock = MagicMock()
    mock.pipeline.return_value = mock
    mock.zremrangebyscore.return_value = mock
    mock.zadd.return_value = mock
    mock.zcard.return_value = mock
    mock.expire.return_value = mock
    mock.execute.return_value = [None, None, 5, None]
    return mock

@pytest.fixture
def rate_limiter_redis(mock_redis):
    return RateLimiter(redis_client=mock_redis)

@pytest.fixture
def rate_limiter_memory():
    return RateLimiter(redis_client=None)

def test_redis_rate_limiter_allows_within_limit(rate_limiter_redis, mock_redis):
    mock_redis.execute.return_value = [None, None, 5, None]
    
    allowed, count = rate_limiter_redis.check_rate_limit(
        key="test_user",
        max_requests=10,
        window_seconds=60
    )
    
    assert allowed is True
    assert count == 5

def test_redis_rate_limiter_blocks_over_limit(rate_limiter_redis, mock_redis):
    mock_redis.execute.return_value = [None, None, 11, None]
    
    allowed, count = rate_limiter_redis.check_rate_limit(
        key="test_user",
        max_requests=10,
        window_seconds=60
    )
    
    assert allowed is False
    assert count == 11

def test_redis_rate_limiter_exact_limit(rate_limiter_redis, mock_redis):
    mock_redis.execute.return_value = [None, None, 10, None]
    
    allowed, count = rate_limiter_redis.check_rate_limit(
        key="test_user",
        max_requests=10,
        window_seconds=60
    )
    
    assert allowed is True
    assert count == 10

def test_memory_rate_limiter_allows_within_limit(rate_limiter_memory):
    for i in range(5):
        allowed, count = rate_limiter_memory.check_rate_limit(
            key="test_user",
            max_requests=10,
            window_seconds=60
        )
        assert allowed is True
        assert count == i + 1

def test_memory_rate_limiter_blocks_over_limit(rate_limiter_memory):
    for i in range(10):
        rate_limiter_memory.check_rate_limit(
            key="test_user",
            max_requests=10,
            window_seconds=60
        )
    
    allowed, count = rate_limiter_memory.check_rate_limit(
        key="test_user",
        max_requests=10,
        window_seconds=60
    )
    
    assert allowed is False
    assert count == 11

def test_memory_rate_limiter_window_expiry(rate_limiter_memory):
    allowed, count = rate_limiter_memory.check_rate_limit(
        key="test_user",
        max_requests=10,
        window_seconds=1
    )
    assert allowed is True
    
    time.sleep(1.1)
    
    allowed, count = rate_limiter_memory.check_rate_limit(
        key="test_user",
        max_requests=10,
        window_seconds=1
    )
    
    assert count == 1

def test_memory_rate_limiter_multiple_users(rate_limiter_memory):
    for i in range(5):
        rate_limiter_memory.check_rate_limit(
            key="user1",
            max_requests=10,
            window_seconds=60
        )
    
    for i in range(3):
        rate_limiter_memory.check_rate_limit(
            key="user2",
            max_requests=10,
            window_seconds=60
        )
    
    allowed1, count1 = rate_limiter_memory.check_rate_limit(
        key="user1",
        max_requests=10,
        window_seconds=60
    )
    
    allowed2, count2 = rate_limiter_memory.check_rate_limit(
        key="user2",
        max_requests=10,
        window_seconds=60
    )
    
    assert count1 == 6
    assert count2 == 4

def test_get_remaining_requests(rate_limiter_memory):
    for i in range(3):
        rate_limiter_memory.check_rate_limit(
            key="test_user",
            max_requests=10,
            window_seconds=60
        )
    
    remaining = rate_limiter_memory.get_remaining_requests(
        key="test_user",
        max_requests=10,
        window_seconds=60
    )
    
    assert remaining == 6

def test_get_remaining_requests_zero(rate_limiter_memory):
    for i in range(12):
        rate_limiter_memory.check_rate_limit(
            key="test_user",
            max_requests=10,
            window_seconds=60
        )
    
    remaining = rate_limiter_memory.get_remaining_requests(
        key="test_user",
        max_requests=10,
        window_seconds=60
    )
    
    assert remaining == 0

def test_redis_error_fallback(rate_limiter_redis, mock_redis):
    mock_redis.execute.side_effect = Exception("Redis error")
    
    allowed, count = rate_limiter_redis.check_rate_limit(
        key="test_user",
        max_requests=10,
        window_seconds=60
    )
    
    assert allowed is True
    assert count == 0
