"""Agent integration layer.

Wraps the real 信噪 ReAct agent into an async generator that yields
step-by-step messages for WebSocket streaming.

Falls back to a mock agent if the real agent cannot be imported
(e.g. missing DEEPSEEK_API_KEY or dependencies).
"""

from __future__ import annotations

import asyncio
import json
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import AsyncGenerator

# ---------------------------------------------------------------------------
# Make the project's src/ importable
# ---------------------------------------------------------------------------
_PROJECT_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(_PROJECT_ROOT / "src"))

_REAL_AGENT_AVAILABLE = False
try:
    from npc_agent.config import MAX_STEPS, MODEL          # noqa: E402
    from npc_agent.llm_client import get_client             # noqa: E402
    from npc_agent.memory import SYSTEM_PROMPT              # noqa: E402
    from npc_agent.tools import tool_map, tools             # noqa: E402
    from npc_agent.tools.input_guard import check_injection # noqa: E402
    from npc_agent.utils import clean_reply                 # noqa: E402
    _REAL_AGENT_AVAILABLE = True
    print("[agent] 信噪 Agent 加载成功")
except Exception as exc:
    print(f"[agent] 信噪 Agent 加载失败，使用 mock: {exc}")


# ===================================================================
# Helper: map risk_score output → verdict + confidence
# ===================================================================

def _score_to_verdict(score: int | None) -> tuple[str, float]:
    if score is None:
        return "medium_risk", 0.5
    if score >= 70:
        return "high_risk", min(0.6 + score * 0.004, 0.99)
    if score >= 40:
        return "medium_risk", 0.5 + score * 0.005
    if score >= 15:
        return "low_risk", 0.4 + score * 0.01
    return "safe", 0.85


def _parse_tool_result(raw: str) -> dict:
    """Try to parse a tool result string as JSON, fallback to {raw: ...}."""
    try:
        return json.loads(raw)
    except (json.JSONDecodeError, TypeError):
        return {"raw": raw}


def _summarize(name: str, output: dict) -> str:
    if name == "risk_score":
        return f"风险评分 {output.get('score', '?')}/100，命中 {len(output.get('signals', []))} 项信号"
    if name == "search_knowledge":
        matches = output.get("matches", [])
        hint = output.get("quality_hint", "")
        return f"匹配 {len(matches)} 条知识库记录" + (f"（{hint}）" if hint else "")
    if name == "web_search":
        raw = output.get("raw", "")
        if isinstance(raw, str) and raw:
            return "网络搜索已返回结果"
        return f"搜索到 {len(output.get('results', []))} 条相关结果"
    return str(output)[:80]


# ===================================================================
# Real Agent generator
# ===================================================================

async def run_real_agent(
    message: str, message_type: str,
) -> AsyncGenerator[dict, None]:
    """Run the real 信噪 ReAct agent, yielding step + result messages."""

    # Injection guard
    guard = await asyncio.to_thread(check_injection, message)
    if guard["blocked"]:
        yield {
            "type": "result",
            "verdict": "safe", "confidence": 0.0,
            "summary": "这段话里有些奇怪的指令，我不吃这套。有正经问题直接问。",
            "advice": ["请重新输入需要检测的可疑消息"],
            "evidence": [],
        }
        return

    # Fresh conversation (no history carry-over for web sessions)
    messages: list[dict] = [
        {"role": "system", "content": SYSTEM_PROMPT},
        {"role": "user", "content": message},
    ]

    client = get_client()
    step_number = 0
    risk_result: dict | None = None
    evidence: list[dict] = []
    reply = ""

    for _ in range(MAX_STEPS):
        # ---- LLM call (blocking → thread) ----
        try:
            response = await asyncio.to_thread(
                client.chat.completions.create,
                model=MODEL,
                messages=messages,
                tools=tools,
            )
        except Exception as e:
            yield {"type": "error", "message": f"LLM 调用失败: {e}"}
            return

        msg = response.choices[0].message

        # ---- No tool calls → final reply ----
        if not msg.tool_calls:
            reply = clean_reply(msg.content)
            break

        thought = msg.content or ""
        messages.append(msg.to_dict())

        # ---- Process each tool call ----
        for tc in msg.tool_calls:
            name = tc.function.name
            try:
                args = json.loads(tc.function.arguments) if tc.function.arguments else {}
                raw_result = await asyncio.to_thread(tool_map[name], args)
            except Exception as e:
                raw_result = f"工具执行出错：{e}"

            tool_output = _parse_tool_result(raw_result)

            # Track risk_score for verdict
            if name == "risk_score" and "score" in tool_output:
                risk_result = tool_output

            evidence.append({"source": name, "finding": _summarize(name, tool_output)})

            step_number += 1
            yield {
                "type": "step",
                "step_number": step_number,
                "total_steps": MAX_STEPS,
                "thought": thought,
                "tool_name": name,
                "tool_input": args,
                "tool_output": tool_output,
                "timestamp": datetime.now(timezone.utc).isoformat(),
            }
            thought = ""  # only first tool call of each round carries the thought

            messages.append({
                "role": "tool",
                "tool_call_id": tc.id,
                "content": raw_result if isinstance(raw_result, str) else json.dumps(raw_result, ensure_ascii=False),
            })
    else:
        reply = "想了半天没想明白 你换个方式问问"

    # ---- Build structured result ----
    score = risk_result.get("score") if risk_result else None
    verdict, confidence = _score_to_verdict(score)

    advice: list[str] = []
    if risk_result and risk_result.get("suggested_action"):
        # Split long suggested_action into sentences
        action = risk_result["suggested_action"]
        for part in action.replace("。", "。\n").split("\n"):
            part = part.strip()
            if part:
                advice.append(part)
    if not advice:
        advice = ["建议通过官方渠道核实相关信息"]

    yield {
        "type": "result",
        "verdict": verdict,
        "confidence": confidence,
        "summary": reply,
        "advice": advice,
        "evidence": evidence,
    }


