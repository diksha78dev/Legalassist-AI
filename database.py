"""Compatibility shim for the original monolithic `database.py`.

The project has moved models and CRUD helpers into the `db/` package, but many
existing imports still point at `database`. This module re-exports the pieces
needed by the current codebase and keeps the authentication/OTP security path
working while the refactor continues.
"""

from __future__ import annotations

import datetime as dt
import hashlib
from contextlib import contextmanager
from typing import Optional, List

import enum
try:
    import redis
except ImportError:  # pragma: no cover - runtime optional dependency
    redis = None

from sqlalchemy import Column, Integer, String, DateTime, Boolean, Text, ForeignKey, Enum as SQLEnum, UniqueConstraint
from sqlalchemy.orm import Session, relationship

from config import Config
from db.base import Base
from db.session import engine, SessionLocal, init_db, db_session, get_db, _to_utc_datetime, _datetime_for_db
from db.models.auth import User, OTPVerification
from db.models.notifications import NotificationStatus, NotificationChannel, NotificationLog, NotificationTemplate, UserPreference
from db.models.cases import CaseDeadline, Case, CaseDocument, Attachment, CaseTimeline
from db.crud.notifications import (
    create_case_deadline,
    get_upcoming_deadlines,
    has_notification_been_sent,
    log_notification,
    get_notification_history,
)
from db.crud.feedback import submit_user_feedback, get_user_feedback


class RevokedToken(Base):
    __tablename__ = "revoked_tokens"

    id = Column(Integer, primary_key=True)
    jti = Column(String(255), unique=True, nullable=False, index=True)
    revoked_at = Column(DateTime(timezone=True), default=lambda: dt.datetime.now(dt.timezone.utc), nullable=False)
    expires_at = Column(DateTime(timezone=True), nullable=False, index=True)


_OTP_RATE_LIMIT_WINDOW_SECONDS = 60 * 60
_OTP_RATE_LIMIT_SCRIPT = """
local current = redis.call('INCR', KEYS[1])
if current == 1 then
    redis.call('EXPIRE', KEYS[1], ARGV[1])
end
return current
"""
_otp_rate_limit_client = None
_otp_rate_limit_script = None


def _otp_rate_limit_key(identifier: str) -> str:
    normalized = str(identifier).strip().lower()
    digest = hashlib.sha256(normalized.encode("utf-8")).hexdigest()
    return f"otp:rate:{digest}"


def _get_otp_rate_limit_script():
    global _otp_rate_limit_client, _otp_rate_limit_script

    if _otp_rate_limit_script is None:
        if redis is None:
            raise RuntimeError("Redis is required for OTP rate limiting but is not installed.")

        redis_url = getattr(Config, "REDIS_URL", "redis://localhost:6379/0")
        _otp_rate_limit_client = redis.from_url(redis_url, decode_responses=True)
        _otp_rate_limit_script = _otp_rate_limit_client.register_script(_OTP_RATE_LIMIT_SCRIPT)

    return _otp_rate_limit_script


def _reserve_otp_rate_limit_slot(identifier: str, max_requests_per_hour: int, label: str = "identifier") -> int:
    normalized_identifier = str(identifier).strip().lower()
    if not normalized_identifier:
        raise ValueError(f"{label} is required for OTP rate limiting")

    script = _get_otp_rate_limit_script()
    current = int(script(keys=[_otp_rate_limit_key(normalized_identifier)], args=[_OTP_RATE_LIMIT_WINDOW_SECONDS]))

    if current > max_requests_per_hour:
        raise ValueError("Too many OTP requests. Please try again later.")

    return current


def create_otp_verification(
    db: Session,
    email: str,
    otp_hash: str,
    expires_at: dt.datetime,
    max_requests_per_hour: int = 5,
    requester_ip: Optional[str] = None,
) -> OTPVerification:
    """Create a new OTP verification record with rate limiting."""
    _reserve_otp_rate_limit_slot(email, max_requests_per_hour, label="Email")
    if requester_ip:
        _reserve_otp_rate_limit_slot(requester_ip, max_requests_per_hour, label="IP")

    otp = OTPVerification(
        email=email,
        otp_hash=otp_hash,
        expires_at=expires_at,
    )
    db.add(otp)
    db.commit()
    db.refresh(otp)
    return otp


