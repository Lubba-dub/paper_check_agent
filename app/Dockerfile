# ==========================================================
# Article Check — Docker 多阶段构建
# 前端在镜像内构建，后端镜像只保留运行时依赖与前端产物。
# ==========================================================

ARG FRONTEND_BASE=node:20-alpine
ARG RUNTIME_BASE=python:3.12-slim

# ─── Stage 1: Frontend deps ──────────────────────────────
FROM ${FRONTEND_BASE} AS frontend-deps

WORKDIR /frontend
COPY article_check/web/frontend/package.json article_check/web/frontend/package-lock.json ./
RUN npm ci

# ─── Stage 2: Frontend build ─────────────────────────────
FROM ${FRONTEND_BASE} AS frontend-builder

WORKDIR /frontend
COPY --from=frontend-deps /frontend/node_modules /frontend/node_modules
COPY article_check/web/frontend/ /frontend/
RUN npm run build

# ─── Stage 3: Backend runtime ────────────────────────────
FROM ${RUNTIME_BASE} AS runtime

LABEL maintainer="ShaoPaodiao <18519101256@163.com>"
LABEL description="Article Check — 学术论文审查智能体 Web 服务"
LABEL version="0.3.0"

RUN apt-get update && apt-get install -y --no-install-recommends \
    curl \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

COPY pyproject.toml requirements.txt README.md ./
COPY article_check/ /app/article_check/
COPY dify_api.example.md /app/dify_api.example.md
COPY dify_dsl/ /app/dify_dsl/
COPY 北师大论文格式要求/ /app/北师大论文格式要求/

RUN pip install --no-cache-dir -r requirements.txt && \
    pip install --no-cache-dir .

COPY --from=frontend-builder /frontend/dist /app/article_check/web/frontend/dist

RUN mkdir -p /app/reports /app/uploads /app/.worktrees /app/.article_check/offline_indices

EXPOSE 8000

ENV ARTICLE_CHECK_ROOT=/app
ENV PYTHONPATH=/app

HEALTHCHECK --interval=30s --timeout=5s --start-period=15s --retries=3 \
    CMD curl -sf http://localhost:8000/api/health || exit 1

CMD ["uvicorn", "article_check.web.server:app", "--host", "0.0.0.0", "--port", "8000", "--workers", "2"]
