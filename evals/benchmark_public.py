"""公开数据集基准：可疑短信拦截判定（P/R/F1 客观指标）。

任务定义：给定一条短信，判断应当「拦截」（广告推销/诈骗/钓鱼/博彩/违法推广）
还是「放行」（正常交流、官方通知、验证码等）。正类 = 拦截（label=1）。

数据：hrwhisper/SpamMessage 分层采样（见 scripts/evaldata/fetch_benchmark_data.py），
dev 集只用于规则引擎调阈值，test 集报告最终指标。
注意：该数据集对数字做了脱敏（手机号/金额/日期中的数字替换为 x），
会削弱依赖 \\d 的正则规则，报告中已注明。

对比系统（同一份样本）：
    risk_score   规则引擎（纯本地、零成本、阈值在 dev 上选定后冻结）
    single_shot  DeepSeek 单次调用、无工具（隔离工具贡献的消融）
    agent        完整 agent（DeepSeek + risk_score + search_knowledge，不含 web_search）

用法：
    python evals/benchmark_public.py --systems risk_score                  # 免费，含 dev 阈值扫描
    python evals/benchmark_public.py --systems agent --limit 10            # 付费前冒烟
    python evals/benchmark_public.py --systems risk_score single_shot agent

逐样本结果追加写 evals/results/benchmark_<system>.jsonl（可断点续跑，按 id 去重）；
汇总指标写 evals/reports/benchmark_report.md + evals/reports/benchmark_metrics.json。
"""

from __future__ import annotations

import argparse
import datetime
import json
import re
import statistics
import sys
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT / "src"))

from npc_agent.tools.risk_score import risk_score  # noqa: E402

TEST_PATH = PROJECT_ROOT / "evals" / "data" / "spam_sample_v1.jsonl"
DEV_PATH = PROJECT_ROOT / "evals" / "data" / "spam_sample_v1.dev.jsonl"
RESULTS_DIR = PROJECT_ROOT / "evals" / "results"
REPORT_PATH = PROJECT_ROOT / "evals" / "reports" / "benchmark_report.md"
METRICS_PATH = PROJECT_ROOT / "evals" / "reports" / "benchmark_metrics.json"

DATASET_SOURCE = "hrwhisper/SpamMessage@754d3a7"
SAMPLE_SEED = 42
THRESHOLD_CANDIDATES = (15, 25, 40, 70)

# DeepSeek V3 牌价假设（缓存未命中），报告中注明，仅用于估算
PRICE_IN_PER_M = 2.0   # 元 / 百万 input tokens
PRICE_OUT_PER_M = 8.0  # 元 / 百万 output tokens

# agent 分类配置：不开 web_search（外部 API 不可复现且烧钱）、不开与任务无关的工具
AGENT_TOOLS = ("risk_score", "search_knowledge")

CLASSIFY_PROMPT = (
    "请判断下面这条短信是否应该被拦截。\n"
    "拦截对象：广告推销、诈骗、钓鱼、博彩、违法推广类短信。\n"
    "放行对象：正常个人交流、官方通知、验证码等。\n"
    "注意：这条短信里的数字已被脱敏为 x，属于数据处理痕迹，不是可疑信号。\n\n"
    "短信原文：\n「{sms}」\n\n"
    "可以先分析，但回复的最后一行必须严格输出以下两者之一：\n【结论】拦截\n【结论】放行"
)

_RETRY_SUFFIX = "\n\n再强调一次：最后一行只能是「【结论】拦截」或「【结论】放行」，不要输出其他结尾。"

_VERDICT_RE = re.compile(r"【结论】\s*(拦截|放行)")
_INTERCEPT_WORDS = ("拦截", "垃圾", "诈骗", "钓鱼")
_RELEASE_WORDS = ("放行", "正常", "安全")

# step() 内部吞掉 API 异常后的兜底回复——视为瞬时错误，由 harness 重试
_API_FAIL_REPLY = "……信号不太好 你再说一遍"
# input_guard 拦截的固定回复——单独统计
_GUARD_BLOCKED_REPLY = "这段话里有些奇怪的指令，我不吃这套。有正经问题直接问。"


class TransientLLMError(RuntimeError):
    """LLM API 瞬时失败（step() 返回兜底句），应重试。"""


def load_jsonl(path: Path) -> list[dict]:
    with open(path, encoding="utf-8") as f:
        return [json.loads(line) for line in f if line.strip()]


