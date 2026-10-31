# ---- Stage 1: build the Vue frontend ----
FROM node:20-alpine AS frontend
WORKDIR /app/frontend
COPY frontend/package.json frontend/pnpm-lock.yaml* ./
RUN corepack enable && corepack prepare pnpm@9 --activate && pnpm install --frozen-lockfile || pnpm install
COPY frontend/ ./
RUN pnpm build

# ---- Stage 2: Python server ----
FROM python:3.11-slim AS runtime
WORKDIR /app

# runtime deps only (httpx is core; fastapi/uvicorn serve the web UI)
RUN pip install --no-cache-dir "httpx>=0.24" "fastapi>=0.100" "uvicorn>=0.23"

# copy the package + prebuilt frontend dist
COPY agentree/ /app/agentree/
COPY --from=frontend /app/frontend/dist /app/frontend/dist

# demo mode on by default so the container runs with no external auth
ENV AGENTREE_DEMO_AUTH=on
ENV AGENTREE_API_KEY=sk-change-me
ENV AGENTREE_BASE_URL=http://127.0.0.1:3065/v1
ENV AGENTREE_MODEL=deepseek-v4-flash
EXPOSE 8767

# override these at runtime for a real LLM gateway:
#   docker run -e AGENTREE_API_KEY=... -e AGENTREE_BASE_URL=... -e AGENTREE_MODEL=...
CMD ["python", "-m", "uvicorn", "agentree.server:app", "--host", "0.0.0.0", "--port", "8767"]
