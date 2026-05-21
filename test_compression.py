"""
自动跑多轮对话，观察 memory 压缩的完整过程。
"""
import json
import os
import sys

LOG_FILE = "compression_test_log.txt"
log_f = open(LOG_FILE, "w", encoding="utf-8")

# 重定向 stdout/stderr，让源码里的 print 也不会炸
sys.stdout = log_f
sys.stderr = log_f

def log(msg=""):
    log_f.write(str(msg) + "\n")
    log_f.flush()

# 先清掉旧的 chat_history，保证干净环境
HISTORY_FILE = "chat_history.json"
if os.path.exists(HISTORY_FILE):
    os.rename(HISTORY_FILE, "chat_history_backup.json")
    log("[setup] backed up old chat_history.json")

from src.npc_agent.agent import step
from src.npc_agent.memory import load_messages, SYSTEM_PROMPT
from src.npc_agent.config import MAX_MESSAGES

inputs = [
    "你是谁",
    "你多大了",
    "你会什么",
    "现在几点了",
    "帮我查一下杀猪盘是什么",
    "我收到一条短信说中奖了，可信吗",
    "密码怎么设才安全",
    "你觉得人工智能会取代人类吗",
    "怎么判断一个链接是不是钓鱼网站",
    "最近有什么新型诈骗手法",
    "我的手机号泄露了怎么办",
    "什么是社会工程学攻击",
]

messages = load_messages()
log(f"[init] MAX_MESSAGES = {MAX_MESSAGES}")
log(f"[init] initial message count: {len(messages)}")
log("=" * 60)

for i, user_input in enumerate(inputs, 1):
    before_count = len(messages)

    log(f"\n--- Round {i} ---")
    log(f"[input] {user_input}")
    log(f"[before] message count: {before_count}")

    # 记录压缩前的完整 roles
    roles_before = [m.get("role", "?") for m in messages]
    log(f"[before roles] {roles_before}")

    reply, messages = step(messages, user_input)

    after_count = len(messages)
    log(f"[reply] {reply[:120]}{'...' if len(reply) > 120 else ''}")
    log(f"[after] message count: {after_count}")

    # 检测压缩：如果 step 内部触发了压缩，after_count 会比 before_count+2 小很多
    expected = before_count + 2  # normal: +1 user +1 assistant (minimum)
    if after_count < expected - 2:
        log(f"  *** COMPRESSION TRIGGERED! before={before_count} -> after={after_count} ***")

    roles_after = [m.get("role", "?") for m in messages]
    log(f"[after roles] {roles_after}")

    sys_content = messages[0].get("content", "")
    has_memory = "长期记忆" in sys_content or "历史记忆" in sys_content
    log(f"[system prompt has memory] {has_memory}")

log()
log("=" * 60)
log(f"[done] final message count: {len(messages)}")
log(f"[done] final roles: {[m.get('role', '?') for m in messages]}")

sys_content = messages[0].get("content", "")
for marker in ["【长期记忆】", "【历史记忆】"]:
    idx = sys_content.find(marker)
    if idx != -1:
        log(f"\n[system prompt memory section]\n{sys_content[idx:]}")
        break

sys.stdout = sys.__stdout__
sys.stderr = sys.__stderr__
log_f.close()
print(f"Done. Log written to {LOG_FILE}")