def parse_verdict(reply: str) -> int | None:
    """从回复中解析 拦截=1 / 放行=0，解析不出返回 None。"""
    if not reply or not reply.strip():
        return None
    matches = _VERDICT_RE.findall(reply)
    if matches:
        return 1 if matches[-1] == "拦截" else 0
    # 同义词兜底：只看最后两行；两侧信号都出现或都不出现 → 判不出
    tail = "\n".join(reply.strip().splitlines()[-2:])
    hit_intercept = any(w in tail for w in _INTERCEPT_WORDS)
    hit_release = any(w in tail for w in _RELEASE_WORDS)
    if hit_intercept and not hit_release:
        return 1
    if hit_release and not hit_intercept:
        return 0
    return None


# ─── 三个被测系统 ────────────────────────────────────────────

def classify_risk_score(text: str, threshold: int) -> dict:
    """规则引擎：score >= threshold 即拦截。纯本地。"""
    r = risk_score(text)
    return {
        "pred": 1 if r["score"] >= threshold else 0,
        "score": r["score"],
        "signals": r["signals"],
        "parse_fail": False,
        "tokens_in": 0,
        "tokens_out": 0,
        "n_tool_calls": 0,
    }


def _trace_tokens(trace: dict) -> tuple[int, int, int]:
    tokens_in = tokens_out = n_tool = 0
    for s in trace.get("steps", []):
        if s.get("type") == "llm_call":
            tokens_in += s.get("prompt_tokens", 0)
            tokens_out += s.get("completion_tokens", 0)
        elif s.get("type") == "tool_call":
            n_tool += 1
    return tokens_in, tokens_out, n_tool


def _llm_classify(text: str, active_tools: tuple[str, ...]) -> dict:
    """共用的 LLM 分类路径：active_tools=() 即 single_shot，否则为 agent。"""
    from npc_agent.agent import step
    from npc_agent.persona import SYSTEM_PROMPT

    def ask(user_input: str) -> tuple[str, dict]:
        trace: dict = {}
        messages = [{"role": "system", "content": SYSTEM_PROMPT}]
        reply, _ = step(
            messages,
            user_input,
            active_tools=list(active_tools),
            use_long_memory=False,
            persist=False,
            temperature=0.0,
            trace_sink=trace,
        )
        if reply == _API_FAIL_REPLY:
            raise TransientLLMError("LLM API 调用失败")
        return reply, trace

    user_input = CLASSIFY_PROMPT.format(sms=text)
    reply, trace = ask(user_input)
    tokens_in, tokens_out, n_tool = _trace_tokens(trace)

    guard_blocked = reply == _GUARD_BLOCKED_REPLY
    pred = parse_verdict(reply)
    retried = False
    if pred is None and not guard_blocked:
        retried = True
        reply2, trace2 = ask(user_input + _RETRY_SUFFIX)
        t_in2, t_out2, n_tool2 = _trace_tokens(trace2)
        tokens_in += t_in2
        tokens_out += t_out2
        n_tool += n_tool2
        p2 = parse_verdict(reply2)
        if p2 is not None:
            pred = p2
            reply = reply2

    parse_fail = pred is None
    if pred is None:
        pred = 0  # 弃权按放行计：出不了结论的探测器拦不住任何东西

    return {
        "pred": pred,
        "reply": reply[:300],
        "parse_fail": parse_fail,
        "retried": retried,
        "guard_blocked": guard_blocked,
        "tokens_in": tokens_in,
        "tokens_out": tokens_out,
        "n_tool_calls": n_tool,
    }


def classify_agent(text: str) -> dict:
    return _llm_classify(text, AGENT_TOOLS)


def classify_single_shot(text: str) -> dict:
    return _llm_classify(text, ())


# ─── 运行与汇总 ──────────────────────────────────────────────

