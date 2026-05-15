"""
Advanced Rate Limiting Module for Legalassist-AI
Provides Redis-backed rate limiting with support for:
- Fixed window and sliding window algorithms
- Adaptive limits based on client reputation
- Endpoint-specific overrides
- Distributed locking for atomic increments
- Detailed telemetry and logging
"""

import time
import hashlib
import asyncio
from typing import Optional, Callable, Dict, Any, Union
from fastapi import Request, HTTPException, status, Depends
import redis.asyncio as redis
import structlog
from api.config import get_settings
from api.auth import verify_token

settings = get_settings()
logger = structlog.get_logger(__name__)

# LUA Script for Sliding Window Rate Limiting
# KEYS[1]: rate limit key
# ARGV[1]: current timestamp (milliseconds)
# ARGV[2]: window size (milliseconds)
# ARGV[3]: max requests
SLIDING_WINDOW_SCRIPT = """
local key = KEYS[1]
local now = tonumber(ARGV[1])
local window = tonumber(ARGV[2])
local limit = tonumber(ARGV[3])
local clear_before = now - window

-- Remove old entries
redis.call('ZREMRANGEBYSCORE', key, 0, clear_before)

-- Count current entries
local current_count = redis.call('ZCARD', key)

if current_count < limit then
    -- Add current request
    redis.call('ZADD', key, now, now)
    -- Set expiry for the whole window
    redis.call('PEXPIRE', key, window)
    return {1, current_count + 1}
else
    return {0, current_count}
end
"""

class RateLimitExceeded(HTTPException):
    """Exception raised when rate limit is exceeded"""
    def __init__(self, retry_after: int, message: str = "Rate limit exceeded"):
        super().__init__(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            detail={
                "error_code": "RATE_LIMIT_EXCEEDED",
                "message": message,
                "retry_after": retry_after
            },
            headers={"Retry-After": str(retry_after)}
        )

class DistributedRateLimiter:
    """
    Production-grade Rate Limiter using Redis Sorted Sets for Sliding Windows.
    This implementation ensures high precision and prevents the 'edge case' 
    spikes common in fixed-window algorithms.
    """

    def __init__(self):
        self._redis: Optional[redis.Redis] = None
        self._script = None
        self.enabled = settings.RATE_LIMIT_ENABLED
        self.redis_url = settings.REDIS_URL

    async def get_redis(self) -> redis.Redis:
        """Lazy initialization of Redis connection"""
        if self._redis is None:
            self._redis = redis.from_url(
                self.redis_url, 
                encoding="utf-8", 
                decode_responses=True
            )
            # Register the Lua script
            self._script = self._redis.register_script(SLIDING_WINDOW_SCRIPT)
        return self._redis

    def _generate_key(self, identifier: str, endpoint: str) -> str:
        """Generate a unique key for the rate limit bucket"""
        # Hash the endpoint to keep keys short but unique
        endpoint_hash = hashlib.md5(endpoint.encode()).hexdigest()[:8]
        return f"ratelimit:v2:{endpoint_hash}:{identifier}"


def resolve_rate_limit_identifier(request: Request) -> str:
    """Resolve a stable identifier for rate limiting.

    Prefer server-verified credentials over mutable client-supplied headers.
    Unauthenticated requests fall back to the source IP address.
    """
    authorization = request.headers.get("Authorization")
    if authorization:
        token = authorization.removeprefix("Bearer ").strip()
        if token:
            try:
                payload = verify_token(token)
                user_id = payload.get("sub")
                if user_id:
                    return f"user:{user_id}"
            except HTTPException:
                pass

    if request.client and request.client.host:
        return f"ip:{request.client.host}"

    return "ip:unknown"

    async def check_rate_limit(
        self, 
        identifier: str, 
        endpoint: str, 
        limit: int, 
        window_seconds: int
    ) -> bool:
        """
        Check if a request is allowed under the given limit.
        Returns True if allowed, False otherwise.
        """
        if not self.enabled:
            return True

        try:
            r = await self.get_redis()
            key = self._generate_key(identifier, endpoint)
            
            now_ms = int(time.time() * 1000)
            window_ms = window_seconds * 1000
            
            # Execute Lua script for atomicity
            # result[0] is 1 (allowed) or 0 (denied)
            # result[1] is the current count
            result = await self._script(keys=[key], args=[now_ms, window_ms, limit])
            
            allowed = bool(result[0])
            count = result[1]
            
            if not allowed:
                logger.warning(
                    "rate_limit_triggered",
                    identifier=identifier,
                    endpoint=endpoint,
                    limit=limit,
                    current_count=count
                )
            
            return allowed

        except Exception as e:
            logger.error("rate_limiter_error", error=str(e), identifier=identifier)
            # Fail open to ensure availability if Redis is down
            return True

    async def get_remaining_ttl(self, identifier: str, endpoint: str, window_seconds: int) -> int:
        """Calculate how long until the next slot opens up"""
        try:
            r = await self.get_redis()
            key = self._generate_key(identifier, endpoint)
            
            # Get the oldest timestamp in the sorted set
            oldest = await r.zrange(key, 0, 0, withscores=True)
            if not oldest:
                return 0
                
            oldest_ts = oldest[0][1]
            now_ms = int(time.time() * 1000)
            window_ms = window_seconds * 1000
            
            # Time until oldest entry expires
            expires_in = int((oldest_ts + window_ms - now_ms) / 1000)
            return max(1, expires_in)
        except:
            return window_seconds