# ===================================================================
# Mock Agent (fallback)
# ===================================================================

MOCK_STEPS = [
    {
        "thought": "这条消息包含可疑链接，需要先用 risk_score 评估风险等级...",
        "tool_name": "risk_score",
        "tool_input": {"scenario": ""},
        "tool_output": {
            "score": 85,
            "signals": ["紧急催促用词", "包含可疑短链接", "要求提供个人信息"],
            "suggestion": "高风险，建议立即标记",
        },
    },
    {
        "thought": "风险评分较高，需要在知识库中查找是否有匹配的已知诈骗模式...",
        "tool_name": "search_knowledge",
        "tool_input": {"query": "冒充银行验证身份 短信诈骗"},
        "tool_output": {
            "matches": [{"id": "pattern-bank-impersonation", "title": "冒充银行客服诈骗", "similarity": 0.92}],
            "quality_hint": "high_confidence",
        },
    },
    {
        "thought": "知识库确认为已知诈骗模式，再搜索一下最近是否有类似案例的新闻报道...",
        "tool_name": "web_search",
        "tool_input": {"query": "2026年 冒充银行短信诈骗 最新案例"},
        "tool_output": {
            "results": [{"title": "多地出现冒充银行短信诈骗新变种", "url": "https://example.com/news/123"}],
        },
    },
]

MOCK_RESULT = {
    "verdict": "high_risk",
    "confidence": 0.96,
    "summary": "这是一条高风险钓鱼短信。消息包含多个诈骗信号：紧急催促用词、可疑链接、要求验证身份。匹配已知诈骗模式「冒充银行客服」，近期多地有类似案例报道。",
    "advice": [
        "不要点击消息中的任何链接",
        "直接拨打银行官方客服电话确认",
        "将此短信举报至 12321 不良信息举报平台",
        "如已点击链接或输入信息，立即联系银行冻结账户",
    ],
    "evidence": [
        {"source": "risk_score", "finding": "风险评分 85/100，命中 3 项高危信号"},
        {"source": "search_knowledge", "finding": "匹配已知诈骗模式：冒充银行客服（相似度 0.92）"},
        {"source": "web_search", "finding": "2026年多地出现同类诈骗短信新变种"},
    ],
}


async def run_mock_agent(
    message: str, message_type: str,
) -> AsyncGenerator[dict, None]:
    total_steps = len(MOCK_STEPS)
    for i, step in enumerate(MOCK_STEPS, 1):
        await asyncio.sleep(1.2)
        data = step.copy()
        if step["tool_name"] == "risk_score":
            data["tool_input"] = {"scenario": message}
        yield {
            "type": "step",
            "step_number": i, "total_steps": total_steps,
            "thought": data["thought"], "tool_name": data["tool_name"],
            "tool_input": data["tool_input"], "tool_output": data["tool_output"],
            "timestamp": datetime.now(timezone.utc).isoformat(),
        }
    await asyncio.sleep(0.5)
    yield {"type": "result", **MOCK_RESULT}


# ===================================================================
# Public entry: auto-select real or mock
# ===================================================================

async def run_agent(
    message: str, message_type: str,
) -> AsyncGenerator[dict, None]:
    """Public API — uses the real 信噪 agent if available, else mock."""
    gen = (
        run_real_agent(message, message_type)
        if _REAL_AGENT_AVAILABLE
        else run_mock_agent(message, message_type)
    )
    async for msg in gen:
        yield msg
