import datetime as dt
import enum
from sqlalchemy import (
    Column,
    Integer,
    String,
    DateTime,
    Boolean,
    Text,
    ForeignKey,
    UniqueConstraint,
    Index,
)
from sqlalchemy.orm import relationship
from db.base import Base


class CaseDeadline(Base):
    __tablename__ = "case_deadlines"

    id = Column(Integer, primary_key=True)
    user_id = Column(Integer, ForeignKey("users.id", ondelete="CASCADE"), index=True, nullable=False)
    case_id = Column(Integer, ForeignKey("cases.id", ondelete="CASCADE"), nullable=False, index=True)
    case_title = Column(String(255), nullable=False)
    deadline_date = Column(DateTime(timezone=True), nullable=False, index=True)
    deadline_type = Column(String(255), nullable=False)
    description = Column(Text, nullable=True)
    created_at = Column(DateTime(timezone=True), default=lambda: dt.datetime.now(dt.timezone.utc), nullable=False)
    updated_at = Column(DateTime(timezone=True), default=lambda: dt.datetime.now(dt.timezone.utc), onupdate=lambda: dt.datetime.now(dt.timezone.utc))
    is_completed = Column(Boolean, default=False, index=True)

    case = relationship("Case", back_populates="deadlines")
    notifications = relationship("NotificationLog", back_populates="deadline", cascade="all, delete-orphan")
    attachments = relationship("Attachment", back_populates="deadline", cascade="all, delete-orphan")

    def days_until_deadline(self) -> int:
        now = dt.datetime.now(dt.timezone.utc)
        deadline = self.deadline_date
        if deadline and deadline.tzinfo is None:
            deadline = deadline.replace(tzinfo=dt.timezone.utc)
        delta = deadline - now
        return max(0, delta.days)


class Case(Base):
    __tablename__ = "cases"
    __table_args__ = (UniqueConstraint("user_id", "case_number", name="uq_user_case_number"),)

    id = Column(Integer, primary_key=True)
    user_id = Column(Integer, ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True)
    case_number = Column(String(255), nullable=False)
    case_type = Column(String(255), nullable=False, index=True)
    jurisdiction = Column(String(255), nullable=False, index=True)
    status = Column(String(255), default="active", nullable=False)
    title = Column(String(255), nullable=True)
    created_at = Column(DateTime(timezone=True), default=lambda: dt.datetime.now(dt.timezone.utc), nullable=False)
    updated_at = Column(DateTime(timezone=True), default=lambda: dt.datetime.now(dt.timezone.utc), onupdate=lambda: dt.datetime.now(dt.timezone.utc))

    user = relationship("User", back_populates="cases")
    documents = relationship("CaseDocument", back_populates="case", cascade="all, delete-orphan")
    deadlines = relationship("CaseDeadline", back_populates="case", cascade="all, delete-orphan")
    timeline_events = relationship("CaseTimeline", back_populates="case", cascade="all, delete-orphan")
    attachments = relationship("Attachment", back_populates="case", cascade="all, delete-orphan")


class CaseDocument(Base):
    __tablename__ = "case_documents"

    id = Column(Integer, primary_key=True)
    case_id = Column(Integer, ForeignKey("cases.id", ondelete="CASCADE"), nullable=False, index=True)
    document_type = Column(String(255), nullable=False)
    document_content = Column(Text, nullable=True)
    file_path = Column(String(255), nullable=True)
    uploaded_at = Column(DateTime(timezone=True), default=lambda: dt.datetime.now(dt.timezone.utc), nullable=False)
    summary = Column(Text, nullable=True)
    remedies = Column(Text, nullable=True)

    case = relationship("Case", back_populates="documents")


class Attachment(Base):
    __tablename__ = "attachments"

    id = Column(Integer, primary_key=True)
    user_id = Column(Integer, ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True)
    case_id = Column(Integer, ForeignKey("cases.id", ondelete="CASCADE"), nullable=True, index=True)
    deadline_id = Column(Integer, ForeignKey("case_deadlines.id", ondelete="CASCADE"), nullable=True, index=True)
    original_filename = Column(String(255), nullable=False)
    stored_path = Column(String(1024), nullable=False)
    content_type = Column(String(255), nullable=True)
    size_bytes = Column(Integer, nullable=True)
    uploaded_at = Column(DateTime(timezone=True), default=lambda: dt.datetime.now(dt.timezone.utc), nullable=False)

    case = relationship("Case", back_populates="attachments")
    deadline = relationship("CaseDeadline", back_populates="attachments")


class CaseTimeline(Base):
    __tablename__ = "case_timeline"

    id = Column(Integer, primary_key=True)
    case_id = Column(Integer, ForeignKey("cases.id", ondelete="CASCADE"), nullable=False, index=True)
    event_type = Column(String(255), nullable=False, index=True)
    event_date = Column(DateTime(timezone=True), default=lambda: dt.datetime.now(dt.timezone.utc), nullable=False, index=True)
    description = Column(Text, nullable=False)
    event_metadata = Column(Text, nullable=True)
    created_at = Column(DateTime(timezone=True), default=lambda: dt.datetime.now(dt.timezone.utc), nullable=False)

    case = relationship("Case", back_populates="timeline_events")
