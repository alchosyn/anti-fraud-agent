# 反诈 Agent 后端镜像（FastAPI + 信噪 ReAct agent）
#
# 体积说明：agent 的 RAG 依赖 sentence-transformers/torch。必须用 PyTorch 官方
# CPU wheel index 安装 torch（~900MB），否则 Linux 默认拉 CUDA 全家桶（~3GB）。
# embedding 模型在构建期预下载进镜像，运行时零下载、可离线启动。
#
# 国内构建提速：
#   docker build --build-arg HF_ENDPOINT=https://hf-mirror.com \
#                --build-arg PIP_INDEX=https://pypi.tuna.tsinghua.edu.cn/simple .

FROM python:3.12-slim

ARG PIP_INDEX=https://pypi.org/simple
ARG HF_ENDPOINT=https://huggingface.co

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    HF_HOME=/opt/hf-cache

WORKDIR /app

# 1) CPU 版 torch（固定走 CPU wheel index，避免 CUDA 依赖）
RUN pip install --no-cache-dir "torch>=2.2" \
    --index-url https://download.pytorch.org/whl/cpu \
    --extra-index-url ${PIP_INDEX}

# 2) 业务依赖（agent 核心 + 后端，分开命名避免覆盖）
COPY requirements.txt /tmp/agent-requirements.txt
COPY backend/requirements.txt /tmp/backend-requirements.txt
RUN pip install --no-cache-dir -i ${PIP_INDEX} \
    -r /tmp/agent-requirements.txt -r /tmp/backend-requirements.txt

# 3) 预下载 embedding 模型（HF_ENDPOINT 可切镜像站）
RUN HF_ENDPOINT=${HF_ENDPOINT} python -c \
    "from sentence_transformers import SentenceTransformer; SentenceTransformer('paraphrase-multilingual-MiniLM-L12-v2')" \
    && chmod -R a+rX ${HF_HOME}

# 4) 代码与知识库（evals/训练脚本/前端不进镜像）
COPY src/ ./src/
COPY backend/ ./backend/
COPY data/knowledge_base.json ./data/knowledge_base.json

# 5) 非 root 运行
RUN useradd -m appuser && chown -R appuser:appuser /app
USER appuser

EXPOSE 8000

HEALTHCHECK --interval=15s --timeout=3s --start-period=20s --retries=3 \
    CMD python -c "import urllib.request,sys; sys.exit(0 if urllib.request.urlopen('http://127.0.0.1:8000/api/healthz', timeout=2).status==200 else 1)"

# 待处理会话已存 Redis，多 worker 安全；默认 1 worker（embedding 模型每 worker 各占 ~500MB 内存）
CMD ["sh", "-c", "uvicorn backend.main:app --host 0.0.0.0 --port 8000 --workers ${UVICORN_WORKERS:-1}"]
