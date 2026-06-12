"""SQLAlchemy 2.0 ORM 表定义。

设计要点：
- 4 表：users / sessions / messages / tool_calls，外键全部 ON DELETE CASCADE
- sessions.id 用 UUID（对外暴露的 session_id，不可枚举）；users.id 用自增（内部主键）
- JSON 列：PostgreSQL 上用 JSONB（可索引、可查询），SQLite 上自动退化为 JSON 文本
  （with_variant 模式——同一套模型在生产 PG 与测试 SQLite 间无缝切换）
- 高频查询路径加复合索引：history 列表按 (user_id, created_at DESC) 取
- messages 表为多轮对话预留：seq 递增，UNIQUE(session_id, seq) 防并发重复
"""

from __future__ import annotations

import datetime
import uuid

from sqlalchemy import (
    JSON,
    BigInteger,
    DateTime,
    Float,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
    Uuid,
    func,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship

# PostgreSQL 用 JSONB，其余方言（SQLite 测试）退化为通用 JSON
JsonVariant = JSON().with_variant(JSONB(), "postgresql")
# SQLite 不支持 BigInteger 自增主键，退化为 Integer
BigIntPk = BigInteger().with_variant(Integer(), "sqlite")


class Base(DeclarativeBase):
    pass


class User(Base):
    __tablename__ = "users"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    username: Mapped[str] = mapped_column(String(64), unique=True, index=True)
    display_name: Mapped[str] = mapped_column(String(128), default="")
    hashed_password: Mapped[str] = mapped_column(String(128))
    created_at: Mapped[datetime.datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )

    sessions: Mapped[list[AnalysisSession]] = relationship(
        back_populates="user", cascade="all, delete-orphan", passive_deletes=True
    )


class AnalysisSession(Base):
    """一次分析会话（一条被检消息 + agent 的完整处理过程与结论）。"""

    __tablename__ = "sessions"

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    user_id: Mapped[int] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), index=True
    )
    message_type: Mapped[str] = mapped_column(String(32), default="sms")
    verdict: Mapped[str | None] = mapped_column(String(16))
    confidence: Mapped[float | None] = mapped_column(Float)
    summary: Mapped[str | None] = mapped_column(Text)
    advice: Mapped[list | None] = mapped_column(JsonVariant)
    evidence: Mapped[list | None] = mapped_column(JsonVariant)
    created_at: Mapped[datetime.datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )

    user: Mapped[User] = relationship(back_populates="sessions")
    messages: Mapped[list[Message]] = relationship(
        back_populates="session",
        cascade="all, delete-orphan",
        passive_deletes=True,
        order_by="Message.seq",
    )
    tool_calls: Mapped[list[ToolCall]] = relationship(
        back_populates="session",
        cascade="all, delete-orphan",
        passive_deletes=True,
        order_by="ToolCall.step_number",
    )

    # history 列表查询路径：WHERE user_id = ? ORDER BY created_at DESC
    __table_args__ = (Index("ix_sessions_user_created", "user_id", "created_at"),)


class Message(Base):
    """会话内的对话轮次（user 提交的原文 / agent 的最终回复）。"""

    __tablename__ = "messages"

    id: Mapped[int] = mapped_column(BigIntPk, primary_key=True, autoincrement=True)
    session_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("sessions.id", ondelete="CASCADE"), index=True
    )
    seq: Mapped[int] = mapped_column(Integer)
    role: Mapped[str] = mapped_column(String(16))  # user | agent
    content: Mapped[str] = mapped_column(Text)
    created_at: Mapped[datetime.datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )

    session: Mapped[AnalysisSession] = relationship(back_populates="messages")

    __table_args__ = (UniqueConstraint("session_id", "seq", name="uq_messages_session_seq"),)


class ToolCall(Base):
    """ReAct 循环中每一次工具调用的日志（推理可视化与审计用）。"""

    __tablename__ = "tool_calls"

    id: Mapped[int] = mapped_column(BigIntPk, primary_key=True, autoincrement=True)
    session_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("sessions.id", ondelete="CASCADE"), index=True
    )
    step_number: Mapped[int] = mapped_column(Integer)
    total_steps: Mapped[int] = mapped_column(Integer, default=0)
    thought: Mapped[str | None] = mapped_column(Text)
    tool_name: Mapped[str] = mapped_column(String(64))
    tool_input: Mapped[dict | None] = mapped_column(JsonVariant)
    tool_output: Mapped[dict | None] = mapped_column(JsonVariant)
    created_at: Mapped[datetime.datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )

    session: Mapped[AnalysisSession] = relationship(back_populates="tool_calls")
