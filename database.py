"""
Database models for deadline tracking and notification management.
Uses SQLAlchemy ORM with SQLite for persistence.
"""

from datetime import datetime, timezone
from typing import Optional, List
from sqlalchemy import (
    create_engine,
    Column,
    Integer,
    String,
    DateTime,
    Boolean,
    Text,
    ForeignKey,
    Enum as SQLEnum,
)
from sqlalchemy.orm import declarative_base, relationship, sessionmaker, Session
import enum
import os

# Database setup
DATABASE_URL = os.getenv("DATABASE_URL", "sqlite:///./legalassist.db")
engine = create_engine(DATABASE_URL, connect_args={"check_same_thread": False} if "sqlite" in DATABASE_URL else {})
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)
Base = declarative_base()


class NotificationStatus(str, enum.Enum):
    """Status of sent notifications"""
    PENDING = "pending"
    SENT = "sent"
    FAILED = "failed"
    BOUNCED = "bounced"
    OPENED = "opened"


class NotificationChannel(str, enum.Enum):
    """Channel for sending notifications"""
    SMS = "sms"
    EMAIL = "email"
    BOTH = "both"


class CaseDeadline(Base):
    """Model for case deadlines"""
    __tablename__ = "case_deadlines"

    id = Column(Integer, primary_key=True, index=True)
    user_id = Column(String, index=True, nullable=False)
    case_id = Column(String, nullable=False)
    case_title = Column(String, nullable=False)
    deadline_date = Column(DateTime, nullable=False, index=True)
    deadline_type = Column(String, nullable=False)  # appeal, filing, submission, etc.
    description = Column(Text, nullable=True)
    created_at = Column(DateTime, default=lambda: datetime.now(timezone.utc), nullable=False)
    updated_at = Column(DateTime, default=lambda: datetime.now(timezone.utc), onupdate=lambda: datetime.now(timezone.utc))
    is_completed = Column(Boolean, default=False)

    # Relationships
    notifications = relationship("NotificationLog", back_populates="deadline", cascade="all, delete-orphan")

    def days_until_deadline(self) -> int:
        """Calculate days remaining until deadline"""
        now = datetime.now(timezone.utc)
        delta = self.deadline_date - now
        return max(0, delta.days)

    def __repr__(self):
        return f"<CaseDeadline(user_id={self.user_id}, case_id={self.case_id}, deadline_date={self.deadline_date})>"


class UserPreference(Base):
    """Model for user notification preferences"""
    __tablename__ = "user_preferences"

    id = Column(Integer, primary_key=True, index=True)
    user_id = Column(String, unique=True, nullable=False, index=True)
    phone_number = Column(String, nullable=True)
    email = Column(String, nullable=False)
    notification_channel = Column(SQLEnum(NotificationChannel), default=NotificationChannel.BOTH)
    timezone = Column(String, default="UTC")  # e.g., "Asia/Kolkata", "America/New_York"
    notify_30_days = Column(Boolean, default=True)
    notify_10_days = Column(Boolean, default=True)
    notify_3_days = Column(Boolean, default=True)
    notify_1_day = Column(Boolean, default=True)
    created_at = Column(DateTime, default=lambda: datetime.now(timezone.utc))
    updated_at = Column(DateTime, default=lambda: datetime.now(timezone.utc), onupdate=lambda: datetime.now(timezone.utc))

    def __repr__(self):
        return f"<UserPreference(user_id={self.user_id}, channel={self.notification_channel})>"


class NotificationLog(Base):
    """Model for tracking sent notifications"""
    __tablename__ = "notification_logs"

    id = Column(Integer, primary_key=True, index=True)
    deadline_id = Column(Integer, ForeignKey("case_deadlines.id"), nullable=False, index=True)
    user_id = Column(String, nullable=False, index=True)
    channel = Column(SQLEnum(NotificationChannel), nullable=False)
    status = Column(SQLEnum(NotificationStatus), default=NotificationStatus.PENDING, index=True)
    recipient = Column(String, nullable=False)  # phone or email
    days_before = Column(Integer, nullable=False)  # 30, 10, 3, or 1 day reminder
    message_id = Column(String, nullable=True)  # From Twilio or SendGrid
    error_message = Column(Text, nullable=True)
    sent_at = Column(DateTime, nullable=True)
    delivered_at = Column(DateTime, nullable=True)
    created_at = Column(DateTime, default=lambda: datetime.now(timezone.utc), nullable=False)

    # Relationships
    deadline = relationship("CaseDeadline", back_populates="notifications")

    def __repr__(self):
        return f"<NotificationLog(user_id={self.user_id}, status={self.status}, channel={self.channel})>"


