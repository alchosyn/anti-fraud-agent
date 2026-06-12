# 简历 Bullet 素材（数字均为实测，可直接引用）

> 2026-06-12 全部数据已定稿（v2 评估 + 4 变体消融重跑完成，零污染）。

## 后端 / 工程向

- 将反诈 Agent Web 服务从 SQLite 重构为 **PostgreSQL + SQLAlchemy 2.0 async ORM**
  （用户/会话/消息/工具调用日志四表，级联外键 + JSONB + 复合索引），保持 REST/WS
  契约零破坏；以 **28 个零网络依赖的后端测试**（fakeredis + ASGI 直连）和
  **GitHub Actions 双 job CI** 保障回归
- 设计 **Redis 双层缓存**（分析结果缓存命中跳过整个 LLM ReAct 循环：6.7s/3k tokens
  → 毫秒级；工具结果缓存 24h TTL）与**手写固定窗口限流**（INCR+EXPIRE，登录
  10次/分/IP、分析 30次/时/用户，429+Retry-After，Redis 故障 fail-open）
- 压测定位 **同步 bcrypt 阻塞事件循环** 的瓶颈并以 asyncio.to_thread 修复：
  50 并发登录 **QPS 5.0 → 62.3（×12.5），P95 16.1s → 1.04s（−93.6%）**；
  读路径 278 QPS / P95 514ms；将待处理会话从进程内 dict 迁移至 Redis 原子
  GETDEL 交接，解锁多 worker 水平扩展
- **Docker Compose 三服务编排**（app+PostgreSQL+Redis，健康检查/CPU-torch 镜像/
  构建期预载 embedding 模型）+ Nginx 反代/HTTPS/WS 升级的 VPS 部署套件

## 评估 / Agent 向

- 在公开中文垃圾短信数据集（80 万条，分层采样 n=500、固定种子、dev/test 阈值
  纪律）上为 Agent 建立**客观 P/R/F1 基准**：规则引擎域外近随机（ROC-AUC 0.49）、
  裸 LLM F1 0.769 但误报率 44.8%、Agent 误报率降至 **9.6%（4.7×）** 而召回付出代价
  ——定位出**工具锚定改变精确率/召回率权衡**的机制并以逐字日志证实指令漂移现象
- 构建 **80 条带硬负例的评估集 v2**（52 诈骗/13 仿可疑合法消息/注入探针，
  LLM 生成 + 人工评审；全量 92.5% 规则通过、judge 4.42/5、规则-judge Spearman 0.51）
  与**四变体工具消融框架**（active_tools 参数化）：工具贡献 25pp content-pass
  （97.5%→72.5%）、citation 3.62→1.68，且硬负例误报率在去工具后增至 3 倍
  （92.3%→61.5% 通过）——与公开基准的"工具锚定"发现互为镜像证据；
  修复**私人长期记忆污染评估**的复现性 bug，judge 钉至带日期快照
  （gpt-4o-mini-2024-07-18, temp=0）
- 诚实呈现负面结果：GRPO 在 65-prompt 规模下相对 SFT 无总分提升（3.63 持平）的
  归因分析；reward 函数含反 hacking 设计（判 0.6 权重 + 假热线惩罚 + AI 味结构惩罚）

## 面试可讲的故事线（按提问概率排序）

1. **"为什么 agent 在公开基准上 F1 反而比裸 LLM 低？"** → 工具锚定 + 域外迁移 +
   精确率/召回率权衡（有逐字证据），以及"哪个系统更好取决于误报/漏报代价"
2. **"压测发现了什么？"** → 同步 bcrypt 卡事件循环 → to_thread + GIL 释放 →
   ×12.5；顺带讲 pending 会话 Redis 化解锁多 worker
3. **"GRPO 为什么没用？"** → 数据规模/reward 噪声/judge 偏置 → 反 hacking 惩罚设计
4. **"缓存怎么设计的？"** → 两层缓存的 key/TTL/失效语义 + fail-open 哲学
