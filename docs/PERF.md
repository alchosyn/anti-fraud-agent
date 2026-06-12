# 性能压测记录

## 测试环境（口径声明）

- 2026-06-12，Windows 11 本机，uvicorn 单 worker
- 存储：SQLite（NullPool）+ 进程内无 Redis（限流关闭 `RATE_LIMIT_DISABLED=1`）
- 工具：`scripts/ops/bench_api.py`（asyncio + httpx，50 并发，15s/10s）
- 该口径偏保守：生产编排（PostgreSQL 连接池 + Redis + Linux）下读路径应更好。
  复现真实栈口径：`docker compose up -d` 后用 locust 跑 `tests/perf/locustfile.py`

## 瓶颈定位与优化：同步 bcrypt 阻塞事件循环

`POST /api/login` 中 `bcrypt.checkpw`（约 200ms CPU 密集）原本直接在 async
handler 里同步执行——每个登录请求都会把整个事件循环挂住 200ms，并发一上来
所有请求（包括其他端点）排队。

**修复**（[backend/api/routes.py](../backend/api/routes.py)）：
`await asyncio.to_thread(verify_password, ...)` 把 bcrypt 丢进线程池。
bcrypt 的 C 实现会释放 GIL，多核真正并行；事件循环只负责调度。

### Before / After（login，50 并发）

| 指标 | 修复前（同步） | 修复后（to_thread） | 变化 |
|---|---|---|---|
| QPS | 5.0 | **62.3** | **×12.5** |
| P50 | 8,626 ms | 776 ms | −91.0% |
| P95 | 16,138 ms | **1,036 ms** | **−93.6%** |
| P99 | 18,434 ms | 1,246 ms | −93.2% |
| 错误数 | 0 | 0 | — |

修复后的延迟构成基本就是 bcrypt 本身的计算时间 × 线程池排队深度，
事件循环不再被独占——同机伴随测量的 `/api/healthz` 不受登录洪峰拖累。

### 其他端点基线（同口径，修复后）

| 端点 | 并发 | QPS | P50 | P95 | P99 |
|---|---|---|---|---|---|
| GET /api/healthz | 50 | 922.4 | 38 ms | 155 ms | 235 ms |
| GET /api/history（带 JWT + DB 查询） | 50 | 278.1 | 113 ms | 514 ms | 802 ms |
| POST /api/login（bcrypt） | 50 | 62.3 | 776 ms | 1,036 ms | 1,246 ms |

## 相关架构改动（支撑水平扩展）

1. **待处理会话从进程内 dict 挪到 Redis**（`backend/services/pending.py`，
   GETDEL 原子一次性消费）——`/api/analyze` 与 WebSocket 可以落在不同
   worker/实例上，uvicorn 多 worker 与多副本部署成为可能。
2. **分析结果 Redis 缓存**：同一消息重复提交直接回缓存结论，跳过整个
   agent ReAct 循环（单次约 6.7s P50 / 3k tokens，见 evals/reports/benchmark_report.md
   的 agent 行）→ 缓存命中时为毫秒级 DB+Redis 读。
3. **WS 推送前先落库**：客户端收到的每条消息都已持久化，断线不丢进度。

## 复现

```powershell
# 修复前后对比（单端点）
$env:RATE_LIMIT_DISABLED="1"; uvicorn backend.main:app --port 8765 --log-level error
python scripts/ops/bench_api.py --endpoint login -c 50 -d 15

# 混合场景（需 pip install locust）
locust -f tests/perf/locustfile.py --host http://127.0.0.1:8000 `
       --users 50 --spawn-rate 10 --run-time 2m --headless
```
