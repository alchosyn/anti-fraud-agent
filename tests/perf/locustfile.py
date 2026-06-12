"""locust 混合场景压测。

用法（先起服务，压测建议关限流）：
    RATE_LIMIT_DISABLED=1 uvicorn backend.main:app --port 8000
    locust -f tests/perf/locustfile.py --host http://127.0.0.1:8000 \
           --users 50 --spawn-rate 10 --run-time 2m --headless

场景权重：历史查询（读多）> 健康检查 > 登录（CPU 密集）> 分析提交（写 + 缓存命中路径）。
analyze 固定消息文本：第二次起命中 Redis 结果缓存，压的是缓存读路径
（真实 agent 跑在 WS 里，不在本压测范围）。
"""

from __future__ import annotations

import uuid

from locust import HttpUser, between, task

PASSWORD = "locust-pass-123"
FIXED_MESSAGE = "【压测固定消息】您的快递已被海关扣留，点击 http://x.vip 缴纳关税"


class ApiUser(HttpUser):
    wait_time = between(0.2, 1.0)

    def on_start(self) -> None:
        self.username = f"locust-{uuid.uuid4().hex[:10]}"
        r = self.client.post("/api/register", json={
            "username": self.username, "password": PASSWORD,
        })
        if r.status_code == 429:
            raise RuntimeError("被限流：压测请设置 RATE_LIMIT_DISABLED=1")
        self.token = r.json()["access_token"]
        self.auth = {"Authorization": f"Bearer {self.token}"}

    @task(5)
    def history(self) -> None:
        self.client.get("/api/history", headers=self.auth)

    @task(3)
    def healthz(self) -> None:
        self.client.get("/api/healthz")

    @task(2)
    def login(self) -> None:
        self.client.post("/api/login", json={
            "username": self.username, "password": PASSWORD,
        })

    @task(1)
    def analyze_cached(self) -> None:
        self.client.post("/api/analyze", json={
            "message": FIXED_MESSAGE, "message_type": "sms",
        }, headers=self.auth)
