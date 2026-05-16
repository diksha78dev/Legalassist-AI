"""
API Configuration
"""
import os
from functools import lru_cache
from pathlib import Path
from typing import Optional
from pydantic_settings import BaseSettings
from pydantic import field_validator


class APISettings(BaseSettings):
    """API Configuration"""
    
    # API Info
    API_TITLE: str = "Legalassist-AI"
    API_VERSION: str = "1.0.0"
    API_DESCRIPTION: str = "Comprehensive legal case analysis and deadline management API"
    
    # Server
    API_HOST: str = os.getenv("API_HOST", "0.0.0.0")
    API_PORT: int = int(os.getenv("API_PORT", "8000"))
    API_WORKERS: int = int(os.getenv("API_WORKERS", "4"))
    
    # CORS
    CORS_ORIGINS: list = [
        "http://localhost:3000",
        "http://localhost:8501",
        "http://localhost:8000",
    ]
    
    # Allowed Hosts for TrustedHostMiddleware
    # Format: comma-separated (localhost,127.0.0.1,example.com) or JSON array
    # Default: localhost, 127.0.0.1
    ALLOWED_HOSTS: list = None
    
    # Rate Limiting
    RATE_LIMIT_ENABLED: bool = True
    RATE_LIMIT_REQUESTS: int = 100  # requests
    RATE_LIMIT_WINDOW: int = 60  # seconds
    RATE_LIMIT_BURST: int = 200  # max burst
    
    # Authentication Rate Limiting (Credential Stuffing Protection)
    AUTH_RATE_LIMIT_REQUESTS: int = 5  # tight limit for login
    AUTH_RATE_LIMIT_WINDOW: int = 60   # per minute
    AUTH_RATE_LIMIT_STRATEGY: str = "fixed-window"  # or 'sliding-window'
    
    # Authentication
    AUTH_ENABLED: bool = True
    JWT_SECRET_KEY: str = os.getenv("JWT_SECRET_KEY", "")
    JWT_ALGORITHM: str = "HS256"
    JWT_EXPIRATION_HOURS: int = 24
    API_KEY_HEADER: str = "X-API-Key"
    
    @field_validator("JWT_SECRET_KEY")
    @classmethod
    def validate_jwt_secret(cls, v: str) -> str:
        if not v or v == "your-secret-key-change-in-production":
            raise ValueError(
                "JWT_SECRET_KEY must be set to a secure value. "
                "Do not use default or placeholder values in production."
            )
        return v
    
    # Database
    DATABASE_URL: str = os.getenv("DATABASE_URL", "")
    DATABASE_POOL_SIZE: int = 20
    DATABASE_MAX_OVERFLOW: int = 10
    
    # Redis
    REDIS_URL: str = os.getenv("REDIS_URL", "redis://localhost:6379/0")
    REDIS_CACHE_TTL: int = 3600  # 1 hour
    
    # Celery
    CELERY_BROKER_URL: str = os.getenv("CELERY_BROKER_URL", "redis://localhost:6379/1")
    CELERY_RESULT_BACKEND: str = os.getenv("CELERY_RESULT_BACKEND", "redis://localhost:6379/2")
    CELERY_TASK_TIMEOUT: int = 3600  # 1 hour
    CELERY_TASK_SOFT_TIME_LIMIT: int = 3300  # 55 minutes
    
    # File Upload
    UPLOAD_MAX_SIZE: int = 25 * 1024 * 1024  # 25 MB
    UPLOAD_EXTENSIONS: list = [".pdf", ".doc", ".docx", ".txt"]
    UPLOAD_TEMP_DIR: str = os.getenv(
        "UPLOAD_TEMP_DIR",
        str(Path(tempfile.gettempdir()) / "legalassist-uploads")
    )
    
    # PDF Export
    PDF_MAX_PAGES: int = 5000
    PDF_QUALITY: str = "high"  # low, medium, high
    
    # LLM Settings
    LLM_MAX_TOKENS: int = 2000
    LLM_TEMPERATURE: float = 0.7
    LLM_MODEL: str = "gpt-4"
    LLM_TIMEOUT: int = 120  # seconds
    
    # Logging
    LOG_LEVEL: str = os.getenv("LOG_LEVEL", "INFO")
    LOG_FORMAT: str = "json"
    
    # Observability
    ENABLE_METRICS: bool = True
    ENABLE_TRACING: bool = True
    JAEGER_ENABLED: bool = os.getenv("JAEGER_ENABLED", "false").lower() == "true"
    
    # Feature Flags
    ENABLE_OAUTH2: bool = os.getenv("ENABLE_OAUTH2", "true").lower() == "true"
    ENABLE_WEBSOCKET: bool = os.getenv("ENABLE_WEBSOCKET", "true").lower() == "true"
    ENABLE_ANALYTICS: bool = os.getenv("ENABLE_ANALYTICS", "true").lower() == "true"
    
    def __init__(self, **data):
        super().__init__(**data)
        # Parse ALLOWED_HOSTS from environment
        if self.ALLOWED_HOSTS is None:
            hosts_env = os.getenv("APP_ALLOWED_HOSTS", "")
            if hosts_env.strip():
                # Support both comma-separated and JSON formats
                if hosts_env.startswith('['):
                    import json
                    try:
                        self.ALLOWED_HOSTS = json.loads(hosts_env)
                    except (json.JSONDecodeError, ValueError):
                        self.ALLOWED_HOSTS = [h.strip() for h in hosts_env.split(',') if h.strip()]
                else:
                    self.ALLOWED_HOSTS = [h.strip() for h in hosts_env.split(',') if h.strip()]
            else:
                # Safe defaults for development
                self.ALLOWED_HOSTS = ["localhost", "127.0.0.1"]
    
    class Config:
        env_file = ".env"
        case_sensitive = True


@lru_cache()
def get_settings() -> APISettings:
    """Get API settings (cached)"""
    return APISettings()
