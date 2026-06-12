"""消融实验：量化各工具对 Agent 回答质量的贡献。

变体（通过 step(active_tools=...) 实现，其余配置与正式评估一致）：
    full           全部 5 个工具
    no_rag         去掉 search_knowledge（知识库检索）
    no_web_search  去掉 web_search
    no_risk_score  去掉 risk_score（规则评分器）
    no_tools       纯对话，无任何工具

指标说明：
    rule_pass     run_eval 的完整规则通过率（含工具调用检查——禁用了某工具的变体
                  在「期望调用该工具」的 case 上必然失败，此列对消融变体偏严，仅供参考）
    content_pass  只看关键词命中 + 禁词（衡量回答内容，是消融对比的主指标）
    judge_*       LLM-as-judge 4 维（gpt-4o-mini 快照，temperature=0）
    hard_neg      risk_label=legit 子集的 content_pass（误报抵抗力）

用法：
    python evals/run_ablation.py --cases evals/cases_v2.json --variants full no_tools --limit 3   # 冒烟
    python evals/run_ablation.py --cases evals/cases_v2.json --judge                              # 全量

逐 case 结果写 evals/results/ablation_<variant>.jsonl（断点续跑按 id 跳过）；
汇总写 evals/ablation_report.md + evals/ablation_metrics.json。
"""

from __future__ import annotations

import argparse
import datetime
import json
import statistics
import sys
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT / "src"))
sys.path.insert(0, str(PROJECT_ROOT / "evals"))

from run_eval import EVAL_STEP_KWARGS, load_cases, run_one_case  # noqa: E402

RESULTS_DIR = PROJECT_ROOT / "evals" / "results"
REPORT_PATH = PROJECT_ROOT / "evals" / "ablation_report.md"
METRICS_PATH = PROJECT_ROOT / "evals" / "ablation_metrics.json"

ABLATIONS: dict[str, dict] = {
    "full": {"active_tools": None},
    "no_rag": {"active_tools": ["web_search", "get_current_time", "calculator", "risk_score"]},
    "no_web_search": {"active_tools": ["search_knowledge", "get_current_time", "calculator", "risk_score"]},
    "no_risk_score": {"active_tools": ["search_knowledge", "web_search", "get_current_time", "calculator"]},
    "no_tools": {"active_tools": []},
}
DEFAULT_VARIANTS = ["full", "no_rag", "no_web_search", "no_tools"]


def content_pass(rule_result: dict) -> bool:
    """只看内容检查（关键词 + 禁词），忽略工具调用检查。"""
    checks = rule_result.get("checks", {})
    if not checks:
        return False
    return bool(
        checks.get("keywords_present", {}).get("pass", False)
        and checks.get("no_forbidden", {}).get("pass", False)
    )


def run_variant(
    name: str,
    cases: list[dict],
    step_kwargs: dict,
    with_judge: bool,
    workers: int = 4,
    judge_workers: int = 8,
) -> list[dict]:
    """跑一个变体的所有 case（并发 + 断点续跑），可选叠加 judge。"""
    out_path = RESULTS_DIR / f"ablation_{name}.jsonl"
    out_path.parent.mkdir(parents=True, exist_ok=True)

    done: dict[str, dict] = {}
    if out_path.exists():
        with open(out_path, encoding="utf-8") as f:
            for line in f:
                if line.strip():
                    row = json.loads(line)
                    done[row["id"]] = row

    todo = [c for c in cases if c["id"] not in done]
    print(f"[{name}] case {len(cases)} 个，已完成 {len(done)}，本轮待跑 {len(todo)}")

    lock = threading.Lock()

    def work(case: dict) -> None:
        r = run_one_case(case, step_kwargs=step_kwargs)
        r["risk_label"] = case.get("risk_label", "")
        with lock:
            with open(out_path, "a", encoding="utf-8") as f:
                f.write(json.dumps(r, ensure_ascii=False) + "\n")
            done[r["id"]] = r
            if len(done) % 10 == 0 or len(done) == len(cases):
                print(f"[{name}] {len(done)}/{len(cases)}")

    if todo:
        if workers <= 1:
            for c in todo:
                work(c)
        else:
            with ThreadPoolExecutor(max_workers=workers) as ex:
                list(ex.map(work, todo))

    results = [done[c["id"]] for c in cases if c["id"] in done]

    if with_judge:
        from judge import llm_judge  # noqa: E402

        cases_by_id = {c["id"]: c for c in cases}
        need = [r for r in results if not r.get("judge_result") and not r.get("error")]
        print(f"[{name}] judge 待打分 {len(need)} 条...")

        def judge_one(r: dict) -> None:
            case = cases_by_id[r["id"]]
            try:
                r["judge_result"] = llm_judge(
                    {
                        "user_input": case["user_input"],
                        "expected_keywords": case.get("expected_keywords", []),
                        "scenario_type": case.get("scenario_type", ""),
                    },
                    r["agent_reply"],
                )
            except Exception as e:
                print(f"  judge error ({r['id']}): {e}")
                r["judge_result"] = None

        with ThreadPoolExecutor(max_workers=judge_workers) as ex:
            list(ex.map(judge_one, need))

        # judge 结果落盘（整文件重写，含 judge 字段）
        with open(out_path, "w", encoding="utf-8") as f:
            for r in results:
                f.write(json.dumps(r, ensure_ascii=False) + "\n")

    return results


