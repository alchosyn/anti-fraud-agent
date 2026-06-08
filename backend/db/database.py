from __future__ import annotations

import aiosqlite
from pathlib import Path

DB_PATH = Path(__file__).resolve().parent / "anti_fraud.db"

_SCHEMA = """
CREATE TABLE IF NOT EXISTS sessions (
    session_id TEXT PRIMARY KEY,
    message    TEXT NOT NULL,
    message_type TEXT NOT NULL DEFAULT 'sms',
    verdict    TEXT,
    confidence REAL,
    summary    TEXT,
    advice     TEXT,
    created_at DATETIME DEFAULT (datetime('now'))
);

CREATE TABLE IF NOT EXISTS steps (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    session_id  TEXT NOT NULL REFERENCES sessions(session_id),
    step_number INTEGER NOT NULL,
    total_steps INTEGER NOT NULL DEFAULT 0,
    thought     TEXT,
    tool_name   TEXT,
    tool_input  TEXT,
    tool_output TEXT,
    timestamp   DATETIME DEFAULT (datetime('now'))
);
"""


async def get_db() -> aiosqlite.Connection:
    db = await aiosqlite.connect(str(DB_PATH))
    db.row_factory = aiosqlite.Row
    await db.execute("PRAGMA journal_mode=WAL")
    return db


async def init_db() -> None:
    db = await get_db()
    try:
        await db.executescript(_SCHEMA)
        await db.commit()
    finally:
        await db.close()
