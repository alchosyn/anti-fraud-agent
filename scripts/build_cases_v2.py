"""合并 cases.json(v1) + 评审后的 cases_v2_candidates.json → evals/cases_v2.json。

人工评审的修订全部编码在本文件（可审计、可重放）：
  - legit 硬负例：取消工具调用要求（考内容不考过程——对明显正常的消息，
    agent 直接回答与先验证后回答都算对）；must_not_contain 加「假冒」，
    防止错误回答「这不正常/这是假冒」靠子串命中「正常」假通过
  - 三条 borderline 实为教科书诈骗模式（社保卡停用链接/冒充客服加QQ/兼职押金），
    重标为 fraud 并改关键词
  - 个别不可达关键词修正（「老人」「短链」），过时场景（健康码）删除
  - v1 的 15 条 case 原样并入（已被既有报告验证过），补 risk_label/source 字段

用法：python scripts/build_cases_v2.py
"""

from __future__ import annotations

import json
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
V1_PATH = PROJECT_ROOT / "evals" / "cases.json"
CANDIDATES_PATH = PROJECT_ROOT / "evals" / "cases_v2_candidates.json"
OUT_PATH = PROJECT_ROOT / "evals" / "cases_v2.json"

# v1 case 的 risk_label 标注（评审判断）
V1_LABELS = {
    "phish-sms-bank": "fraud", "fake-customs": "fraud", "fake-public-security": "fraud",
    "shua-dan": "fraud", "killing-pig": "fraud", "ai-faceswap": "fraud",
    "password-check": "consult", "after-scam": "fraud", "loan-scam": "fraud",
    "credit-fix": "fraud", "verification-code-leak": "fraud", "boss-fake": "fraud",
    "qr-payment": "fraud", "elderly-investment": "fraud", "general-chat": "offtopic",
}

# 按候选 id 的字段覆盖（评审修订）
EDITS: dict[str, dict] = {
    # —— 关键词可达性修正 ——
    "v2-fraud-007": {"expected_keywords": ["假", "钓鱼", "退税", "不要点"]},
    "v2-fraud-011": {"expected_keywords": ["不要", "投诉", "12315", "退款"]},
    "v2-fraud-026": {"expected_keywords": ["假", "不要转", "96110", "诈骗"]},
    # —— 重标：实为教科书诈骗模式 ——
    "v2-borderline-006": {
        "risk_label": "fraud",
        "expected_keywords": ["诈骗", "别点", "假", "钓鱼"],
    },
    "v2-borderline-007": {
        "risk_label": "fraud",
        "expected_keywords": ["诈骗", "官方", "核实", "不要加"],
    },
    "v2-borderline-008": {
        "risk_label": "fraud",
        "expected_keywords": ["押金", "诈骗", "不要交", "违法"],
    },
    # —— 时效修正 ——
    "v2-legit-009": {
        "user_input": "我妈妈收到一条短信'【中国铁路】您购买的10月1日G1234次列车已出票，"
                      "座位号05车厢08A，请凭身份证进站'，她怀疑是骗子发的，您看呢？",
    },
}

DROP_IDS = {"v2-legit-008"}  # 健康码场景已过时

# legit 硬负例统一处理：不要求工具调用；must_not_contain 加「假冒」反向防护
LEGIT_TOOLS: list[str] = []
LEGIT_FORBIDDEN = ["假冒", "立即报警", "马上挂断"]


def main() -> None:
    with open(V1_PATH, encoding="utf-8") as f:
        v1 = json.load(f)
    with open(CANDIDATES_PATH, encoding="utf-8") as f:
        candidates = json.load(f)

    merged: list[dict] = []
    for c in v1:
        merged.append({
            **c,
            "risk_label": V1_LABELS[c["id"]],
            "source": "seed",
            "reviewed": True,
        })

    for c in candidates:
        if c["id"] in DROP_IDS:
            continue
        c = {**c, **EDITS.get(c["id"], {})}
        if c["risk_label"] == "legit":
            c["expected_tool_calls"] = LEGIT_TOOLS
            c["must_not_contain"] = LEGIT_FORBIDDEN
        c["reviewed"] = True
        merged.append(c)

    # 重新编号生成类 id（重标后保持前缀与标签一致）
    counters: dict[str, int] = {}
    for c in merged:
        if c["source"] == "seed":
            continue
        label = c["risk_label"]
        counters[label] = counters.get(label, 0) + 1
        c["id"] = f"v2-{label}-{counters[label]:03d}"

    ids = [c["id"] for c in merged]
    assert len(ids) == len(set(ids)), "id 重复"
    for c in merged:
        assert c["user_input"] and isinstance(c["expected_tool_calls"], list)

    with open(OUT_PATH, "w", encoding="utf-8") as f:
        json.dump(merged, f, ensure_ascii=False, indent=2)

    from collections import Counter
    dist = Counter(c["risk_label"] for c in merged)
    print(f"cases_v2.json: {len(merged)} 条 → {OUT_PATH}")
    for label, n in sorted(dist.items()):
        print(f"  {label}: {n}")


if __name__ == "__main__":
    main()
