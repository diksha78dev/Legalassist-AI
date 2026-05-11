"""
Dependency injection and common dependencies
"""
from typing import Optional
from fastapi import Depends, HTTPException, status
from api.auth import get_current_user, CurrentUser


async def get_rate_limit_key(
    current_user: Optional[CurrentUser] = Depends(get_current_user)
) -> str:
    """Get rate limit key for current user/API key"""
    if current_user:
        return f"user:{current_user.user_id}"
    return "anonymous"


async def verify_api_version(
    x_api_version: Optional[str] = None
) -> str:
    """Verify API version from header"""
    if x_api_version and x_api_version not in ["v1"]:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Unsupported API version: {x_api_version}. Use v1"
        )
    return x_api_version or "v1"
