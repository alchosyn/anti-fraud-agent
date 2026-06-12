"""基于 Redis 的固定窗口限流（手写 INCR + EXPIRE，不依赖三方限流库）。

设计：
- key = af:rl:{scope}:{身份}:{窗口编号}，窗口编号 = 当前秒数 // 窗口长度，
  天然滚动过期；EXPIRE 仅做兜底清理
- 身份：by_user=True 时优先取 JWT 的 user_id（解不开退回 IP）；否则取客户端 IP
  （部署在 Nginx 后时取 X-Forwarded-For 第一跳）
- fail-open：Redis 未配置或不可用时放行（可用性优先于限流准确性）
- 超限返回 429 + Retry-After
"""

from __future__ import annotations

import os
import time

from fastapi import HTTPException, Request

from ..auth import decode_token
from .redis_client import get_redis

# 压测/演示时关闭限流：RATE_LIMIT_DISABLED=1
_DISABLED = os.getenv("RATE_LIMIT_DISABLED", "") == "1"


def _client_ip(request: Request) -> str:
    fwd = request.headers.get("x-forwarded-for")
    if fwd:
        return fwd.split(",")[0].strip()
    return request.client.host if request.client else "unknown"


def _identity(request: Request, by_user: bool) -> str:
    if by_user:
        auth = request.headers.get("authorization", "")
        if auth.lower().startswith("bearer "):
            try:
                payload = decode_token(auth[7:])
                return f"u{payload['user_id']}"
            except Exception:
                pass
    return f"ip:{_client_ip(request)}"


def rate_limit(scope: str, limit: int, window_s: int, by_user: bool = False):
    """返回一个 FastAPI 依赖。用法：dependencies=[Depends(rate_limit("login", 10, 60))]"""

    async def dependency(request: Request) -> None:
        if _DISABLED:
            return
        r = get_redis()
        if r is None:
            return
        window = int(time.time()) // window_s
        key = f"af:rl:{scope}:{_identity(request, by_user)}:{window}"
        try:
            count = await r.incr(key)
            if count == 1:
                await r.expire(key, window_s + 5)
        except Exception:
            return  # fail-open
        if count > limit:
            retry_after = window_s - int(time.time()) % window_s
            raise HTTPException(
                status_code=429,
                detail=f"Rate limit exceeded: {limit} requests per {window_s}s",
                headers={"Retry-After": str(retry_after)},
            )

    return dependency
