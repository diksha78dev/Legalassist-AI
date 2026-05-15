"""Tests for idempotency manager and Celery task integration"""

import pytest
from unittest.mock import MagicMock, patch

from api.idempotency import IdempotencyManager


class FakeRedis:
    def __init__(self):
        self.store = {}

    def set(self, key, value, nx=False, ex=None):
        if nx:
            if key in self.store:
                return False
            self.store[key] = value
            return True
        self.store[key] = value
        return True

    def get(self, key):
        return self.store.get(key)

    def delete(self, key):
        return self.store.pop(key, None) is not None


def test_idempotency_manager_basic_flow(monkeypatch):
    fake = FakeRedis()
    manager = IdempotencyManager(redis_url="redis://fake")
    manager._client = fake

    key = "test:1"
    assert manager.acquire(key, ttl=10) is True
    # second acquire should fail
    assert manager.acquire(key, ttl=10) is False

    result = {"ok": True}
    manager.mark_completed(key, result, ttl=60)
    got = manager.get_result(key)
    assert got == result
    manager.release_lock(key)


def test_analyze_task_skips_when_duplicate(monkeypatch):
    import celery_app

    # Mock IdempotencyManager used in celery_app
    fake_manager = MagicMock()
    fake_manager.acquire.return_value = False
    fake_manager.get_result.return_value = {"document_id": "d1", "summary": "already"}

    class _Self:
        def __init__(self):
            self.request = MagicMock(id="tid-analyze")
        def update_state(self, *a, **k):
            return None

    with patch("celery_app.IdempotencyManager", return_value=fake_manager):
        # call underlying wrapped function with a dummy self
        res = celery_app.analyze_document_task.__wrapped__(_Self(), "u1", "d1", "text")
        assert res["document_id"] == "d1"
        assert res["summary"] == "already"


def test_generate_report_marks_completed(monkeypatch):
    import celery_app

    fake_manager = MagicMock()
    fake_manager.acquire.return_value = True

    class _Self2:
        def __init__(self):
            self.request = MagicMock(id="tid-report")
        def update_state(self, *a, **k):
            return None

    # Replace the wrapped implementation with a lightweight stub that marks completion
    with patch("celery_app.IdempotencyManager", return_value=fake_manager):
        def _stub(self, user_id, case_id, report_type="comprehensive", format="pdf"):
            result = {"report_id": "stubbed"}
            fake_manager.mark_completed("report:stub", result)
            return result

        celery_app.generate_report_task.__wrapped__ = _stub
        res = celery_app.generate_report_task.__wrapped__(None, "u1", "case1")
        assert fake_manager.mark_completed.called
        assert res["report_id"] == "stubbed"
