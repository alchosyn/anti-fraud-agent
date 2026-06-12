"""Redis 缓存层。

两级缓存（均 fail-open，Redis 不可用时静默跳过）：
1. 分析结果缓存：同一条消息（message_type + 内容哈希）的完整分析结论。
   命中时跳过整个 agent ReAct 循环——这是省 LLM 成本与延迟的大头。
   仅缓存无对话历史的首轮分析（带历史的结果依赖上下文，不可复用）。
2. 工具结果缓存：search_knowledge / risk_score 按输入哈希缓存，
   供 agent 循环内部复用（search_knowledge 内含一次 LLM query 改写调用）。
"""

from __future__ import annotations

import hashlib
import json

from .redis_client import get_redis

ANALYSIS_TTL_S = 60 * 60        # 分析结果 1 小时
TOOL_TTL_S = 24 * 60 * 60       # 工具结果 24 小时（知识库/规则基本静态）


def _h(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()[:32]


def analysis_key(message_type: str, message: str) -> str:
    return f"af:analysis:{message_type}:{_h(message)}"


def tool_key(tool_name: str, payload: str) -> str:
    return f"af:tool:{tool_name}:{_h(payload)}"


async def get_cached_analysis(message_type: str, message: str) -> dict | None:
    r = get_redis()
    if r is None:
        return None
    try:
        raw = await r.get(analysis_key(message_type, message))
        return json.loads(raw) if raw else None
    except Exception:
        return None


async def set_cached_analysis(message_type: str, message: str, result: dict) -> None:
    r = get_redis()
    if r is None:
        return
    try:
        await r.set(
            analysis_key(message_type, message),
            json.dumps(result, ensure_ascii=False),
            ex=ANALYSIS_TTL_S,
        )
    except Exception:
        pass


async def get_cached_tool(tool_name: str, payload: str) -> str | None:
    r = get_redis()
    if r is None:
        return None
    try:
        return await r.get(tool_key(tool_name, payload))
    except Exception:
        return None


async def set_cached_tool(tool_name: str, payload: str, output: str) -> None:
    r = get_redis()
    if r is None:
        return
    try:
        await r.set(tool_key(tool_name, payload), output, ex=TOOL_TTL_S)
    except Exception:
        pass
