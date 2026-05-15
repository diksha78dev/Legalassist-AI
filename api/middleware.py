"""
API Rate Limiting and Middleware
"""
import time
from typing import Callable
from fastapi import Request, HTTPException, status
from fastapi.responses import JSONResponse
import redis
import structlog

from observability.instrumentation import (
    bind_request_context,
    clear_request_context,
    capture_exception,
    generate_correlation_id,
    observe_request,
    record_api_error,
    traced_operation,
)

logger = structlog.get_logger(__name__)


class RateLimiter:
    """Token bucket rate limiter using Redis"""

    # Lua script: atomically increment the counter and set TTL on first write.
    # Redis executes Lua scripts as a single atomic operation, so there is no
    # window between INCR and EXPIRE where the key can be left without a TTL.
    _INCR_EXPIRE_SCRIPT = """
local current = redis.call('INCR', KEYS[1])
if current == 1 then
    redis.call('EXPIRE', KEYS[1], ARGV[1])
end
return current
"""

    def __init__(self, redis_url: str = "redis://localhost:6379/0"):
        self.redis = redis.from_url(redis_url, decode_responses=True)
        self.requests = 100  # requests
        self.window = 60  # seconds
        self._script = self.redis.register_script(self._INCR_EXPIRE_SCRIPT)

    def is_allowed(self, key: str) -> bool:
        """Check if request is allowed"""
        try:
            current = int(self._script(keys=[key], args=[self.window]))
            return current <= self.requests
        except Exception as e:
            logger.error("Rate limiter error", error=str(e))
            # Fail open - allow request if Redis unavailable
            return True
    
    def get_retry_after(self, key: str) -> int:
        """Get seconds until next request allowed"""
        try:
            ttl = self.redis.ttl(key)
            return ttl if ttl > 0 else self.window
        except:
            return self.window


async def rate_limit_middleware(request: Request, call_next: Callable):
    """Rate limiting middleware"""
    
    # Skip rate limiting for health checks
    if request.url.path in ["/api/v1/health", "/api/v1/health/ready", "/api/v1/health/live"]:
        return await call_next(request)
    
    # Get client identifier
    client_ip = request.client.host if request.client else "unknown"
    user_id = request.headers.get("X-User-Id", client_ip)
    
    rate_limiter = RateLimiter()
    rate_limit_key = f"ratelimit:{user_id}:{int(time.time() // 60)}"
    
    if not rate_limiter.is_allowed(rate_limit_key):
        logger.warning(
            "Rate limit exceeded",
            user_id=user_id,
            ip=client_ip
        )
        return JSONResponse(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            content={
                "error_code": "RATE_LIMIT_EXCEEDED",
                "message": f"Rate limit exceeded. Max {rate_limiter.requests} requests per {rate_limiter.window} seconds",
                "retry_after": rate_limiter.get_retry_after(rate_limit_key)
            },
            headers={"Retry-After": str(rate_limiter.get_retry_after(rate_limit_key))}
        )
    
    response = await call_next(request)
    response.headers["X-RateLimit-Limit"] = str(rate_limiter.requests)
    try:
        current_count = int(rate_limiter.redis.get(rate_limit_key) or 0)
    except Exception:
        current_count = 0
    response.headers["X-RateLimit-Remaining"] = str(max(0, rate_limiter.requests - current_count))
    
    return response


async def add_correlation_id_middleware(request: Request, call_next: Callable):
    """Add correlation ID to all requests"""
    
    correlation_id = request.headers.get("X-Correlation-Id")
    if not correlation_id:
        correlation_id = generate_correlation_id()
    
    request.state.correlation_id = correlation_id
    request.state.request_id = correlation_id
    request.state.user_id = request.headers.get("X-User-Id") or request.headers.get("Authorization")
    
    try:
        response = await call_next(request)
        response.headers["X-Correlation-Id"] = correlation_id
        response.headers["X-Request-Id"] = correlation_id
        return response
    finally:
        pass


async def error_handling_middleware(request: Request, call_next: Callable):
    """Global error handling middleware"""
    
    try:
        response = await call_next(request)
        return response
    except HTTPException:
        raise
    except Exception as e:
        logger.error(
            "Unhandled error",
            path=request.url.path,
            method=request.method,
            error=str(e)
        )
        record_api_error(request.url.path, e)
        capture_exception(e, path=request.url.path, method=request.method)
        return JSONResponse(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            content={
                "error_code": "INTERNAL_SERVER_ERROR",
                "message": "An internal error occurred"
            }
        )


async def logging_middleware(request: Request, call_next: Callable):
    """Log all requests and responses"""
    
    start_time = time.time()
    endpoint = request.url.path
    request_id = getattr(request.state, "request_id", request.headers.get("X-Correlation-Id") or generate_correlation_id())
    user_id = getattr(request.state, "user_id", request.headers.get("X-User-Id"))

    bind_request_context(request_id=request_id, user_id=user_id)

    with traced_operation(
        f"http {request.method} {endpoint}",
        {
            "http.method": request.method,
            "http.target": endpoint,
            "request.id": request_id,
            "user.id": user_id or "anonymous",
        },
    ):
        try:
            response = await call_next(request)
        except Exception as exc:
            duration = time.time() - start_time
            observe_request(endpoint, request.method, 500, duration)
            logger.error(
                "http_request_failed",
                method=request.method,
                path=endpoint,
                status_code=500,
                duration_ms=round(duration * 1000, 2),
                request_id=request_id,
                user_id=user_id,
                error=str(exc),
            )
            raise
        finally:
            clear_request_context()

    process_time = time.time() - start_time
    observe_request(endpoint, request.method, response.status_code, process_time)

    logger.info(
        "http_request_completed",
        method=request.method,
        path=endpoint,
        status_code=response.status_code,
        duration_ms=round(process_time * 1000, 2),
        request_id=request_id,
        user_id=user_id,
    )

    response.headers["X-Process-Time"] = str(process_time)
    response.headers["X-Request-Id"] = request_id
    return response


async def request_size_limit_middleware(request: Request, call_next: Callable):
    """Enforce request body size limits to prevent DOS attacks"""
    from api.validation import ValidationConfig, PayloadTooLargeError
    
    # Skip size checks for certain endpoints
    if request.url.path in ["/api/v1/health", "/api/v1/health/ready", "/api/v1/health/live", "/metrics"]:
        return await call_next(request)
    
    # Get content length header
    content_length = request.headers.get("content-length")
    if content_length:
        try:
            content_length_bytes = int(content_length)
            max_json_body = ValidationConfig.MAX_JSON_BODY
            
            # For file uploads, allow larger sizes
            if request.url.path.startswith("/api/v1/analyze/upload") or request.url.path.startswith("/api/v1/documents"):
                max_size = ValidationConfig.MAX_UPLOAD_SIZE
            else:
                max_size = max_json_body
            
            if content_length_bytes > max_size:
                logger.warning(
                    "request_size_limit_exceeded",
                    path=request.url.path,
                    content_length=content_length_bytes,
                    max_size=max_size,
                    size_mb=round(content_length_bytes / 1024 / 1024, 2),
                )
                raise PayloadTooLargeError(
                    detail=f"Request body too large: {round(content_length_bytes / 1024 / 1024, 2)} MB (max {round(max_size / 1024 / 1024, 2)} MB)"
                )
        except (ValueError, TypeError):
            pass  # Invalid content-length, let the request proceed
    
    return await call_next(request)
