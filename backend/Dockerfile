# =============================================================================
# Pin 后端镜像（CPU / GPU 双变体，多阶段构建）
#
# 构建（build context = 仓库根，widget 阶段需要 frontend/ 源码）：
#   CPU（默认）: docker build -f backend/Dockerfile -t pin-backend:cpu .
#   GPU        : docker build -f backend/Dockerfile --target runtime-gpu -t pin-backend:gpu .
#
# 运行（⚠️ 必须挂载 config.yaml —— core/config.py 在 import 时强制读取，否则启动即崩）：
#   docker run -d --name pin-backend -p 8000:8000 \
#     -e DATABASE_URL="postgresql+asyncpg://user:pass@host:5432/pin" \
#     -e CHECKPOINT_URL="postgresql://user:pass@host:5432/pin" \
#     -e JWT_SECRET_KEY="<生产密钥>" \
#     -e ADMIN_USERNAME=... -e ADMIN_PASSWORD=... \
#     -v ./config.yaml:/app/backend/config.yaml:ro \
#     -v pin-uploads:/app/uploads -v pin-logs:/app/logs \
#     -v pin-models:/app/backend/local_models \
#     pin-backend:cpu
#
# 环境变量覆盖链路复用 core/config.py 现有机制，零代码改动：
#   DATABASE_URL / CHECKPOINT_URL / JWT_SECRET_KEY / ADMIN_USERNAME / ADMIN_PASSWORD / LOG_DIR
# 数据卷：uploads=上传文件  logs=日志  local_models=本地模型缓存（首次运行自动下载）
# =============================================================================

# ── 阶段 ①：构建 widget.js（后端 /widget 静态托管，产物随镜像版本一致）───────
FROM node:22-alpine AS widget-builder
WORKDIR /pin/frontend
COPY frontend/package.json frontend/package-lock.json ./
RUN npm ci
COPY frontend/ ./
# vite.widget.config.ts 输出到 ../backend/static/widget/widget.js → /pin/backend/static/widget
RUN npm run build:widget

# ── 阶段 ②：CPU 依赖 ────────────────────────────────────────────────────────
# --no-sources 忽略 pyproject 钉的 cu128 源重新解析：torch 落 PyPI 版
# （Linux PyPI torch 自带 CUDA 运行时依赖，无 GPU 时 resolve_local_device 自动降级
#   CPU，功能完整；与 GPU 变体差异仅在 cu12x/cu128 构建与镜像体积）
FROM python:3.12-slim AS deps-cpu
COPY --from=ghcr.io/astral-sh/uv:latest /uv /uvx /bin/
WORKDIR /app
COPY pyproject.toml uv.lock ./
RUN uv sync --no-sources --no-dev --no-install-project

# ── 阶段 ③：GPU 依赖 ────────────────────────────────────────────────────────
# uv sync --frozen 忠实按锁文件安装（torch 走 pyproject 钉的 cu128 index）；
# cu128 wheel 自带 CUDA 运行时库（nvidia-* pip 包），无需 nvidia/cuda 基础镜像，
# 宿主机仅需 NVIDIA 驱动 + nvidia-container-toolkit（docker run --gpus all）
FROM python:3.12-slim AS deps-gpu
COPY --from=ghcr.io/astral-sh/uv:latest /uv /uvx /bin/
WORKDIR /app
COPY pyproject.toml uv.lock ./
RUN uv sync --frozen --no-dev --no-install-project

# ── 阶段 ④：GPU 运行层（docker build --target runtime-gpu）──────────────────
FROM deps-gpu AS runtime-gpu
RUN apt-get update \
 && apt-get install -y --no-install-recommends tzdata curl libgomp1 \
 && rm -rf /var/lib/apt/lists/* \
 && ln -sf /usr/share/zoneinfo/Asia/Shanghai /etc/localtime \
 && echo "Asia/Shanghai" > /etc/timezone
ENV TZ=Asia/Shanghai
ENV PATH="/app/.venv/bin:${PATH}"
WORKDIR /app
COPY backend/ ./backend/
COPY --from=widget-builder /pin/backend/static/widget ./backend/static/widget
EXPOSE 8000
HEALTHCHECK --interval=30s --timeout=5s --start-period=30s --retries=3 \
  CMD curl -fsS http://localhost:8000/docs || exit 1
CMD ["uvicorn", "backend.main:app", "--host", "0.0.0.0", "--port", "8000"]

# ── 阶段 ⑤：CPU 运行层（默认 target：最后声明 = CPU）────────────────────────
FROM deps-cpu AS runtime-cpu
RUN apt-get update \
 && apt-get install -y --no-install-recommends tzdata curl libgomp1 \
 && rm -rf /var/lib/apt/lists/* \
 && ln -sf /usr/share/zoneinfo/Asia/Shanghai /etc/localtime \
 && echo "Asia/Shanghai" > /etc/timezone
ENV TZ=Asia/Shanghai
ENV PATH="/app/.venv/bin:${PATH}"
WORKDIR /app
COPY backend/ ./backend/
COPY --from=widget-builder /pin/backend/static/widget ./backend/static/widget
EXPOSE 8000
HEALTHCHECK --interval=30s --timeout=5s --start-period=30s --retries=3 \
  CMD curl -fsS http://localhost:8000/docs || exit 1
CMD ["uvicorn", "backend.main:app", "--host", "0.0.0.0", "--port", "8000"]
