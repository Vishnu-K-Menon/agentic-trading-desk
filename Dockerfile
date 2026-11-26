# Agentic Trading Desk: one container serving the API, the scheduler and the built frontend.
# Made for a Hugging Face Docker Space (port 7860, runs as user 1000).

FROM node:20-slim AS frontend
WORKDIR /build
COPY frontend/package.json frontend/package-lock.json ./
RUN npm ci --no-audit --no-fund
COPY frontend/ ./
RUN npm run build

FROM python:3.12-slim

ENV PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    PLAYWRIGHT_BROWSERS_PATH=/opt/playwright \
    FASTEMBED_CACHE_PATH=/opt/fastembed

# Node runs the MCP servers that ship as npm packages (web search and the knowledge graph).
RUN apt-get update \
    && apt-get install -y --no-install-recommends curl ca-certificates git gnupg libatomic1 \
    && curl -fsSL https://deb.nodesource.com/setup_20.x | bash - \
    && apt-get install -y --no-install-recommends nodejs \
    && rm -rf /var/lib/apt/lists/*

COPY requirements.txt /tmp/requirements.txt
RUN pip install -r /tmp/requirements.txt \
    && playwright install --with-deps chromium \
    && python -c "from fastembed import TextEmbedding; TextEmbedding('sentence-transformers/all-MiniLM-L6-v2')" \
    && chmod -R a+rX /opt/playwright /opt/fastembed

RUN useradd -m -u 1000 user
USER user
ENV HOME=/home/user \
    PATH=/home/user/.local/bin:$PATH \
    DATA_DIR=/home/user/app/data \
    USE_BROWSER=true
WORKDIR /home/user/app

COPY --chown=user backend ./backend
COPY --chown=user --from=frontend /build/dist ./frontend/dist

EXPOSE 7860
# Bring back the last backup (if one is configured), then start the floor. If a backup exists but
# cannot be read, stop rather than start blank and save over it.
CMD ["sh", "-c", "python -m backend.backup restore && exec uvicorn backend.api:app --host 0.0.0.0 --port 7860"]
