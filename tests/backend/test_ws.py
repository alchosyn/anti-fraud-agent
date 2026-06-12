"""WebSocket 流式链路测试：agent 用假生成器替身（不调 LLM）。

覆盖：完整流（step → result → 落库）、缓存命中短路、未授权拒绝、
重复消费 session 拒绝。
"""

from __future__ import annotations

import pytest
from starlette.testclient import TestClient

import backend.api.websocket as ws_module
from backend.main import app

FAKE_STEP = {
    "type": "step", "step_number": 1, "total_steps": 6,
    "thought": "先打个分", "tool_name": "risk_score",
    "tool_input": {"scenario": "x"}, "tool_output": {"score": 85},
    "cached": False, "timestamp": "2026-06-12T00:00:00+00:00",
}
FAKE_RESULT = {
    "type": "result", "verdict": "high_risk", "confidence": 0.9,
    "summary": "一眼假", "advice": ["别点链接", "打96110"],
    "evidence": [{"source": "risk_score", "finding": "85分"}],
}


async def fake_run_agent(message, message_type, history=None):
    yield dict(FAKE_STEP)
    yield dict(FAKE_RESULT)


@pytest.fixture()
def ws_client(monkeypatch):
    monkeypatch.setattr(ws_module, "run_agent", fake_run_agent)
    with TestClient(app) as c:
        yield c


def _register_and_token(c: TestClient) -> str:
    r = c.post("/api/register", json={"username": "wsuser", "password": "secret123"})
    assert r.status_code == 200, r.text
    return r.json()["access_token"]


def test_ws_stream_and_persist(ws_client: TestClient):
    token = _register_and_token(ws_client)
    h = {"Authorization": f"Bearer {token}"}

    r = ws_client.post("/api/analyze", json={"message": "可疑短信原文"}, headers=h)
    sid = r.json()["session_id"]
    assert r.json()["status"] == "processing"

    with ws_client.websocket_connect(f"/api/ws/{sid}?token={token}") as ws:
        first = ws.receive_json()
        assert first["type"] == "step" and first["tool_name"] == "risk_score"
        second = ws.receive_json()
        assert second["type"] == "result" and second["verdict"] == "high_risk"

    # 落库验证（走 REST 读回）
    detail = ws_client.get(f"/api/history/{sid}", headers=h).json()
    assert detail["verdict"] == "high_risk"
    assert detail["summary"] == "一眼假"
    assert detail["advice"] == ["别点链接", "打96110"]
    assert detail["evidence"][0]["finding"] == "85分"
    assert len(detail["steps"]) == 1
    assert detail["steps"][0]["tool_output"]["score"] == 85


def test_ws_cache_hit_short_circuit(ws_client: TestClient):
    """同一条消息第二次分析：status=cached，WS 直接回结果（无 step）。"""
    token = _register_and_token(ws_client)
    h = {"Authorization": f"Bearer {token}"}
    msg = {"message": "重复提交的同一条诈骗短信", "message_type": "sms"}

    # 第一轮：完整跑（写入缓存）
    sid1 = ws_client.post("/api/analyze", json=msg, headers=h).json()["session_id"]
    with ws_client.websocket_connect(f"/api/ws/{sid1}?token={token}") as ws:
        assert ws.receive_json()["type"] == "step"
        assert ws.receive_json()["type"] == "result"

    # 第二轮：缓存命中
    r = ws_client.post("/api/analyze", json=msg, headers=h)
    assert r.json()["status"] == "cached"
    sid2 = r.json()["session_id"]
    with ws_client.websocket_connect(f"/api/ws/{sid2}?token={token}") as ws:
        first = ws.receive_json()
        assert first["type"] == "result"
        assert first["cached"] is True
        assert first["verdict"] == "high_risk"

    # 缓存命中的会话同样落库
    detail = ws_client.get(f"/api/history/{sid2}", headers=h).json()
    assert detail["verdict"] == "high_risk"
    assert detail["steps"] == []


def test_ws_rejects_bad_token(ws_client: TestClient):
    token = _register_and_token(ws_client)
    h = {"Authorization": f"Bearer {token}"}
    sid = ws_client.post("/api/analyze", json={"message": "x"}, headers=h).json()["session_id"]

    from starlette.websockets import WebSocketDisconnect
    with pytest.raises(WebSocketDisconnect):
        with ws_client.websocket_connect(f"/api/ws/{sid}?token=garbage") as ws:
            ws.receive_json()


def test_ws_session_consumed_once(ws_client: TestClient):
    token = _register_and_token(ws_client)
    h = {"Authorization": f"Bearer {token}"}
    sid = ws_client.post("/api/analyze", json={"message": "只许一次"}, headers=h).json()["session_id"]

    with ws_client.websocket_connect(f"/api/ws/{sid}?token={token}") as ws:
        ws.receive_json()
        ws.receive_json()

    with ws_client.websocket_connect(f"/api/ws/{sid}?token={token}") as ws:
        msg = ws.receive_json()
        assert msg["type"] == "error"