def run_system(
    name: str,
    samples: list[dict],
    classify_fn,
    out_path: Path,
    max_workers: int = 6,
) -> list[dict]:
    """并发跑一个系统；逐样本追加写 jsonl，断点续跑按 id 跳过。"""
    out_path.parent.mkdir(parents=True, exist_ok=True)
    done_ids: set[str] = set()
    if out_path.exists():
        for row in load_jsonl(out_path):
            done_ids.add(row["id"])

    todo = [s for s in samples if s["id"] not in done_ids]
    print(f"[{name}] 样本 {len(samples)} 条，已完成 {len(done_ids & {s['id'] for s in samples})}，本轮待跑 {len(todo)}")

    lock = threading.Lock()
    progress = {"done": 0}

    def work(sample: dict) -> None:
        last_err: Exception | None = None
        result: dict | None = None
        for attempt in range(3):
            try:
                t0 = time.time()
                result = classify_fn(sample["text"])
                result["latency_ms"] = int((time.time() - t0) * 1000)
                break
            except Exception as e:  # TransientLLMError / 网络错误
                last_err = e
                time.sleep(2 * 2**attempt)
        if result is None:
            result = {
                "pred": 0,
                "parse_fail": True,
                "error": str(last_err)[:200],
                "latency_ms": 0,
                "tokens_in": 0,
                "tokens_out": 0,
                "n_tool_calls": 0,
            }
        row = {"id": sample["id"], "label": sample["label"], **result}
        with lock:
            with open(out_path, "a", encoding="utf-8") as f:
                f.write(json.dumps(row, ensure_ascii=False) + "\n")
            progress["done"] += 1
            if progress["done"] % 25 == 0 or progress["done"] == len(todo):
                print(f"[{name}] {progress['done']}/{len(todo)}")

    if todo:
        if max_workers <= 1:
            for s in todo:
                work(s)
        else:
            with ThreadPoolExecutor(max_workers=max_workers) as ex:
                list(ex.map(work, todo))

    # 读回完整结果，限定在当前样本集内并按 id 去重（保留最后一次）
    by_id = {row["id"]: row for row in load_jsonl(out_path)}
    return [by_id[s["id"]] for s in samples if s["id"] in by_id]


def compute_metrics(y_true: list[int], y_pred: list[int]) -> dict:
    from sklearn.metrics import (
        accuracy_score,
        confusion_matrix,
        f1_score,
        precision_score,
        recall_score,
    )

    cm = confusion_matrix(y_true, y_pred, labels=[0, 1])
    tn, fp, fn, tp = (int(v) for v in cm.ravel())
    return {
        "n": len(y_true),
        "precision": round(float(precision_score(y_true, y_pred, zero_division=0)), 4),
        "recall": round(float(recall_score(y_true, y_pred, zero_division=0)), 4),
        "f1": round(float(f1_score(y_true, y_pred, zero_division=0)), 4),
        "accuracy": round(float(accuracy_score(y_true, y_pred)), 4),
        "fpr": round(fp / (fp + tn), 4) if (fp + tn) else 0.0,
        "confusion": {"tn": tn, "fp": fp, "fn": fn, "tp": tp},
    }


def sweep_thresholds(dev_samples: list[dict], thresholds=THRESHOLD_CANDIDATES) -> dict:
    """在 dev 集上扫规则引擎阈值，返回各阈值指标 + ROC-AUC + 最优阈值（按 F1）。"""
    from sklearn.metrics import roc_auc_score

    y_true = [s["label"] for s in dev_samples]
    scores = [risk_score(s["text"])["score"] for s in dev_samples]
    rows = []
    for t in thresholds:
        y_pred = [1 if sc >= t else 0 for sc in scores]
        rows.append({"threshold": t, **compute_metrics(y_true, y_pred)})
    best = max(rows, key=lambda r: r["f1"])
    return {
        "rows": rows,
        "best_threshold": best["threshold"],
        "roc_auc": round(float(roc_auc_score(y_true, scores)), 4),
    }


def system_summary(rows: list[dict]) -> dict:
    """从逐样本结果汇总指标 + 运行统计。"""
    y_true = [r["label"] for r in rows]
    y_pred = [r["pred"] for r in rows]
    m = compute_metrics(y_true, y_pred)
    latencies = [r.get("latency_ms", 0) for r in rows]
    tokens_in = sum(r.get("tokens_in", 0) for r in rows)
    tokens_out = sum(r.get("tokens_out", 0) for r in rows)
    n = len(rows) or 1
    cost_total = tokens_in / 1e6 * PRICE_IN_PER_M + tokens_out / 1e6 * PRICE_OUT_PER_M
    m.update({
        "parse_fail_rate": round(sum(1 for r in rows if r.get("parse_fail")) / n, 4),
        "guard_blocked": sum(1 for r in rows if r.get("guard_blocked")),
        "error_count": sum(1 for r in rows if r.get("error")),
        "latency_p50_ms": int(statistics.median(latencies)) if latencies else 0,
        "latency_p95_ms": int(sorted(latencies)[int(0.95 * (len(latencies) - 1))]) if latencies else 0,
        "avg_tokens_in": round(tokens_in / n, 1),
        "avg_tokens_out": round(tokens_out / n, 1),
        "avg_tool_calls": round(sum(r.get("n_tool_calls", 0) for r in rows) / n, 2),
        "cost_per_1k_msgs_rmb": round(cost_total / n * 1000, 2),
    })
    return m