def get_pending_otp(db: Session, email: str) -> Optional[OTPVerification]:
    now = dt.datetime.now(dt.timezone.utc)
    return db.query(OTPVerification).filter(
        OTPVerification.email == email,
        OTPVerification.is_used == False,
        OTPVerification.expires_at > now,
    ).order_by(OTPVerification.created_at.desc()).first()


def mark_otp_as_used(db: Session, otp_id: int) -> bool:
    try:
        otp = db.query(OTPVerification).filter(OTPVerification.id == otp_id).first()
        if otp:
            otp.is_used = True
            db.commit()
            db.refresh(otp)
            return True
        return False
    except Exception:
        db.rollback()
        return False


def record_otp_failed_attempt(db: Session, otp_id: int, lockout_duration_minutes: int = 15, max_failed_attempts: int = 5) -> bool:
    otp = db.query(OTPVerification).filter(OTPVerification.id == otp_id).first()
    if otp:
        otp.failed_attempts += 1
        if otp.failed_attempts >= max_failed_attempts:
            otp.locked_until = dt.datetime.now(dt.timezone.utc) + dt.timedelta(minutes=lockout_duration_minutes)
        db.commit()
        db.refresh(otp)
        return True
    return False


def reset_otp_failed_attempts(db: Session, otp_id: int) -> bool:
    otp = db.query(OTPVerification).filter(OTPVerification.id == otp_id).first()
    if otp:
        otp.failed_attempts = 0
        otp.locked_until = None
        db.commit()
        db.refresh(otp)
        return True
    return False


def cleanup_expired_otps(db: Session) -> int:
    now = dt.datetime.now(dt.timezone.utc)
    deleted = db.query(OTPVerification).filter(OTPVerification.expires_at < now).delete()
    db.commit()
    return deleted


def get_user_by_email(db: Session, email: str) -> Optional[User]:
    return db.query(User).filter(User.email == email).first()


def create_user(db: Session, email: str) -> User:
    user = User(email=email)
    db.add(user)
    db.commit()
    db.refresh(user)
    return user


def update_user_last_login(db: Session, user_id: int) -> Optional[User]:
    user = db.query(User).filter(User.id == user_id).first()
    if user:
        user.last_login = dt.datetime.now(dt.timezone.utc)
        db.commit()
        db.refresh(user)
    return user


def revoke_token(db: Session, jti: str, expires_at: dt.datetime) -> RevokedToken:
    token = RevokedToken(jti=jti, expires_at=expires_at)
    db.add(token)
    db.commit()
    db.refresh(token)
    return token


def is_token_revoked(db: Session, jti: str) -> bool:
    return db.query(RevokedToken).filter(RevokedToken.jti == jti).first() is not None


def cleanup_expired_revoked_tokens(db: Session) -> int:
    now = dt.datetime.now(dt.timezone.utc)
    deleted = db.query(RevokedToken).filter(RevokedToken.expires_at < now).delete()
    db.commit()
    return deleted


__all__ = [
    "Base",
    "engine",
    "SessionLocal",
    "init_db",
    "db_session",
    "get_db",
    "_to_utc_datetime",
    "_datetime_for_db",
    "User",
    "OTPVerification",
    "RevokedToken",
    "NotificationStatus",
    "NotificationChannel",
    "NotificationLog",
    "NotificationTemplate",
    "UserPreference",
    "CaseDeadline",
    "Case",
    "CaseDocument",
    "Attachment",
    "CaseTimeline",
    "create_case_deadline",
    "get_upcoming_deadlines",
    "has_notification_been_sent",
    "log_notification",
    "get_notification_history",
    "submit_user_feedback",
    "get_user_feedback",
    "create_otp_verification",
    "get_pending_otp",
    "mark_otp_as_used",
    "record_otp_failed_attempt",
    "reset_otp_failed_attempts",
    "cleanup_expired_otps",
    "get_user_by_email",
    "create_user",
    "update_user_last_login",
    "revoke_token",
    "is_token_revoked",
    "cleanup_expired_revoked_tokens",
]
