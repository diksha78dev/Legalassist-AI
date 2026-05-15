"""Tests for FeatureFlagManager"""

import os
import pytest
from unittest.mock import MagicMock

from api.feature_flags import FeatureFlagManager, get_feature_flag_manager


def test_defaults_and_env_override(monkeypatch):
    defaults = {"NEW_UI": False}
    manager = FeatureFlagManager(defaults=defaults)

    # default false
    assert manager.is_enabled("new_ui") is False

    # env override
    monkeypatch.setenv("FEATURE_NEW_UI", "1")
    assert manager.is_enabled("new_ui") is True


def test_redis_override(monkeypatch):
    fake_redis = MagicMock()
    fake_redis.get.return_value = "1"

    manager = FeatureFlagManager(defaults={"X": False}, redis_url="redis://fake")
    manager._client = fake_redis

    assert manager.is_enabled("x") is True
    fake_redis.get.assert_called()


def test_set_flag_without_redis(monkeypatch):
    manager = FeatureFlagManager()
    # no redis configured -> set_flag should return False
    assert manager.set_flag("feature", True) is False


def test_get_feature_flag_manager_singleton():
    m1 = get_feature_flag_manager()
    m2 = get_feature_flag_manager()
    assert m1 is m2