def _error_examples(rows: list[dict], samples_by_id: dict, kind: str, limit: int = 10) -> list[str]:
    """kind: 'fp'（正常被拦）或 'fn'（垃圾被放）。返回报告用文本行。"""
    if kind == "fp":
        picked = [r for r in rows if r["label"] == 0 and r["pred"] == 1]
    else:
        picked = [r for r in rows if r["label"] == 1 and r["pred"] == 0]
    out = []
    for r in picked[:limit]:
        text = samples_by_id.get(r["id"], {}).get("text", "")[:60]
        out.append(f"- `{r['id']}` {text}")
    return out


def write_report(
    metrics: dict[str, dict],
    sweep: dict | None,
    threshold: int,
    rows_by_system: dict[str, list[dict]],
    samples: list[dict],
) -> None:
    samples_by_id = {s["id"]: s for s in samples}
    today = datetime.date.today().isoformat()
    n = len(samples)

    lines = [
        "# 公开数据集基准报告：可疑短信拦截判定",
        "",
        "## 方法论",
        "",
        f"- **数据集**: [{DATASET_SOURCE}](https://github.com/hrwhisper/SpamMessage)（约 80 万条带标签中文短信；"
        "label=1 垃圾【广告/诈骗/钓鱼】，label=0 正常。仓库未声明 license，本仓库仅分发派生小样本+出处行号）",
        f"- **采样**: 分层采样，seed={SAMPLE_SEED}；dev 100 条（仅用于规则引擎调阈值）+ test {n} 条（报告指标）。"
        "样本文件: `evals/data/spam_sample_v1[.dev].jsonl`，由 `scripts/evaldata/fetch_benchmark_data.py` 可复现",
        "- **任务**: 二分类「拦截 / 放行」，正类=拦截。LLM 系统通过提示词约束输出 `【结论】拦截/放行` 后正则解析；"
        "解析失败重试一次，仍失败按「放行」计（弃权的探测器拦不住任何东西），并单独报告 parse_fail_rate",
        f"- **被测系统**: ① risk_score 规则引擎（阈值 {threshold}，dev 上按 F1 选定后冻结）；"
        "② single_shot（deepseek-chat 单次调用、无工具）；③ agent（deepseek-chat + risk_score + search_knowledge，"
        "temperature=0、不注入长期记忆、不开 web_search）",
        f"- **成本估算**: 按 DeepSeek 牌价假设 输入 ¥{PRICE_IN_PER_M}/M、输出 ¥{PRICE_OUT_PER_M}/M（缓存未命中价）。"
        "agent 行未计入 search_knowledge 内部 query 改写的少量 LLM 调用",
        "- **已知数据特性**: 数据集对数字脱敏（替换为 x），削弱依赖 `\\d` 的正则信号；"
        "提示词中已告知模型该痕迹不构成可疑信号",
        f"- **运行日期**: {today}；模型: deepseek-chat (V3)",
        "",
        "## 主结果（test 集）",
        "",
        "| 系统 | n | Precision | Recall | F1 | Accuracy | FPR | p50 延迟 | p95 延迟 | 均 tokens (in/out) | 工具调用/条 | ¥/千条 | parse_fail |",
        "|---|---|---|---|---|---|---|---|---|---|---|---|---|",
    ]
    for name, m in metrics.items():
        lines.append(
            f"| {name} | {m['n']} | {m['precision']:.3f} | {m['recall']:.3f} | **{m['f1']:.3f}** "
            f"| {m['accuracy']:.3f} | {m['fpr']:.3f} | {m['latency_p50_ms']} ms | {m['latency_p95_ms']} ms "
            f"| {m['avg_tokens_in']:.0f}/{m['avg_tokens_out']:.0f} | {m['avg_tool_calls']:.2f} "
            f"| {m['cost_per_1k_msgs_rmb']:.2f} | {m['parse_fail_rate']:.1%} |"
        )

    lines += ["", "### 混淆矩阵", ""]
    for name, m in metrics.items():
        c = m["confusion"]
        lines += [
            f"**{name}**（行=真实，列=预测；正类=拦截）",
            "",
            "| | 预测放行 | 预测拦截 |",
            "|---|---|---|",
            f"| 真实正常 | {c['tn']} | {c['fp']} |",
            f"| 真实垃圾 | {c['fn']} | {c['tp']} |",
            "",
        ]

    if sweep:
        lines += [
            "## 规则引擎阈值扫描（dev 集，100 条）",
            "",
            f"- 连续分数 ROC-AUC: **{sweep['roc_auc']:.3f}**；按 F1 选定阈值 **{sweep['best_threshold']}**",
            "",
            "| 阈值 | Precision | Recall | F1 | FPR |",
            "|---|---|---|---|---|",
        ]
        for r in sweep["rows"]:
            marker = " ←" if r["threshold"] == sweep["best_threshold"] else ""
            lines.append(
                f"| {r['threshold']}{marker} | {r['precision']:.3f} | {r['recall']:.3f} "
                f"| {r['f1']:.3f} | {r['fpr']:.3f} |"
            )
        lines.append("")

    lines += ["## 错误分析（每系统最多各 10 例）", ""]
    for name, rows in rows_by_system.items():
        lines.append(f"### {name}")
        lines.append("")
        fp = _error_examples(rows, samples_by_id, "fp")
        fn = _error_examples(rows, samples_by_id, "fn")
        lines.append(f"**误报 FP（正常被拦，共 {metrics[name]['confusion']['fp']} 条）**：")
        lines += fp or ["- 无"]
        lines.append("")
        lines.append(f"**漏报 FN（垃圾被放，共 {metrics[name]['confusion']['fn']} 条）**：")
        lines += fn or ["- 无"]
        lines.append("")

    REPORT_PATH.write_text("\n".join(lines), encoding="utf-8")
    print(f"[report] {REPORT_PATH}")


