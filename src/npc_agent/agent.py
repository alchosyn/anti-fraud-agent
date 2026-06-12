import json
import time

from .config import MAX_STEPS, MODEL
from .llm_client import get_client
from .long_memory import recall_memory
from .memory import load_messages, save_messages
from .tools import tool_map, tools
from .tools.input_guard import check_injection
from .tracing import log_llm_call, log_tool_call, new_trace, save_trace
from .utils import clean_reply


def step(
    messages: list[dict],
    user_input: str,
    *,
    active_tools: list[str] | None = None,
    use_long_memory: bool = True,
    persist: bool = True,
    temperature: float | None = None,
    trace_sink: dict | None = None,
) -> tuple[str, list[dict]]:
    """Run one turn: append user input, drive the ReAct loop, return (reply, messages).

    Keyword-only 参数全部用于评估/基准场景，默认值保持线上行为不变：
        active_tools:    None=开放全部工具；列表=只开放指定工具；[]=纯对话（不传 tools）
        use_long_memory: False 时跳过长期记忆注入（避免私人记忆污染评估）
        persist:         False 时不写 chat_history.json / trace 文件（并发跑评估安全）
        temperature:     None 用 API 默认；评估传 0.0 求稳定
        trace_sink:      传入 dict 则在返回前收到完整 trace（tokens/步骤/延迟）
    """
    if active_tools is None:
        selected_tools = tools
    else:
        known = {t["function"]["name"] for t in tools}
        unknown = set(active_tools) - known
        if unknown:
            raise ValueError(f"未知工具名: {sorted(unknown)}")
        selected_tools = [t for t in tools if t["function"]["name"] in set(active_tools)]

    # —— 系统护栏：Prompt Injection 检测 ——
    guard_result = check_injection(user_input)
    if guard_result["blocked"]:
        blocked_reply = "这段话里有些奇怪的指令，我不吃这套。有正经问题直接问。"
        messages.append({"role": "user", "content": user_input})
        messages.append({"role": "assistant", "content": blocked_reply})
        return blocked_reply, messages

    # —— 长期记忆：仅在全新会话（messages 只有 system prompt）时检索一次 ——
    if use_long_memory and len(messages) == 1:
        memories = recall_memory(user_input)
        if memories:
            memory_text = "\n".join(memories)
            messages[0]["content"] += f"\n\n【历史记忆】以下是过去对话中的相关信息：\n{memory_text}"
            print(f"[long_memory] 注入 {len(memories)} 条历史记忆")

    client = get_client()
    messages.append({"role": "user", "content": user_input})
    trace = new_trace(user_input)
    reply: str | None = None

    create_kwargs: dict = {"model": MODEL}
    if selected_tools:
        create_kwargs["tools"] = selected_tools
    if temperature is not None:
        create_kwargs["temperature"] = temperature

    for _ in range(MAX_STEPS):
        try:
            t0 = time.time()
            response = client.chat.completions.create(
                messages=messages,
                **create_kwargs,
            )
            log_llm_call(trace, response, int((time.time() - t0) * 1000))
        except Exception:
            reply = "……信号不太好 你再说一遍"
            break

        msg = response.choices[0].message

        if not msg.tool_calls:
            reply = clean_reply(msg.content)
            break

        if msg.content:
            print(f"[Thought] {msg.content}")

        messages.append(msg.to_dict())

        for tool_call in msg.tool_calls:
            name = tool_call.function.name
            try:
                args = json.loads(tool_call.function.arguments) if tool_call.function.arguments else {}
                t0 = time.time()
                result = tool_map[name](args)
                log_tool_call(trace, name, args, result, int((time.time() - t0) * 1000))
            except Exception as e:
                result = f"工具执行出错：{e}"

            messages.append({
                "role": "tool",
                "tool_call_id": tool_call.id,
                "content": result,
            })

    if reply is None:
        reply = "想了半天没想明白 你换个方式问问"

    messages.append({"role": "assistant", "content": reply})
    trace["agent_reply"] = reply
    if trace_sink is not None:
        trace_sink.update(trace)
    if persist:
        save_trace(trace, reply)
        messages = save_messages(messages)
    return reply, messages


def run_chat_loop() -> None:
    messages = load_messages()
    while True:
        user_input = input("你：")
        if user_input == "quit":
            break
        reply, messages = step(messages, user_input)
        print(f"信噪：{reply}")
