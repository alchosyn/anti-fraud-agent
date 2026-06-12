"""待处理分析会话的暂存区（analyze 写入 → WebSocket 取走，一次性消费）。

有 Redis 时存 Redis（TTL 10 分钟，跨 worker/跨实例可见——这是支持
uvicorn 多 worker 与水平扩容的前提）；无 Redis 回落到进程内 dict
（单 worker 开发模式够用）。
"""

from __future__ import annotations

import json

from .redis_client import get_redis

PENDING_TTL_S = 600

_local: dict[str, dict] = {}


def _key(session_id: str) -> str:
    return f"af:pending:{session_id}"


async def put_pending(session_id: str, payload: dict) -> None:
    r = get_redis()
    if r is not None:
        try:
            await r.set(_key(session_id), json.dumps(payload, ensure_ascii=False), ex=PENDING_TTL_S)
            return
        except Exception:
            pass
    _local[session_id] = payload


async def pop_pending(session_id: str) -> dict | None:
    r = get_redis()
    if r is not None:
        try:
            # GETDEL：原子取走，保证一次性消费（两个 WS 连同一 session 只有一个成功）
            raw = await r.getdel(_key(session_id))
            if raw:
                return json.loads(raw)
        except Exception:
            pass
    return _local.pop(session_id, None)