def variant_summary(results: list[dict]) -> dict:
    n = len(results) or 1
    rule_passed = sum(1 for r in results if r["rule_result"]["pass"])
    content_passed = sum(1 for r in results if content_pass(r["rule_result"]))
    hard_neg = [r for r in results if r.get("risk_label") == "legit"]
    hard_neg_passed = sum(1 for r in hard_neg if content_pass(r["rule_result"]))
    judged = [r for r in results if r.get("judge_result")]

    summary = {
        "n": len(results),
        "rule_pass": round(rule_passed / n, 4),
        "content_pass": round(content_passed / n, 4),
        "hard_neg_n": len(hard_neg),
        "hard_neg_content_pass": round(hard_neg_passed / len(hard_neg), 4) if hard_neg else None,
        "avg_latency_ms": int(statistics.mean(r["latency_ms"] for r in results)) if results else 0,
        "avg_tool_calls": round(
            statistics.mean(len(r.get("tool_calls_made", [])) for r in results), 2
        ) if results else 0.0,
        "errors": sum(1 for r in results if r.get("error")),
    }
    if judged:
        summary["judge_n"] = len(judged)
        summary["judge_overall"] = round(
            statistics.mean(r["judge_result"]["overall"] for r in judged), 2
        )
        for dim in ("accuracy", "actionability", "citation", "tone"):
            summary[f"judge_{dim}"] = round(
                statistics.mean(r["judge_result"]["scores"][dim] for r in judged), 2
            )
    return summary


def write_report(summaries: dict[str, dict], cases_path: Path, with_judge: bool) -> None:
    from judge import JUDGE_MODEL  # noqa: E402

    today = datetime.date.today().isoformat()
    full = summaries.get("full", {})
    lines = [
        "# 消融实验报告：各工具对回答质量的贡献",
        "",
        f"- **case 集**: `{cases_path}`（n={next(iter(summaries.values()))['n']}）",
        "- **配置**: temperature=0，不注入长期记忆，不落盘；变体仅改 `active_tools`",
        f"- **judge**: {JUDGE_MODEL if with_judge else '未启用'}（temperature=0）",
        f"- **运行日期**: {today}；模型: deepseek-chat (V3)",
        "- **指标**: content_pass=关键词+禁词通过率（消融主指标）；rule_pass 含工具调用检查，"
        "对禁用工具的变体结构性偏严，仅供参考；hard_neg=合法消息子集通过率（误报抵抗）",
        "",
    ]

    header = "| 变体 | content_pass | Δ vs full | rule_pass | hard_neg | 平均工具调用 | 平均延迟 |"
    sep = "|---|---|---|---|---|---|---|"
    if with_judge:
        header = (
            "| 变体 | content_pass | Δ | judge 总分 | Δ | accuracy | actionability | citation | tone "
            "| hard_neg | 工具调用/case | 延迟 |"
        )
        sep = "|---|---|---|---|---|---|---|---|---|---|---|---|"
    lines += [header, sep]

    for name, s in summaries.items():
        d_content = s["content_pass"] - full.get("content_pass", 0)
        hard_neg = f"{s['hard_neg_content_pass']:.0%}" if s.get("hard_neg_content_pass") is not None else "—"
        if with_judge and "judge_overall" in s:
            d_judge = s["judge_overall"] - full.get("judge_overall", 0)
            lines.append(
                f"| {name} | {s['content_pass']:.1%} | {d_content:+.1%} "
                f"| {s['judge_overall']:.2f} | {d_judge:+.2f} "
                f"| {s['judge_accuracy']:.2f} | {s['judge_actionability']:.2f} "
                f"| {s['judge_citation']:.2f} | {s['judge_tone']:.2f} "
                f"| {hard_neg} | {s['avg_tool_calls']:.2f} | {s['avg_latency_ms']} ms |"
            )
        else:
            lines.append(
                f"| {name} | {s['content_pass']:.1%} | {d_content:+.1%} | {s['rule_pass']:.1%} "
                f"| {hard_neg} | {s['avg_tool_calls']:.2f} | {s['avg_latency_ms']} ms |"
            )

    REPORT_PATH.write_text("\n".join(lines) + "\n", encoding="utf-8")
    print(f"[report] {REPORT_PATH}")


def main() -> None:
    parser = argparse.ArgumentParser(description="消融实验 runner")
    parser.add_argument("--cases", type=Path, default=PROJECT_ROOT / "evals" / "cases_v2.json")
    parser.add_argument("--variants", nargs="+", default=DEFAULT_VARIANTS, choices=list(ABLATIONS))
    parser.add_argument("--judge", action="store_true")
    parser.add_argument("--limit", type=int, default=None)
    parser.add_argument("--workers", type=int, default=4)
    args = parser.parse_args()

    cases = load_cases(args.cases)
    if args.limit:
        cases = cases[: args.limit]

    # 主线程预热知识库（embedding 懒加载非线程安全）
    if any(
        ABLATIONS[v]["active_tools"] is None or "search_knowledge" in (ABLATIONS[v]["active_tools"] or [])
        for v in args.variants
    ):
        from npc_agent.tools.knowledge import _ensure_loaded
        _ensure_loaded()

    summaries: dict[str, dict] = {}
    for variant in args.variants:
        step_kwargs = {**EVAL_STEP_KWARGS, **ABLATIONS[variant]}
        t0 = time.time()
        results = run_variant(variant, cases, step_kwargs, with_judge=args.judge, workers=args.workers)
        summaries[variant] = variant_summary(results)
        s = summaries[variant]
        print(
            f"[{variant}] content_pass={s['content_pass']:.1%} rule_pass={s['rule_pass']:.1%}"
            + (f" judge={s.get('judge_overall')}" if args.judge else "")
            + f"（{int(time.time() - t0)}s）"
        )

    METRICS_PATH.write_text(json.dumps(summaries, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"[metrics] {METRICS_PATH}")
    write_report(summaries, args.cases, args.judge)


if __name__ == "__main__":
    main()