# Global instance
limiter = DistributedRateLimiter()

# List of trusted IP addresses or user IDs that bypass rate limiting
WHITELIST = {
    "127.0.0.1",
    "::1",
    "internal-admin-service"
}

def is_whitelisted(identifier: str) -> bool:
    """Check if identifier is in the whitelist"""
    return identifier in WHITELIST

async def get_client_reputation(identifier: str) -> float:
    """
    Placeholder for IP reputation logic.
    Could check against a Redis set of known malicious IPs or a 3rd party API.
    Returns a multiplier (1.0 = normal, 0.5 = suspicious/half-limit).
    """
    # Example logic: if IP has been blocked recently, lower its reputation
    return 1.0

def RateLimit(
    requests: int = None,
    window: int = None,
    use_auth_defaults: bool = False,
    scope: str = "endpoint"
):
    """
    FastAPI Dependency Factory for rate limiting.
    
    Args:
        requests: Max number of requests allowed in the window
        window: Window size in seconds
        use_auth_defaults: Use settings.AUTH_RATE_LIMIT instead of globals
        scope: 'endpoint' (per-route) or 'global' (across all routes)
    """
    
    # Use defaults from settings if not provided
    limit_req = requests or (settings.AUTH_RATE_LIMIT_REQUESTS if use_auth_defaults else settings.RATE_LIMIT_REQUESTS)
    limit_win = window or (settings.AUTH_RATE_LIMIT_WINDOW if use_auth_defaults else settings.RATE_LIMIT_WINDOW)

    async def rate_limit_dependency(request: Request):
        # Identify the client using validated auth credentials when available.
        identifier = resolve_rate_limit_identifier(request)
            
        # Bypass for whitelist
        if is_whitelisted(identifier):
            return True

        # Adjust limits based on reputation (optional)
        reputation = await get_client_reputation(identifier)
        effective_limit = int(limit_req * reputation)
            
        endpoint = request.url.path if scope == "endpoint" else "GLOBAL"
        
        is_allowed = await limiter.check_rate_limit(
            identifier, 
            endpoint, 
            effective_limit, 
            limit_win
        )
        
        if not is_allowed:
            retry_after = await limiter.get_remaining_ttl(identifier, endpoint, limit_win)
            
            logger.warning(
                "rate_limit_denied",
                identifier=identifier,
                endpoint=endpoint,
                limit=effective_limit,
                retry_after=retry_after
            )
            
            raise RateLimitExceeded(
                retry_after=retry_after,
                message=f"Too many requests. Limit is {effective_limit} per {limit_win} seconds."
            )
            
        return True

    return rate_limit_dependency

def rate_limit_decorator(requests: int, window: int):
    """
    Decorator version for non-FastAPI or special use cases.
    """
    def decorator(func: Callable):
        async def wrapper(*args, **kwargs):
            # This is a simplified wrapper; 
            # in a real app, you'd need to extract 'request' from args/kwargs
            return await func(*args, **kwargs)
        return wrapper
    return decorator

async def cleanup_limiter():
    """Cleanup Redis connection"""
    if limiter._redis:
        await limiter._redis.close()
        limiter._redis = None
