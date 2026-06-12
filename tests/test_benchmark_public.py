"""evals/benchmark_public.py 单元测试。

全部离线：不调任何 API、不下载数据。LLM 分类路径只测纯逻辑部分
（verdict 解析、指标计算、阈值映射、工具子集校验、采样确定性）。
"""

from __future__ import annotations

import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT / "src"))
sys.path.insert(0, str(PROJECT_ROOT / "evals"))
sys.path.insert(0, str(PROJECT_ROOT / "scripts"))

from benchmark_public import (  # noqa: E402
    classify_risk_score,
    compute_metrics,
    parse_verdict,
)
from fetch_benchmark_data import split_dev_test, stratified_sample  # noqa: E402

# ─── parse_verdict ───────────────────────────────────────


def test_verdict_intercept():
    assert parse_verdict("这条短信是典型钓鱼。\n【结论】拦截") == 1


def test_verdict_release():
    assert parse_verdict("正常的快递通知。\n【结论】放行") == 0


def test_verdict_with_space():
    assert parse_verdict("【结论】 拦截") == 1


def test_verdict_last_wins():
    """同时出现多个结论时取最后一个（模型自我纠正的常见形态）。"""
    reply = "初看像广告。【结论】拦截\n等等，这是官方验证码。【结论】放行"
    assert parse_verdict(reply) == 0


def test_verdict_preceded_by_analysis():
    reply = "先打个分。链接是短链，话术带紧迫性，典型钓鱼套路。\n\n【结论】拦截"
    assert parse_verdict(reply) == 1


def test_verdict_synonym_fallback_intercept():
    """没有【结论】标记时，末两行的同义词兜底。"""
    assert parse_verdict("分析了一下。\n这就是垃圾短信，别理。") == 1


def test_verdict_synonym_fallback_release():
    assert parse_verdict("看了一遍。\n正常消息，不用担心。") == 0


def test_verdict_ambiguous_returns_none():
    """末两行同时含两侧信号 → 判不出。"""
    assert parse_verdict("这条看着正常，但也可能是诈骗。") is None


def test_verdict_garbage_returns_none():
    assert parse_verdict("……信号不太好") is None
    assert parse_verdict("") is None
    assert parse_verdict(None) is None


def test_verdict_synonym_only_reads_tail():
    """同义词兜底只看最后两行：前文的干扰词不影响。"""
    reply = "用户问这是不是诈骗。\n我查了下。\n没问题，放行。"
    assert parse_verdict(reply) == 0


# ─── compute_metrics ─────────────────────────────────────


def test_metrics_hand_computed():
    """8 样本手算混淆矩阵交叉验证 sklearn 接线与 FPR 定义。

    y_true: 4 正常(0) + 4 垃圾(1)
    y_pred: tn=3, fp=1, fn=2, tp=2
    precision = 2/3, recall = 2/4, f1 = 2*P*R/(P+R) = 0.5714..., fpr = 1/4
    """
    y_true = [0, 0, 0, 0, 1, 1, 1, 1]
    y_pred = [0, 0, 0, 1, 0, 0, 1, 1]
    m = compute_metrics(y_true, y_pred)
    assert m["confusion"] == {"tn": 3, "fp": 1, "fn": 2, "tp": 2}
    assert abs(m["precision"] - 2 / 3) < 1e-3
    assert abs(m["recall"] - 0.5) < 1e-3
    assert abs(m["f1"] - (2 * (2 / 3) * 0.5 / (2 / 3 + 0.5))) < 1e-3
    assert abs(m["fpr"] - 0.25) < 1e-3
    assert m["accuracy"] == 5 / 8


def test_metrics_all_correct():
    m = compute_metrics([0, 1], [0, 1])
    assert m["f1"] == 1.0
    assert m["fpr"] == 0.0


def test_metrics_degenerate_all_release():
    """全放行：recall=0，f1=0（zero_division 不抛异常）。"""
    m = compute_metrics([1, 1, 0], [0, 0, 0])
    assert m["recall"] == 0.0
    assert m["f1"] == 0.0


# ─── classify_risk_score 阈值映射 ────────────────────────