def main() -> None:
    parser = argparse.ArgumentParser(description="公开数据集基准")
    parser.add_argument(
        "--systems", nargs="+", default=["risk_score"],
        choices=["risk_score", "single_shot", "agent"],
    )
    parser.add_argument("--limit", type=int, default=None, help="只跑 test 集前 N 条（冒烟用）")
    parser.add_argument("--threshold", type=int, default=None, help="跳过 dev 扫描，直接指定规则阈值")
    parser.add_argument("--workers", type=int, default=6)
    args = parser.parse_args()

    test = load_jsonl(TEST_PATH)
    dev = load_jsonl(DEV_PATH)
    if args.limit:
        test = test[: args.limit]

    # 阈值：优先命令行，否则 dev 扫描
    sweep = None
    threshold = args.threshold
    if threshold is None:
        sweep = sweep_thresholds(dev)
        threshold = sweep["best_threshold"]
        print(f"[sweep] dev ROC-AUC={sweep['roc_auc']}，选定阈值 {threshold}")

    if any(s in args.systems for s in ("agent",)):
        # 主线程预热知识库（embedding 模型加载非线程安全）
        from npc_agent.tools.knowledge import _ensure_loaded
        _ensure_loaded()

    classify_fns = {
        "risk_score": lambda text: classify_risk_score(text, threshold),
        "single_shot": classify_single_shot,
        "agent": classify_agent,
    }

    metrics: dict[str, dict] = {}
    rows_by_system: dict[str, list[dict]] = {}
    for name in args.systems:
        out_path = RESULTS_DIR / f"benchmark_{name}.jsonl"
        workers = 1 if name == "risk_score" else args.workers
        rows = run_system(name, test, classify_fns[name], out_path, max_workers=workers)
        rows_by_system[name] = rows
        metrics[name] = system_summary(rows)
        print(f"[{name}] F1={metrics[name]['f1']} P={metrics[name]['precision']} "
              f"R={metrics[name]['recall']} FPR={metrics[name]['fpr']}")

    METRICS_PATH.write_text(
        json.dumps({"threshold": threshold, "sweep": sweep, "metrics": metrics},
                   ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    print(f"[metrics] {METRICS_PATH}")
    write_report(metrics, sweep, threshold, rows_by_system, test)


if __name__ == "__main__":
    main()
