"""轻量 API 压测脚本（asyncio + httpx，无额外依赖）。

与 locust 的分工：本脚本用于快速的单端点对比测量（如优化前后 P95），
locust（tests/perf/locustfile.py）用于混合场景的持续压测。

用法：
    python scripts/ops/bench_api.py --url http://127.0.0.1:8765 --endpoint healthz -c 50 -d 15
    python scripts/ops/bench_api.py --endpoint login -c 50 -d 15      # 需先注册 bench 用户
    python scripts/ops/bench_api.py --endpoint history -c 50 -d 15
"""

from __future__ import annotations

import argparse
import asyncio
import statistics
import time

import httpx

BENCH_USER = {"username": "benchuser", "password": "bench-pass-123"}


async def ensure_user(base: str) -> str:
    async with httpx.AsyncClient(base_url=base, timeout=10) as c:
        r = await c.post("/api/register", json=BENCH_USER)
        if r.status_code not in (200, 409):
            raise SystemExit(f"register failed: {r.status_code} {r.text[:200]}")
        r = await c.post("/api/login", json=BENCH_USER)
        r.raise_for_status()
        return r.json()["access_token"]


def make_request_fn(endpoint: str, token: str):
    if endpoint == "healthz":
        return lambda c: c.get("/api/healthz")
    if endpoint == "login":
        return lambda c: c.post("/api/login", json=BENCH_USER)
    if endpoint == "history":
        headers = {"Authorization": f"Bearer {token}"}
        return lambda c: c.get("/api/history", headers=headers)
    raise SystemExit(f"unknown endpoint: {endpoint}")


async def worker(client, fn, deadline: float, latencies: list[float], errors: list[int]):
    while time.perf_counter() < deadline:
        t0 = time.perf_counter()
        try:
            r = await fn(client)
            latencies.append((time.perf_counter() - t0) * 1000)
            if r.status_code >= 400:
                errors.append(r.status_code)
        except Exception:
            errors.append(-1)


def pct(sorted_vals: list[float], p: float) -> float:
    if not sorted_vals:
        return 0.0
    idx = min(len(sorted_vals) - 1, int(p / 100 * (len(sorted_vals) - 1)))
    return sorted_vals[idx]


async def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--url", default="http://127.0.0.1:8765")
    parser.add_argument("--endpoint", default="healthz", choices=["healthz", "login", "history"])
    parser.add_argument("-c", "--concurrency", type=int, default=50)
    parser.add_argument("-d", "--duration", type=int, default=15)
    args = parser.parse_args()

    token = await ensure_user(args.url)
    fn = make_request_fn(args.endpoint, token)

    latencies: list[float] = []
    errors: list[int] = []
    limits = httpx.Limits(max_connections=args.concurrency, max_keepalive_connections=args.concurrency)
    async with httpx.AsyncClient(base_url=args.url, timeout=30, limits=limits) as client:
        # 预热
        for _ in range(3):
            await fn(client)
        deadline = time.perf_counter() + args.duration
        t_start = time.perf_counter()
        await asyncio.gather(*[
            worker(client, fn, deadline, latencies, errors)
            for _ in range(args.concurrency)
        ])
        elapsed = time.perf_counter() - t_start

    latencies.sort()
    n = len(latencies)
    print(f"endpoint={args.endpoint} concurrency={args.concurrency} duration={elapsed:.1f}s")
    print(f"requests={n}  errors={len(errors)}  QPS={n / elapsed:.1f}")
    if n:
        print(
            f"latency ms: p50={pct(latencies, 50):.1f}  p95={pct(latencies, 95):.1f}  "
            f"p99={pct(latencies, 99):.1f}  mean={statistics.mean(latencies):.1f}  max={latencies[-1]:.1f}"
        )


if __name__ == "__main__":
    asyncio.run(main())