def test_risk_score_intercepts_strong_scam():
    """安全账户(30) + 公检法(20) = 50 ≥ 40 → 拦截。"""
    text = "我是公安局的，你的账户涉嫌洗钱，请把资金转入安全账户配合调查"
    r = classify_risk_score(text, threshold=40)
    assert r["pred"] == 1
    assert r["score"] >= 40


def test_risk_score_releases_plain_greeting():
    text = "妈，我今晚不回家吃饭了，你们先吃"
    r = classify_risk_score(text, threshold=40)
    assert r["pred"] == 0
    assert r["score"] < 40


def test_risk_score_threshold_boundary():
    """同一文本在不同阈值下的判定应随阈值单调变化。"""
    text = "限时领取疫情补贴，逾期失效"  # 紧迫性(15) + 诱饵(15) = 30
    assert classify_risk_score(text, threshold=15)["pred"] == 1
    assert classify_risk_score(text, threshold=40)["pred"] == 0


def test_risk_score_zero_tokens():
    r = classify_risk_score("随便一句话", threshold=40)
    assert r["tokens_in"] == 0 and r["tokens_out"] == 0 and r["n_tool_calls"] == 0


# ─── step() 工具子集校验 ─────────────────────────────────


def test_active_tools_unknown_name_raises():
    from npc_agent.agent import step

    try:
        step([{"role": "system", "content": "x"}], "你好", active_tools=["no_such_tool"])
    except ValueError as e:
        assert "no_such_tool" in str(e)
    else:
        raise AssertionError("未知工具名应当 raise ValueError")


def test_active_tools_subset_filtering():
    from npc_agent.tools import tools

    allowed = {"risk_score", "search_knowledge"}
    selected = [t for t in tools if t["function"]["name"] in allowed]
    assert {t["function"]["name"] for t in selected} == allowed
    assert all(t["type"] == "function" for t in selected)


# ─── 采样确定性（不下载，用造的行）──────────────────────


def _fake_rows(n_per_class: int = 60) -> list[tuple[int, int, str]]:
    rows = []
    for i in range(n_per_class):
        rows.append((i * 2 + 1, 0, f"正常短信样本编号第{i}条，今天天气不错。"))
        rows.append((i * 2 + 2, 1, f"促销垃圾短信样本编号第{i}条，全场五折起。"))
    return rows


def test_sample_deterministic():
    rows = _fake_rows()
    s1 = stratified_sample(rows, n_per_class=20, seed=42)
    s2 = stratified_sample(rows, n_per_class=20, seed=42)
    assert [r["id"] for r in s1] == [r["id"] for r in s2]


def test_sample_class_counts_exact():
    s = stratified_sample(_fake_rows(), n_per_class=20, seed=42)
    assert sum(1 for r in s if r["label"] == 0) == 20
    assert sum(1 for r in s if r["label"] == 1) == 20


def test_split_disjoint_and_stratified():
    s = stratified_sample(_fake_rows(), n_per_class=20, seed=42)
    dev, test = split_dev_test(s, dev_per_class=5, seed=42)
    dev_ids = {r["id"] for r in dev}
    test_ids = {r["id"] for r in test}
    assert not (dev_ids & test_ids)
    assert len(dev) == 10 and len(test) == 30
    assert sum(1 for r in dev if r["label"] == 1) == 5


def test_split_deterministic():
    s = stratified_sample(_fake_rows(), n_per_class=20, seed=42)
    d1, t1 = split_dev_test(s, dev_per_class=5, seed=42)
    d2, t2 = split_dev_test(s, dev_per_class=5, seed=42)
    assert [r["id"] for r in d1] == [r["id"] for r in d2]
    assert [r["id"] for r in t1] == [r["id"] for r in t2]


# ─── 无 pytest 时的兜底 runner ───────────────────────────

if __name__ == "__main__":
    failed = 0
    for name, fn in sorted(globals().items()):
        if name.startswith("test_") and callable(fn):
            try:
                fn()
                print(f"  PASS {name}")
            except AssertionError as e:
                failed += 1
                print(f"  FAIL {name}: {e}")
    print("全部通过" if failed == 0 else f"{failed} 个失败")
    sys.exit(1 if failed else 0)