# Database initialization
def init_db():
    """Create all tables"""
    Base.metadata.create_all(bind=engine)


def get_db() -> Session:
    """Dependency for getting DB session"""
    db = SessionLocal()
    try:
        return db
    finally:
        db.close()


# ==================== Helper Functions ====================


def create_or_update_user_preference(
    db: Session,
    user_id: str,
    email: str,
    phone_number: Optional[str] = None,
    notification_channel: NotificationChannel = NotificationChannel.BOTH,
    timezone: str = "UTC",
) -> UserPreference:
    """Create or update user notification preferences"""
    pref = db.query(UserPreference).filter(UserPreference.user_id == user_id).first()
    
    if pref:
        pref.email = email
        pref.phone_number = phone_number
        pref.notification_channel = notification_channel
        pref.timezone = timezone
        pref.updated_at = datetime.now(timezone=timezone.utc)
    else:
        pref = UserPreference(
            user_id=user_id,
            email=email,
            phone_number=phone_number,
            notification_channel=notification_channel,
            timezone=timezone,
        )
        db.add(pref)
    
    db.commit()
    db.refresh(pref)
    return pref


def create_case_deadline(
    db: Session,
    user_id: str,
    case_id: str,
    case_title: str,
    deadline_date: datetime,
    deadline_type: str,
    description: Optional[str] = None,
) -> CaseDeadline:
    """Create a new case deadline"""
    deadline = CaseDeadline(
        user_id=user_id,
        case_id=case_id,
        case_title=case_title,
        deadline_date=deadline_date,
        deadline_type=deadline_type,
        description=description,
    )
    db.add(deadline)
    db.commit()
    db.refresh(deadline)
    return deadline


def get_upcoming_deadlines(db: Session, days_before: int = 30) -> List[CaseDeadline]:
    """Get all deadlines that are X days away"""
    now = datetime.now(timezone.utc)
    target_date = datetime.fromtimestamp(now.timestamp() + (days_before * 86400), tz=timezone.utc)
    
    return db.query(CaseDeadline).filter(
        CaseDeadline.is_completed == False,
        CaseDeadline.deadline_date <= target_date,
        CaseDeadline.deadline_date > now,
    ).all()


def get_user_deadlines(db: Session, user_id: str) -> List[CaseDeadline]:
    """Get all active deadlines for a user"""
    now = datetime.now(timezone.utc)
    return db.query(CaseDeadline).filter(
        CaseDeadline.user_id == user_id,
        CaseDeadline.is_completed == False,
        CaseDeadline.deadline_date > now,
    ).order_by(CaseDeadline.deadline_date).all()


def has_notification_been_sent(
    db: Session,
    deadline_id: int,
    days_before: int,
    channel: NotificationChannel,
) -> bool:
    """Check if a notification was already sent for this deadline"""
    return db.query(NotificationLog).filter(
        NotificationLog.deadline_id == deadline_id,
        NotificationLog.days_before == days_before,
        NotificationLog.channel == channel,
        NotificationLog.status.in_([NotificationStatus.SENT, NotificationStatus.OPENED]),
    ).first() is not None


def log_notification(
    db: Session,
    deadline_id: int,
    user_id: str,
    channel: NotificationChannel,
    recipient: str,
    days_before: int,
    status: NotificationStatus = NotificationStatus.PENDING,
    message_id: Optional[str] = None,
    error_message: Optional[str] = None,
) -> NotificationLog:
    """Log a notification attempt"""
    log = NotificationLog(
        deadline_id=deadline_id,
        user_id=user_id,
        channel=channel,
        recipient=recipient,
        days_before=days_before,
        status=status,
        message_id=message_id,
        error_message=error_message,
        sent_at=datetime.now(timezone.utc) if status != NotificationStatus.PENDING else None,
    )
    db.add(log)
    db.commit()
    db.refresh(log)
    return log


def get_notification_history(db: Session, user_id: str, limit: int = 50) -> List[NotificationLog]:
    """Get notification history for a user"""
    return db.query(NotificationLog).filter(
        NotificationLog.user_id == user_id
    ).order_by(NotificationLog.created_at.desc()).limit(limit).all()
