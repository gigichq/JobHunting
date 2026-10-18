"""ORM 表（02-技术设计 §6）。JSON 字段以 TEXT 存储，读写走 helpers。"""
import json
import uuid
from datetime import datetime, timezone

from sqlalchemy import (
    Boolean,
    DateTime,
    Float,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
)
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column


def new_id() -> str:
    return uuid.uuid4().hex


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


class Base(DeclarativeBase):
    pass


class JsonMixin:
    @staticmethod
    def loads(raw: str | None, default):
        if not raw:
            return default
        try:
            return json.loads(raw)
        except (ValueError, TypeError):
            return default

    @staticmethod
    def dumps(obj) -> str:
        return json.dumps(obj, ensure_ascii=False)


class User(Base, JsonMixin):
    __tablename__ = "users"
    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=new_id)
    email: Mapped[str] = mapped_column(String(255), unique=True, index=True)
    password_hash: Mapped[str] = mapped_column(String(128))
    display_name: Mapped[str] = mapped_column(String(64))
    age_confirmed_at: Mapped[datetime | None] = mapped_column(DateTime, default=None)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)


class DiagSession(Base, JsonMixin):
    __tablename__ = "sessions"
    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=new_id)
    user_id: Mapped[str] = mapped_column(String(32), ForeignKey("users.id"), index=True)
    mode: Mapped[str] = mapped_column(String(10))  # quick | full
    identity: Mapped[str] = mapped_column(String(16))  # student | professional
    # active | wrapping | ended | generating | report_ready | failed
    status: Mapped[str] = mapped_column(String(16), default="active")
    profile_json: Mapped[str | None] = mapped_column(Text, default=None)
    coverage_json: Mapped[str | None] = mapped_column(Text, default=None)
    turn_count: Mapped[int] = mapped_column(Integer, default=0)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow, onupdate=utcnow)
    ended_at: Mapped[datetime | None] = mapped_column(DateTime, default=None)

    @property
    def profile(self) -> dict:
        return self.loads(self.profile_json, {})

    @property
    def coverage(self) -> dict:
        return self.loads(self.coverage_json, {})


class Message(Base, JsonMixin):
    __tablename__ = "messages"
    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=new_id)
    session_id: Mapped[str] = mapped_column(String(32), ForeignKey("sessions.id"))
    seq: Mapped[int] = mapped_column(Integer)
    role: Mapped[str] = mapped_column(String(10))  # assistant | user
    content: Mapped[str] = mapped_column(Text)
    dimension_key: Mapped[str | None] = mapped_column(String(20), default=None)
    decision_json: Mapped[str | None] = mapped_column(Text, default=None)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)

    __table_args__ = (Index("ix_messages_session_seq", "session_id", "seq"),)


class Report(Base, JsonMixin):
    __tablename__ = "reports"
    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=new_id)
    session_id: Mapped[str] = mapped_column(
        String(32), ForeignKey("sessions.id"), unique=True
    )
    # pending | generating | ready | failed | degraded | deleted
    status: Mapped[str] = mapped_column(String(16), default="pending")
    # extracting | verifying | scoring | concluding | composing | rendering
    progress_stage: Mapped[str | None] = mapped_column(String(20), default=None)
    run_id: Mapped[str | None] = mapped_column(String(32), default=None)
    heartbeat_at: Mapped[datetime | None] = mapped_column(DateTime, default=None)
    started_at: Mapped[datetime | None] = mapped_column(DateTime, default=None)
    version: Mapped[int] = mapped_column(Integer, default=0)
    retry_count: Mapped[int] = mapped_column(Integer, default=0)
    stages_json: Mapped[str | None] = mapped_column(Text, default=None)
    report_json: Mapped[str | None] = mapped_column(Text, default=None)
    html: Mapped[str | None] = mapped_column(Text, default=None)
    quote_hit_rate: Mapped[float | None] = mapped_column(Float, default=None)
    error: Mapped[str | None] = mapped_column(Text, default=None)
    models_used: Mapped[str | None] = mapped_column(Text, default=None)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow, onupdate=utcnow)

    @property
    def stages(self) -> dict:
        return self.loads(self.stages_json, {})


class Correction(Base, JsonMixin):
    __tablename__ = "corrections"
    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=new_id)
    report_id: Mapped[str] = mapped_column(String(32), ForeignKey("reports.id"), index=True)
    user_id: Mapped[str] = mapped_column(String(32), ForeignKey("users.id"))
    quote_or_fact: Mapped[str] = mapped_column(Text)
    comment: Mapped[str] = mapped_column(Text)
    # pending | verified_fixed | rejected
    status: Mapped[str] = mapped_column(String(16), default="pending")
    resolved_at: Mapped[datetime | None] = mapped_column(DateTime, default=None)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)


class ReportVersion(Base, JsonMixin):
    __tablename__ = "report_versions"
    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=new_id)
    report_id: Mapped[str] = mapped_column(String(32), ForeignKey("reports.id"), index=True)
    version: Mapped[int] = mapped_column(Integer)
    report_json: Mapped[str | None] = mapped_column(Text, default=None)
    html: Mapped[str | None] = mapped_column(Text, default=None)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)


class Event(Base, JsonMixin):
    __tablename__ = "events"
    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=new_id)
    user_id: Mapped[str | None] = mapped_column(String(32), default=None, index=True)
    session_id: Mapped[str | None] = mapped_column(String(32), default=None, index=True)
    event: Mapped[str] = mapped_column(String(64), index=True)
    props_json: Mapped[str | None] = mapped_column(Text, default=None)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)
