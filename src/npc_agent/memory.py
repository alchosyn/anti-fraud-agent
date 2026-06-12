"""会话记忆：超长对话的摘要压缩 + chat_history 持久化。

人设提示词在 persona.py；跨会话向量记忆在 long_memory.py。
"""

import json

from .config import HISTORY_FILE, MAX_MESSAGES, MODEL
from .llm_client import get_client
from .long_memory import save_memory
from .persona import SYSTEM_PROMPT


def summarize_messages(messages: list[dict]) -> list[dict]:
    old_messages = messages[1:-4]
    if not old_messages:
        return messages

    conversation_text = ""
    for m in old_messages:
        role = m.get("role", "")
        content = m.get("content", "")
        if role in ("user", "assistant") and content:
            label = "用户" if role == "user" else "信噪"
            conversation_text += f"{label}：{content}\n"

    try:
        response = get_client().chat.completions.create(
            model=MODEL,
            messages=[
                {
                    "role": "system",
                    "content": (
                        "你是一个记忆助手。把以下对话提炼成几条关键信息，"
                        "只保留重要的事实、偏好和约定。用简短的中文列出，不要废话。"
                    ),
                },
                {"role": "user", "content": conversation_text},
            ],
        )
        summary = response.choices[0].message.content.strip()
        save_memory(summary)
    except Exception as e:
        print(f"[system] 摘要生成失败：{e}")
        return messages

    system_with_memory = SYSTEM_PROMPT + f"\n\n【长期记忆】以下是之前对话的关键信息：\n{summary}"

    keep = messages[-4:]

    # If the kept window starts with a tool message, its paired assistant
    # (with tool_calls) was sliced off — walk back until we include it.
    while keep and keep[0].get("role") == "tool":
        idx = len(messages) - len(keep) - 1
        if idx < 1:
            break
        keep = [messages[idx]] + keep

    return [{"role": "system", "content": system_with_memory}] + keep


def save_messages(messages: list[dict]) -> list[dict]:
    if len(messages) > MAX_MESSAGES:
        print("[system] 记忆压缩中...")
        messages = summarize_messages(messages)
    with open(HISTORY_FILE, "w", encoding="utf-8") as f:
        json.dump(messages, f, ensure_ascii=False, indent=2)
    return messages


def load_messages() -> list[dict]:
    try:
        with open(HISTORY_FILE, encoding="utf-8") as f:
            return json.load(f)
    except FileNotFoundError:
        return [{"role": "system", "content": SYSTEM_PROMPT}]
