import os
from datetime import datetime, timezone

import pytest


def test_anonymized_id_changes_with_secret(monkeypatch):
    # Import inside test so monkeypatch can affect env var used during module import.
    monkeypatch.setenv("CASE_ANONYMIZATION_SECRET", "secret_a")
    import case_manager  # noqa: E402

    created_at = datetime(2024, 1, 2, 3, 4, 5, tzinfo=timezone.utc)
    anon_a = case_manager._generate_anonymized_case_id(case_id=123, created_at=created_at)

    monkeypatch.setenv("CASE_ANONYMIZATION_SECRET", "secret_b")
    anon_b = case_manager._generate_anonymized_case_id(case_id=123, created_at=created_at)

    assert anon_a != anon_b


def test_anonymized_id_deterministic_with_same_secret(monkeypatch):
    monkeypatch.setenv("CASE_ANONYMIZATION_SECRET", "same_secret")
    import case_manager  # noqa: E402

    created_at = datetime(2024, 1, 2, 3, 4, 5, tzinfo=timezone.utc)
    anon_1 = case_manager._generate_anonymized_case_id(case_id=123, created_at=created_at)
    anon_2 = case_manager._generate_anonymized_case_id(case_id=123, created_at=created_at)

    assert anon_1 == anon_2


def test_anonymized_id_format(monkeypatch):
    monkeypatch.setenv("CASE_ANONYMIZATION_SECRET", "format_secret")
    import case_manager  # noqa: E402

    created_at = datetime(2024, 1, 2, 3, 4, 5, tzinfo=timezone.utc)
    anon = case_manager._generate_anonymized_case_id(case_id=123, created_at=created_at)

    assert len(anon) == 12
    int(anon, 16)  # should be hex

