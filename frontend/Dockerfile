# =============================================================================
# Pin 前端镜像（管理后台静态托管 + /api、/widget 反向代理）
#
# 构建：docker build -f frontend/Dockerfile -t pin-frontend:latest frontend
# 运行：docker run -d --name pin-frontend -p 80:80 \
#         -e BACKEND_HOST=backend pin-frontend:latest
#（BACKEND_HOST 为后端容器地址，默认 compose 服务名 backend，运行时可 -e 覆盖）
# =============================================================================

# ── 阶段 ①：构建 dist（vue-tsc 类型检查 + vite build）────────────────────────
FROM node:22-alpine AS builder
WORKDIR /build
COPY package.json package-lock.json ./
RUN npm ci
COPY . .
# 先 vite build：同时生成 auto-imports.d.ts / components.d.ts 类型声明（生成物不入 build context）；
# 再 vue-tsc 全量类型检查作门禁——与本地 npm run build 顺序相反，但 tsc 失败同样阻断镜像产出
RUN npx vite build && npx vue-tsc --noEmit

# ── 阶段 ②：nginx 运行层 ───────────────────────────────────────────────────
FROM nginx:1.27-alpine
COPY --from=builder /build/dist /usr/share/nginx/html
# 官方 templates 机制：启动时自动 envsubst 渲染 ${BACKEND_HOST} → conf.d/default.conf
COPY nginx/default.conf.template /etc/nginx/templates/default.conf.template
ENV BACKEND_HOST=backend
EXPOSE 80
