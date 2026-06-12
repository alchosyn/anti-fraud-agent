"""REST API 集成测试（ASGI 直连，零网络）。"""

from __future__ import annotations

import uuid

import httpx


async def test_healthz(client: httpx.AsyncClient):
    r = await client.get("/api/healthz")
    assert r.status_code == 200
    assert r.json() == {"status": "ok"}


async def test_register_login_flow(client: httpx.AsyncClient):
    r = await client.post("/api/register", json={
        "username": "bob", "password": "secret123", "display_name": "鲍勃",
    })
    assert r.status_code == 200
    body = r.json()
    assert body["user"]["username"] == "bob"
    assert body["user"]["display_name"] == "鲍勃"
    assert body["access_token"]

    r = await client.post("/api/login", json={"username": "bob", "password": "secret123"})
    assert r.status_code == 200

    r = await client.post("/api/login", json={"username": "bob", "password": "wrong-pass"})
    assert r.status_code == 401


async def test_register_validation(client: httpx.AsyncClient):
    r = await client.post("/api/register", json={"username": "x", "password": "secret123"})
    assert r.status_code == 400  # 用户名过短
    r = await client.post("/api/register", json={"username": "okname", "password": "123"})
    assert r.status_code == 400  # 密码过短


async def test_register_duplicate(client: httpx.AsyncClient):
    payload = {"username": "dup", "password": "secret123"}
    assert (await client.post("/api/register", json=payload)).status_code == 200
    assert (await client.post("/api/register", json=payload)).status_code == 409


async def test_protected_routes_require_token(client: httpx.AsyncClient):
    assert (await client.get("/api/history")).status_code in (401, 403)
    assert (
        await client.post("/api/analyze", json={"message": "测试"})
    ).status_code in (401, 403)


async def test_analyze_and_history(auth_client: httpx.AsyncClient):
    r = await auth_client.post("/api/analyze", json={
        "message": "您的包裹被扣留，点击 http://x.vip 缴费",
        "message_type": "sms",
    })
    assert r.status_code == 200
    sid = r.json()["session_id"]
    assert r.json()["status"] == "processing"
    uuid.UUID(sid)  # 合法 UUID

    r = await auth_client.get("/api/history")
    assert r.status_code == 200
    records = r.json()["records"]
    assert len(records) == 1
    assert records[0]["session_id"] == sid
    assert "包裹被扣留" in records[0]["message_preview"]

    # 详情：分析未完成时 verdict 为空，但 message 应在
    r = await auth_client.get(f"/api/history/{sid}")
    assert r.status_code == 200
    assert r.json()["message"].startswith("您的包裹")
    assert r.json()["verdict"] is None


async def test_session_detail_isolated_per_user(auth_client: httpx.AsyncClient):
    r = await auth_client.post("/api/analyze", json={"message": "测试消息隔离"})
    sid = r.json()["session_id"]

    # 另一个用户拿不到 alice 的会话
    r = await auth_client.post("/api/register", json={
        "username": "mallory", "password": "secret123",
    })
    other_token = r.json()["access_token"]
    r = await auth_client.get(
        f"/api/history/{sid}", headers={"Authorization": f"Bearer {other_token}"}
    )
    assert r.status_code == 404


async def test_session_detail_bad_id(auth_client: httpx.AsyncClient):
    assert (await auth_client.get("/api/history/not-a-uuid")).status_code == 404
    assert (await auth_client.get(f"/api/history/{uuid.uuid4()}")).status_code == 404
