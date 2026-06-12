"""Repository 层：所有数据库读写的唯一入口。

每个函数显式接收 AsyncSession（路由用 Depends(get_session) 注入，
WebSocket 自行开启会话），不在这里 commit——事务边界由调用方控制。
返回 dict 形状与旧版（aiosqlite 时代）完全一致，REST/WS 契约不变。
"""

from __future__ import annotations

import datetime
import uuid

from sqlalchemy import and_, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from .orm import AnalysisSession, Message, ToolCall, User


def _fmt_dt(dt: datetime.datetime | None) -> str:
    """统一时间序列化：UTC、'YYYY-MM-DD HH:MM:SS'（与旧 SQLite 输出兼容）。"""
    if dt is None:
        return ""
    if dt.tzinfo is not None:
        dt = dt.astimezone(datetime.UTC).replace(tzinfo=None)
    return dt.strftime("%Y-%m-%d %H:%M:%S")


def _parse_ts(ts: str | None) -> datetime.datetime | None:
    if not ts:
        return None
    try:
        return datetime.datetime.fromisoformat(ts)
    except ValueError:
        return None


def _to_uuid(session_id: str) -> uuid.UUID | None:
    try:
        return uuid.UUID(session_id)
    except (ValueError, AttributeError, TypeError):
        return None


# ===================================================================
# User
# ===================================================================

async def create_user(
    db: AsyncSession, username: str, hashed_password: str, display_name: str = ""
) -> int:
    user = User(
        username=username,
        hashed_password=hashed_password,
        display_name=display_name or username,
    )
    db.add(user)
    await db.flush()  # 拿到自增 id，不提交
    return user.id


async def get_user_by_username(db: AsyncSession, username: str) -> dict | None:
    user = await db.scalar(select(User).where(User.username == username))
    if not user:
        return None
    return {
        "id": user.id,
        "username": user.username,
        "display_name": user.display_name,
        "hashed_password": user.hashed_password,
    }


# ===================================================================
# Session / Message / ToolCall（全部按 user_id 隔离）
# ===================================================================

async def create_session(
    db: AsyncSession, session_id: str, user_id: int, message: str, message_type: str
) -> None:
    sid = _to_uuid(session_id)
    db.add(AnalysisSession(id=sid, user_id=user_id, message_type=message_type))
    db.add(Message(session_id=sid, seq=1, role="user", content=message))


async def save_step(
    db: AsyncSession,
    session_id: str,
    step_number: int,
    total_steps: int,
    thought: str,
    tool_name: str,
    tool_input: dict,
    tool_output: dict,
    timestamp: str,
) -> None:
    db.add(ToolCall(
        session_id=_to_uuid(session_id),
        step_number=step_number,
        total_steps=total_steps,
        thought=thought,
        tool_name=tool_name,
        tool_input=tool_input,
        tool_output=tool_output,
        created_at=_parse_ts(timestamp),
    ))


async def save_result(
    db: AsyncSession,
    session_id: str,
    verdict: str | None,
    confidence: float | None,
    summary: str,
    advice: list[str],
    evidence: list[dict] | None = None,
) -> None:
    sid = _to_uuid(session_id)
    sess = await db.get(AnalysisSession, sid)
    if sess is None:
        return
    sess.verdict = verdict
    sess.confidence = confidence
    sess.summary = summary
    sess.advice = advice
    sess.evidence = evidence or []
    # agent 的最终回复也作为一轮对话落表（多轮扩展的基础）
    next_seq = (
        await db.scalar(
            select(Message.seq)
            .where(Message.session_id == sid)
            .order_by(Message.seq.desc())
            .limit(1)
        )
        or 0
    ) + 1
    db.add(Message(session_id=sid, seq=next_seq, role="agent", content=summary or ""))


async def get_history(db: AsyncSession, user_id: int, limit: int = 50) -> list[dict]:
    rows = (
        await db.execute(
            select(AnalysisSession, Message.content)
            .outerjoin(
                Message,
                and_(Message.session_id == AnalysisSession.id, Message.seq == 1),
            )
            .where(AnalysisSession.user_id == user_id)
            .order_by(AnalysisSession.created_at.desc(), AnalysisSession.id)
            .limit(limit)
        )
    ).all()
    return [
        {
            "session_id": str(sess.id),
            "message_preview": (content or "")[:50],
            "message_type": sess.message_type,
            "verdict": sess.verdict,
            "created_at": _fmt_dt(sess.created_at),
        }
        for sess, content in rows
    ]


async def get_session_detail(db: AsyncSession, session_id: str, user_id: int) -> dict | None:
    sid = _to_uuid(session_id)
    if sid is None:
        return None
    sess = await db.scalar(
        select(AnalysisSession)
        .where(AnalysisSession.id == sid, AnalysisSession.user_id == user_id)
        .options(
            selectinload(AnalysisSession.messages),
            selectinload(AnalysisSession.tool_calls),
        )
    )
    if not sess:
        return None

    user_msg = next((m for m in sess.messages if m.role == "user"), None)
    return {
        "session_id": str(sess.id),
        "message": user_msg.content if user_msg else "",
        "message_type": sess.message_type,
        "verdict": sess.verdict,
        "confidence": sess.confidence,
        "summary": sess.summary,
        "advice": sess.advice or [],
        "evidence": sess.evidence or [],
        "steps": [
            {
                "type": "step",
                "step_number": tc.step_number,
                "total_steps": tc.total_steps,
                "thought": tc.thought or "",
                "tool_name": tc.tool_name,
                "tool_input": tc.tool_input or {},
                "tool_output": tc.tool_output or {},
                "timestamp": _fmt_dt(tc.created_at),
            }
            for tc in sess.tool_calls
        ],
        "created_at": _fmt_dt(sess.created_at),
    }
