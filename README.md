# XinZao · Anti-Fraud Dialogue Agent

LLM-powered anti-fraud assistant. Users paste a suspicious message, and the agent identifies scam patterns, explains the attack, and gives actionable advice.

## Architecture

```
User Input
  │
  ▼
┌──────────────────────────────────────────────────┐
│  input_guard                                     │
│  Prompt injection detection (role override,      │
│  fake system messages, prompt leak probing)       │
└──────────────┬───────────────────────────────────┘
               │ pass
               ▼
┌──────────────────────────────────────────────────┐
│  ReAct Agent Loop  (max 6 steps)                 │
│                                                  │
│  ┌────────────┐  ┌─────────────┐  ┌───────────┐ │
│  │ risk_score  │  │ search_kb   │  │web_search │ │
│  │ 13 regex +  │  │ BM25, 55    │  │ Tavily    │ │
│  │ URL spoof   │  │ entries     │  │ live      │ │
│  └────────────┘  └─────────────┘  └───────────┘ │
│  ┌────────────┐  ┌─────────────┐                 │
│  │ calculator  │  │ get_time    │    Memory       │
│  │ entropy     │  │ recency     │    (multi-turn) │
│  └────────────┘  └─────────────┘                 │
└──────────────┬───────────────────────────────────┘
               │
               ▼
┌──────────────────────────────────────────────────┐
│  Langfuse Trace                                  │
│  token count / latency / tool calls per step     │
└──────────────────────────────────────────────────┘
               │
               ▼
           Response
```

| Layer | Stack |
|---|---|
| LLM | DeepSeek-V3 (OpenAI-compatible API) |
| Embedding | paraphrase-multilingual-MiniLM-L12-v2 |
| Retrieval | Hybrid BM25 + vector, LLM query rewriting |
| Web Search | Tavily |
| Evaluation | Public-dataset P/R/F1 + rule checks + pinned LLM-as-Judge + ablations |
| Backend | FastAPI (async) + SQLAlchemy 2.0 + PostgreSQL (SQLite fallback for dev) |
| Cache / Limits | Redis: analysis & tool result cache, fixed-window rate limiting |
| Delivery | Docker Compose (app+db+redis), Nginx+TLS deploy kit, GitHub Actions CI |

## SFT Fine-tuning

50 hand-written seed examples, distilled via DeepSeek to 220 training samples. Qwen2.5-1.5B + LoRA (rank 16), trained on Kaggle T4.

Script: `scripts/train_lora.py`. Unsloth accelerated, auto-fallback to native transformers + peft if Unsloth is unavailable.

## GRPO Post-training

GRPO (same RL algorithm as DeepSeek-R1) on top of the SFT LoRA adapter, with RLAIF-style hybrid reward.

### Reward Design

| Component | Description | Score |
|---|---|---|
| R1 Answer quality | LLM-as-judge via DeepSeek API, overall × 0.6 | 0~3 |
| R2 Step structure | Regex match for inline 1.2.3. steps | +0.5 |
| R3 Real hotline | Contains 96110 / 110 / 12321 etc. | +0.5 |
| P1 Fake hotline | Contains non-existent numbers like 95110 | -1 |
| P2 Too brief | Urgent scenario but reply under 50 chars | -0.5 |
| P3 AI-speak | Markdown lists / emoji bullets / excessive bold | -0.5 |
| P4 Too long | Over 400 characters | -0.5 |

P3 and P4 counteract LLM-judge structure-bias. The judge naturally prefers markdown-heavy long responses. Without these penalties, GRPO would overfit to the judge and destroy the natural tone that SFT learned.

### Training Config

- Warm-start from SFT LoRA adapter
- 65 prompts, 4 generations/prompt, 2 epochs, 520 rollouts total
- ~30 min on Colab T4, DeepSeek API cost under $1
- Script: `scripts/train_grpo.py`, notebook: `notebooks/train_grpo_colab.ipynb`

## Evaluation Results

15 anti-fraud scenarios, 5-way comparison, LLM-as-Judge scoring (out of 5):

| Strategy | overall | accuracy | actionability | citation | tone |
|---|---:|---:|---:|---:|---:|
| deepseek-agent (RAG + tools + guard) | **4.63** | 5.00 | 5.00 | 3.53 | 5.00 |
| deepseek-base (LLM only) | 4.03 | 5.00 | 5.00 | 2.07 | 4.07 |
| qwen-grpo (SFT + GRPO) | 3.63 | 4.40 | 4.40 | 1.80 | 3.93 |
| qwen-lora (SFT) | 3.63 | 4.40 | 4.67 | 1.60 | 3.87 |
| qwen-base (vanilla 1.5B) | 3.35 | 4.20 | 4.20 | 2.00 | 3.00 |

