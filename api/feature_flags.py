"""
Feature flag manager with optional Redis backend and env overrides.
"""
from __future__ import annotations

import os
from typing import Optional, Dict
import structlog

try:
    import redis
except Exception:  # pragma: no cover
    redis = None

logger = structlog.get_logger(__name__)


class FeatureFlagManager:
    """Simple feature flag manager.

    Priority order:
      1. Redis backend (if configured and available)
      2. Environment variables (FEATURE_<NAME>=1)
      3. Default values provided at init
    """

    def __init__(self, defaults: Optional[Dict[str, bool]] = None, redis_url: Optional[str] = None):
        self.defaults = defaults or {}
        self.redis_url = redis_url or os.getenv("REDIS_URL")
        self._client = None

    @property
    def client(self):
        if self._client is None and self.redis_url:
            if redis is None:
                logger.warning("redis_not_installed_for_feature_flags")
                self._client = None
            else:
                try:
                    self._client = redis.from_url(self.redis_url, decode_responses=True)
                except Exception as e:
                    logger.error("feature_flags_redis_init_failed", error=str(e))
                    self._client = None
        return self._client

    def _redis_key(self, name: str) -> str:
        return f"feature:{name}"

    def is_enabled(self, name: str) -> bool:
        name_up = name.upper()
        # 1) Redis override
        try:
            client = self.client
            if client:
                val = client.get(self._redis_key(name_up))
                if val is not None:
                    return str(val).lower() in ("1", "true", "yes", "on")
        except Exception as e:
            logger.warning("feature_flags_redis_unavailable", error=str(e))

        # 2) Env var override
        env_key = f"FEATURE_{name_up}"
        env_val = os.getenv(env_key)
        if env_val is not None:
            return env_val.lower() in ("1", "true", "yes", "on")

        # 3) Defaults
        return bool(self.defaults.get(name_up, False))

    def set_flag(self, name: str, enabled: bool) -> bool:
        name_up = name.upper()
        client = self.client
        if not client:
            logger.warning("feature_flags_no_redis", name=name_up)
            return False
        try:
            client.set(self._redis_key(name_up), "1" if enabled else "0")
            return True
        except Exception as e:
            logger.error("feature_flags_set_failed", name=name_up, error=str(e))
            return False


# singleton
_manager: Optional[FeatureFlagManager] = None


def get_feature_flag_manager(defaults: Optional[Dict[str, bool]] = None) -> FeatureFlagManager:
    global _manager
    if _manager is None:
        _manager = FeatureFlagManager(defaults=defaults)
    return _manager
