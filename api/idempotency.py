"""
Redis-backed idempotency manager for Celery tasks.
"""
from __future__ import annotations

import os
import json
import time
from typing import Optional, Any
import structlog

try:
    import redis
except Exception:  # pragma: no cover - runtime dependency may not be present in tests
    redis = None

logger = structlog.get_logger(__name__)


class IdempotencyManager:
    """Simple Redis-backed idempotency manager.

    Usage:
        manager = IdempotencyManager()
        if not manager.acquire(key, ttl=60):
            return manager.get_result(key)
        try:
            result = do_work()
            manager.mark_completed(key, result)
            return result
        finally:
            manager.release_lock(key)
    """

    def __init__(self, redis_url: Optional[str] = None):
        self.redis_url = redis_url or os.getenv("REDIS_URL", "redis://localhost:6379/0")
        self._client = None

    @property
    def client(self):
        if self._client is None:
            if redis is None:
                raise RuntimeError("redis library is required for idempotency manager")
            self._client = redis.from_url(self.redis_url, decode_responses=False)
        return self._client

    def _key_lock(self, key: str) -> str:
        return f"idemp:lock:{key}"

    def _key_result(self, key: str) -> str:
        return f"idemp:result:{key}"

    def acquire(self, key: str, ttl: int = 60) -> bool:
        """Acquire a lock for the given idempotency key. Returns True if acquired."""
        lock_key = self._key_lock(key)
        try:
            # SET NX with expiry
            acquired = self.client.set(lock_key, b"1", nx=True, ex=ttl)
            if acquired:
                logger.info("idempotency_lock_acquired", key=key)
            else:
                logger.info("idempotency_lock_exists", key=key)
            return bool(acquired)
        except Exception as e:
            logger.error("idempotency_acquire_failed", key=key, error=str(e))
            # Fail open: if Redis is unavailable, allow processing
            return True

    def mark_completed(self, key: str, result: Any, ttl: int = 3600) -> None:
        """Mark the key as completed and store the serialized result."""
        res_key = self._key_result(key)
        try:
            payload = json.dumps({"result": result, "timestamp": int(time.time())}).encode("utf-8")
            self.client.set(res_key, payload, ex=ttl)
            # Release the lock key if present
            try:
                self.client.delete(self._key_lock(key))
            except Exception:
                pass
            logger.info("idempotency_marked_completed", key=key)
        except Exception as e:
            logger.error("idempotency_mark_completed_failed", key=key, error=str(e))

    def get_result(self, key: str) -> Optional[Any]:
        """Return stored result for a completed idempotency key, or None."""
        res_key = self._key_result(key)
        try:
            raw = self.client.get(res_key)
            if not raw:
                return None
            data = json.loads(raw.decode("utf-8"))
            return data.get("result")
        except Exception as e:
            logger.error("idempotency_get_result_failed", key=key, error=str(e))
            return None

    def release_lock(self, key: str) -> None:
        try:
            self.client.delete(self._key_lock(key))
        except Exception:
            pass
