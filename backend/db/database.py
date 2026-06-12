"""数据库引擎与会话管理（SQLAlchemy 2.0 async）。

- 生产：PostgreSQL（asyncpg 驱动），由 DATABASE_URL 注入，连接池 10+20、pool_pre_ping
- 本地无 Docker 开发 / 单元测试：自动回落 SQLite（aiosqlite），同一套 ORM 代码不变
- 表结构由 ORM create_all 建立；线上演进应迁移到 Alembic（见 DEPLOY.md TODO）
"""

from __future__ import annotations

import os
from collections.abc import AsyncGenerator
from pathlib import Path

from sqlalchemy.ext.asyncio import (
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)

from .orm import Base

_DEFAULT_SQLITE = f"sqlite+aiosqlite:///{Path(__file__).resolve().parent / 'anti_fraud.db'}"

DATABASE_URL = os.getenv("DATABASE_URL", _DEFAULT_SQLITE)

_engine_kwargs: dict = {"echo": False}
if DATABASE_URL.startswith("postgresql"):
    _engine_kwargs.update(pool_size=10, max_overflow=20, pool_pre_ping=True)
else:
    # SQLite（开发/测试）：不复用连接。跨事件循环复用 aiosqlite 连接会报
    # "attached to a different loop"（测试里 pytest-asyncio 与 TestClient 各有循环）
    from sqlalchemy.pool import NullPool
    _engine_kwargs.update(poolclass=NullPool)

engine = create_async_engine(DATABASE_URL, **_engine_kwargs)

SessionLocal = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)


async def get_session() -> AsyncGenerator[AsyncSession, None]:
    """FastAPI 依赖：每个请求一个 ORM 会话，异常自动回滚。"""
    async with SessionLocal() as session:
        try:
            yield session
            await session.commit()
        except Exception:
            await session.rollback()
            raise


async def init_db() -> None:
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    await _seed_default_user()


async def _seed_default_user() -> None:
    """演示账号 admin / admin123（已存在则跳过）。"""
    from sqlalchemy import select

    from ..auth import hash_password
    from .orm import User

    async with SessionLocal() as session:
        existing = await session.scalar(select(User).where(User.username == "admin"))
        if existing:
            return
        session.add(User(username="admin", display_name="Admin",
                         hashed_password=hash_password("admin123")))
        await session.commit()
        print("[db] Default account created: admin / admin123")


async def dispose_engine() -> None:
    await engine.dispose()
