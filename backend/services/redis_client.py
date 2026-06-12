"""Redis 异步客户端（单例）。

未配置 REDIS_URL 或连接失败时返回 None——上层（缓存/限流）一律按
「fail-open」降级：缓存不命中、限流放行。保证本地无 Docker 也能开发。
"""

from __future__ import annotations

import os

from redis.asyncio import Redis

REDIS_URL = os.getenv("REDIS_URL", "")

_redis: Redis | None = None
_warned = False


def get_redis() -> Redis | None:
    global _redis, _warned
    if _redis is not None:  # 已初始化或测试注入
        return _redis
    if not REDIS_URL:
        if not _warned:
            print("[redis] REDIS_URL 未配置，缓存与限流降级为 no-op")
            _warned = True
        return None
    _redis = Redis.from_url(
        REDIS_URL,
        decode_responses=True,
        socket_connect_timeout=2,
        socket_timeout=2,
    )
    return _redis


async def close_redis() -> None:
    global _redis
    if _redis is not None:
        await _redis.aclose()
        _redis = None


def reset_for_tests(client: Redis | None) -> None:
    """单测注入 fakeredis 用。"""
    global _redis, _warned
    _redis = client
    _warned = False