### Per-layer Improvement

| Operation | Δ overall | Key changes |
|---|---:|---|
| SFT | +0.28 | tone +0.87 |
| GRPO | +0.00 | citation +0.20, tone +0.06, actionability -0.27 |
| RAG + Agent | +0.60 | citation +1.46, tone +0.93 |

SFT's biggest gain is in tone. Style transfer is where small-data fine-tuning pays off the most. GRPO improved citation and tone slightly, but the training set (65 prompts × 2 epochs) was too small to move the needle on overall. Citation can only be meaningfully improved by RAG. Both SFT and GRPO plateau at 1.6~1.8 while the RAG agent reaches 3.53.

Full per-case report: `evals/compare_report.md`

## Objective Benchmark on Public Data

LLM-judge scores on self-written cases can't answer "does it generalize?" — so the agent
is also measured with hard labels on a public dataset:
[hrwhisper/SpamMessage](https://github.com/hrwhisper/SpamMessage) (~800k labeled Chinese SMS,
stratified sample, seed=42, dev/test split discipline for threshold tuning).
Task: should this SMS be intercepted (ads/fraud/phishing) or released.

| System (n=500) | Precision | Recall | F1 | FPR | p50 latency | ¥/1k msgs |
|---|---:|---:|---:|---:|---:|---:|
| risk_score rule engine | 0.250 | 0.012 | 0.023 | 3.6% | ~0 ms | 0 |
| deepseek single-shot (no tools) | 0.669 | **0.904** | **0.769** | 44.8% | 2.1 s | 1.68 |
| deepseek agent (risk_score + RAG) | **0.817** | 0.428 | 0.562 | **9.6%** | 6.7 s | 7.92 |

Three honest findings (full report: `evals/benchmark_report.md`):

1. **The fraud rule engine is near-random out of domain** (ROC-AUC 0.49): its regexes
   target fraud signals, not generic ad spam — and the dataset masks digits (`x`),
   killing `\d`-based patterns.
2. **Tool anchoring flips the precision/recall trade-off.** The bare LLM intercepts
   aggressively (90% recall, but flags 45% of *legitimate* messages). The agent trusts
   its fraud-tuned risk_score tool ("0 signals → release"), cutting false alarms 4.7×
   (FPR 44.8% → 9.6%) at the cost of missing ad spam.
3. **Instruction drift under tool bias, caught verbatim**: in one logged reply the agent
   *rewrote its own task* — "广告推销本身不在拦截清单里" — directly contradicting the
   prompt, because the anti-fraud persona + tool output overrode the task definition.

Reproduce: `python scripts/fetch_benchmark_data.py && python evals/benchmark_public.py
--systems risk_score single_shot agent` (committed sample: `evals/data/spam_sample_v1.jsonl`).

## Ablations (in-domain, 80-case eval set v2)

Eval set v2 (`evals/cases_v2.json`): 80 reviewed cases — 52 fraud across 15+ patterns,
13 hard negatives (legitimate messages that *look* suspicious — measures false alarms),
5 borderline, 9 off-topic/injection probes. Tool subsets via `step(active_tools=...)`,
judge pinned to `gpt-4o-mini-2024-07-18`, temperature 0, long-memory injection disabled
(a real contamination bug found & fixed: private cross-session memory used to leak into
every eval run).

Full agent on v2: **92.5% rule pass (74/80), judge 4.42/5** (accuracy 4.72 /
actionability 4.67 / citation 3.42 / tone 4.86), rule-vs-judge Spearman ρ = 0.51.
Full report: `evals/report_v2.md`.

| Variant | content pass | judge overall | citation | hard-neg pass | latency |
|---|---:|---:|---:|---:|---:|
| full agent | **97.5%** | **4.49** | 3.62 | 92.3% | 10.3 s |
| − RAG (no search_knowledge) | 92.5% | 4.34 | 3.20 | 92.3% | 9.4 s |
| − web_search | 90.0% | 4.31 | 3.05 | 92.3% | 8.6 s |
| − all tools | 72.5% | 3.16 | **1.68** | **61.5%** | 1.9 s |

Takeaways: tools account for a **25-point content-pass gap** and most of the
citation score (3.62 → 1.68 without them). The hard-negative column is the
mirror image of the public-benchmark finding: with the rule tool present, its
"0 signals" output keeps the agent calm on legitimate-but-suspicious-looking
messages (92.3% pass); strip the tools and false alarms triple (61.5%) — the
same anchoring mechanism that costs recall on out-of-domain ad spam *buys*
false-alarm resistance in-domain.

## Backend & Infrastructure

Full-stack web app (FastAPI + React) around the agent, built like a production service:

