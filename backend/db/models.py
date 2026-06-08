from __future__ import annotations

import json
from .database import get_db


async def create_session(session_id: str, message: str, message_type: str) -> None:
    db = await get_db()
    try:
        await db.execute(
            "INSERT INTO sessions (session_id, message, message_type) VALUES (?, ?, ?)",
            (session_id, message, message_type),
        )
        await db.commit()
    finally:
        await db.close()


async def save_step(
    session_id: str,
    step_number: int,
    total_steps: int,
    thought: str,
    tool_name: str,
    tool_input: dict,
    tool_output: dict,
    timestamp: str,
) -> None:
    db = await get_db()
    try:
        await db.execute(
            """INSERT INTO steps
               (session_id, step_number, total_steps, thought, tool_name, tool_input, tool_output, timestamp)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
            (
                session_id,
                step_number,
                total_steps,
                thought,
                tool_name,
                json.dumps(tool_input, ensure_ascii=False),
                json.dumps(tool_output, ensure_ascii=False),
                timestamp,
            ),
        )
        await db.commit()
    finally:
        await db.close()


async def save_result(
    session_id: str,
    verdict: str,
    confidence: float,
    summary: str,
    advice: list[str],
) -> None:
    db = await get_db()
    try:
        await db.execute(
            """UPDATE sessions
               SET verdict = ?, confidence = ?, summary = ?, advice = ?
               WHERE session_id = ?""",
            (verdict, confidence, summary, json.dumps(advice, ensure_ascii=False), session_id),
        )
        await db.commit()
    finally:
        await db.close()


async def get_history(limit: int = 50) -> list[dict]:
    db = await get_db()
    try:
        cursor = await db.execute(
            """SELECT session_id, message, message_type, verdict, created_at
               FROM sessions ORDER BY created_at DESC LIMIT ?""",
            (limit,),
        )
        rows = await cursor.fetchall()
        return [
            {
                "session_id": r["session_id"],
                "message_preview": r["message"][:50],
                "message_type": r["message_type"],
                "verdict": r["verdict"],
                "created_at": r["created_at"],
            }
            for r in rows
        ]
    finally:
        await db.close()


async def get_session_detail(session_id: str) -> dict | None:
    db = await get_db()
    try:
        cursor = await db.execute(
            "SELECT * FROM sessions WHERE session_id = ?", (session_id,)
        )
        session = await cursor.fetchone()
        if not session:
            return None

        cursor = await db.execute(
            "SELECT * FROM steps WHERE session_id = ? ORDER BY step_number",
            (session_id,),
        )
        steps = await cursor.fetchall()

        advice_raw = session["advice"]
        advice = json.loads(advice_raw) if advice_raw else []

        return {
            "session_id": session["session_id"],
            "message": session["message"],
            "message_type": session["message_type"],
            "verdict": session["verdict"],
            "confidence": session["confidence"],
            "summary": session["summary"],
            "advice": advice,
            "steps": [
                {
                    "type": "step",
                    "step_number": s["step_number"],
                    "total_steps": s["total_steps"],
                    "thought": s["thought"],
                    "tool_name": s["tool_name"],
                    "tool_input": json.loads(s["tool_input"]) if s["tool_input"] else {},
                    "tool_output": json.loads(s["tool_output"]) if s["tool_output"] else {},
                    "timestamp": s["timestamp"],
                }
                for s in steps
            ],
            "created_at": session["created_at"],
        }
    finally:
        await db.close()
