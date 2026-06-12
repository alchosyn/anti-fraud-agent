"""缓存与待处理会话暂存测试（fakeredis）。"""

from __future__ import annotations

from backend.services.cache import (
    get_cached_analysis,
    get_cached_tool,
    set_cached_analysis,
    set_cached_tool,
)
from backend.services.pending import pop_pending, put_pending
from backend.services.redis_client import reset_for_tests


async def test_analysis_cache_roundtrip():
    result = {"type": "result", "verdict": "high_risk", "summary": "假的", "advice": ["别点"]}
    assert await get_cached_analysis("sms", "短信原文") is None
    await set_cached_analysis("sms", "短信原文", result)
    assert await get_cached_analysis("sms", "短信原文") == result
    # 不同 message_type / 内容不串 key
    assert await get_cached_analysis("email", "短信原文") is None
    assert await get_cached_analysis("sms", "别的内容") is None


async def test_analysis_cache_ttl_set(fake_redis):
    await set_cached_analysis("sms", "x", {"a": 1})
    from backend.services.cache import analysis_key
    ttl = await fake_redis.ttl(analysis_key("sms", "x"))
    assert 0 < ttl <= 3600


async def test_tool_cache_roundtrip():
    assert await get_cached_tool("risk_score", '{"scenario":"y"}') is None
    await set_cached_tool("risk_score", '{"scenario":"y"}', '{"score": 30}')
    assert await get_cached_tool("risk_score", '{"scenario":"y"}') == '{"score": 30}'


async def test_cache_degrades_without_redis():
    reset_for_tests(None)
    await set_cached_analysis("sms", "x", {"a": 1})   # 不抛异常
    assert await get_cached_analysis("sms", "x") is None


async def test_pending_one_shot():
    """暂存只能被取走一次（GETDEL 原子性）。"""
    await put_pending("sid-1", {"message": "m", "history": []})
    assert (await pop_pending("sid-1"))["message"] == "m"
    assert await pop_pending("sid-1") is None


async def test_pending_local_fallback():
    reset_for_tests(None)
    await put_pending("sid-2", {"message": "local"})
    assert (await pop_pending("sid-2"))["message"] == "local"
    assert await pop_pending("sid-2") is None
