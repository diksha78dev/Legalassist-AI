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

from api.limiter import limiter, RateLimitExceeded
from api.config import get_settings

settings = get_settings()
logger = structlog.get_logger(__name__)


async def rate_limit_middleware(request: Request, call_next: Callable):
    """
    Global rate limiting middleware.
    Applies default limits to all requests unless overridden at the route level.
    """
    
    if not settings.RATE_LIMIT_ENABLED:
        return await call_next(request)

    # Skip rate limiting for health checks and internal metrics
    path = request.url.path
    if path in ["/api/v1/health", "/api/v1/health/ready", "/api/v1/health/live", "/metrics", "/"]:
        return await call_next(request)
    
    # Identify the client
    # Priority: X-User-Id header > IP Address
    identifier = request.headers.get("X-User-Id")
    if not identifier:
        # Fallback to IP address
        identifier = request.client.host if request.client else "127.0.0.1"
    
    # Check rate limit using the sliding window engine
    # We use a broad 'global' endpoint identifier for the middleware limit
    is_allowed = await limiter.check_rate_limit(
        identifier=identifier,
        endpoint="GLOBAL_API_LIMIT",
        limit=settings.RATE_LIMIT_REQUESTS,
        window_seconds=settings.RATE_LIMIT_WINDOW
    )
    
    if not is_allowed:
        retry_after = await limiter.get_remaining_ttl(
            identifier=identifier,
            endpoint="GLOBAL_API_LIMIT",
            window_seconds=settings.RATE_LIMIT_WINDOW
        )
        
        logger.warning(
            "global_rate_limit_exceeded",
            identifier=identifier,
            path=path,
            retry_after=retry_after
        )
        
        return JSONResponse(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            content={
                "error_code": "RATE_LIMIT_EXCEEDED",
                "message": f"Global rate limit exceeded. Max {settings.RATE_LIMIT_REQUESTS} requests per {settings.RATE_LIMIT_WINDOW} seconds",
                "retry_after": retry_after
            },
            headers={"Retry-After": str(retry_after)}
        )
    
    # Process the request
    response = await call_next(request)
    
    # Add rate limit headers for transparency
    response.headers["X-RateLimit-Limit"] = str(settings.RATE_LIMIT_REQUESTS)
    # Note: Precise remaining count is available in the Lua script result if needed
    
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