- **Database**: SQLAlchemy 2.0 async ORM on PostgreSQL (asyncpg), 4-table schema —
  `users` / `sessions` / `messages` / `tool_calls` — FKs with cascade, JSONB columns
  (auto-degrades to JSON on the SQLite dev fallback), composite index on
  `(user_id, created_at)` for the history path. `backend/db/orm.py`
- **Redis** (all fail-open when absent):
  - analysis-result cache — re-submitting the same message skips the whole ReAct loop
    (≈6.7 s p50 + ~3k tokens → milliseconds)
  - tool-result cache for `search_knowledge` / `risk_score` (24h TTL)
  - hand-rolled fixed-window rate limiter (INCR+EXPIRE): login 10/min/IP,
    register 5/5min/IP, analyze 30/h/user, 429 + Retry-After
  - pending-session handoff via atomic GETDEL — analyze and WebSocket may land on
    different workers, enabling multi-worker / horizontal scaling
- **Crash consistency**: WS persists each step *before* pushing it — whatever the
  client saw is already in the DB.
- **Performance** (`docs/PERF.md`): sync bcrypt was serializing the event loop —
  `asyncio.to_thread` fix took login @50 concurrency from **5.0 → 62.3 QPS (×12.5)**,
  p95 **16.1 s → 1.04 s (−93.6%)**; history reads 278 QPS / p95 514 ms (local profile).
- **Tests & CI**: 28 backend tests (auth/API/rate-limit/cache/WS-stream, fakeredis +
  in-memory ASGI) + 23 offline eval tests; 2-job GitHub Actions matrix.
- **Delivery**: 3-service Docker Compose (app+postgres+redis, healthchecks, CPU-torch
  image with pre-baked embedding model); Nginx + Let's Encrypt VPS kit in `deploy/`.

## Quick Start

```bash
git clone https://github.com/alchosyn/npc-dialogue-ai-agent.git
cd npc-dialogue-ai-agent

# .env
echo "DEEPSEEK_API_KEY=sk-..." > .env
echo "TAVILY_API_KEY=tvly-..." >> .env

# 方式一：CLI agent
pip install -r requirements.txt
python main.py

# 方式二：完整 Web 栈（FastAPI + PostgreSQL + Redis）
docker compose up -d --build        # http://localhost:8000/docs
cd frontend && npm install && npm run dev   # http://localhost:5173

# 方式三：无 Docker 的后端开发（SQLite 回落 + 限流/缓存降级）
pip install -r backend/requirements.txt
uvicorn backend.main:app --reload
```

VPS 生产部署（Nginx + HTTPS）：见 [deploy/DEPLOY.md](deploy/DEPLOY.md)。

## Project Structure

```
src/npc_agent/
  agent.py          ReAct loop
  llm_client.py     DeepSeek client
  memory.py         Conversation memory
  tracing.py        Langfuse tracing
  tools/
    risk_score.py   Rule-based scorer
    input_guard.py  Injection detection
    knowledge.py    BM25 retrieval
    web_search.py   Tavily search

scripts/
  expand_sft_data.py     Seed expansion (50 → 220)
  format_for_qwen.py     Convert to Qwen chat format
  train_lora.py          LoRA SFT training
  train_grpo.py          GRPO post-training
  grpo_reward.py         Hybrid reward function
  build_grpo_dataset.py  GRPO dataset builder

backend/
  main.py           FastAPI app
  auth.py           JWT + bcrypt
  db/orm.py         SQLAlchemy 2.0 models (users/sessions/messages/tool_calls)
  db/models.py      Repository layer
  services/         Redis client / cache / rate limit / pending handoff
  agent/integration.py  Agent → WebSocket streaming bridge (+ tool cache)

evals/
  run_compare.py        5-way comparison
  judge.py              LLM-as-Judge (pinned snapshot)
  cases.json            15 test scenarios (v1, frozen)
  cases_v2.json         80 reviewed scenarios (incl. hard negatives)
  benchmark_public.py   Public-dataset P/R/F1 harness
  run_ablation.py       Tool-ablation runner
  benchmark_report.md   Public benchmark results (committed)

deploy/             Nginx + TLS + prod compose + DEPLOY.md
docs/PERF.md        Load-test numbers & event-loop fix writeup
tests/backend/      28 backend tests (fakeredis + ASGI, no network)
.github/workflows/  CI: backend tests + offline eval tests

notebooks/
  train_grpo_colab.ipynb       GRPO training (Colab)
  train_grpo_kaggle.ipynb      GRPO training (Kaggle)
  train_qwen_lora_kaggle.ipynb SFT training (Kaggle)
  eval_compare_kaggle.ipynb    Evaluation (Kaggle)
```

## License

MIT
