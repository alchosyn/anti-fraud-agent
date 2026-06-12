"""限流测试（fakeredis）。"""

from __future__ import annotations

import httpx

from backend.services.redis_client import reset_for_tests


async def test_login_rate_limited(client: httpx.AsyncClient):
    """login 限 10 次/60s：第 11 次 429 + Retry-After。"""
    payload = {"username": "nobody", "password": "whatever1"}
    statuses = []
    for _ in range(11):
        r = await client.post("/api/login", json=payload)
        statuses.append(r.status_code)
    assert statuses[:10] == [401] * 10  # 未注册 → 401，但都计入窗口
    assert statuses[10] == 429
    assert "Retry-After" in r.headers
    assert "Rate limit" in r.json()["detail"]


async def test_register_rate_limited(client: httpx.AsyncClient):
    """register 限 5 次/300s。"""
    for i in range(5):
        await client.post("/api/register", json={
            "username": f"user{i}", "password": "secret123",
        })
    r = await client.post("/api/register", json={
        "username": "user-last", "password": "secret123",
    })
    assert r.status_code == 429


async def test_analyze_limited_per_user(auth_client: httpx.AsyncClient):
    """analyze 按 user_id 限 30 次/小时。"""
    last = None
    for _ in range(31):
        last = await auth_client.post("/api/analyze", json={"message": "限流测试消息"})
    assert last.status_code == 429


async def test_fail_open_without_redis(client: httpx.AsyncClient):
    """Redis 不可用 → 放行（可用性优先）。"""
    reset_for_tests(None)  # conftest 注入的 fakeredis 撤掉，REDIS_URL 也为空
    for _ in range(15):
        r = await client.post("/api/login", json={"username": "x2", "password": "whatever1"})
    assert r.status_code == 401  # 一直 401（密码错），永远不该 429
