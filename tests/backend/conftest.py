"""后端测试基础设施。

- 数据库：临时文件 SQLite（DATABASE_URL 必须在 import backend.* 之前设好，
  因为 engine 在模块导入时创建）
- Redis：fakeredis 注入（services.redis_client.reset_for_tests）
- HTTP：httpx ASGITransport 直连 app，不起真实服务器
"""

from __future__ import annotations

import os
import sys
from pathlib import Path

_TMP_DB = Path(__file__).resolve().parent / ".tmp_test.db"
os.environ["DATABASE_URL"] = f"sqlite+aiosqlite:///{_TMP_DB}"
os.environ.pop("REDIS_URL", None)  # 真实 redis 不参与测试

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

import httpx  # noqa: E402
import pytest  # noqa: E402
from fakeredis import FakeAsyncRedis  # noqa: E402

from backend.db.database import engine, init_db  # noqa: E402
from backend.db.orm import Base  # noqa: E402
from backend.main import app  # noqa: E402
from backend.services.redis_client import reset_for_tests  # noqa: E402


@pytest.fixture(autouse=True)
async def _fresh_db():
    """每个测试一套干净的表 + 全新 fakeredis。"""
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.drop_all)
    await init_db()
    fake = FakeAsyncRedis(decode_responses=True)
    reset_for_tests(fake)
    yield
    await fake.flushall()
    reset_for_tests(None)


@pytest.fixture()
def fake_redis():
    """需要直接操作 redis 的测试用（_fresh_db 已注入，这里取同一实例）。"""
    from backend.services.redis_client import get_redis
    return get_redis()


@pytest.fixture()
async def client():
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as c:
        yield c


@pytest.fixture()
async def auth_client(client: httpx.AsyncClient):
    """已注册并带 token 的客户端。"""
    r = await client.post("/api/register", json={
        "username": "alice", "password": "secret123", "display_name": "Alice",
    })
    assert r.status_code == 200, r.text
    token = r.json()["access_token"]
    client.headers["Authorization"] = f"Bearer {token}"
    return client


def pytest_sessionfinish(session, exitstatus):
    try:
        _TMP_DB.unlink(missing_ok=True)
    except OSError:
        pass
