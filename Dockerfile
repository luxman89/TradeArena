# syntax=docker/dockerfile:1

# ---------- Stage 1: build ----------
FROM python:3.12-slim AS builder

# Install uv for fast dependency resolution
COPY --from=ghcr.io/astral-sh/uv:latest /uv /usr/local/bin/uv

WORKDIR /app

# Copy dependency files first for layer caching
COPY pyproject.toml uv.lock ./

# Install production dependencies (no dev group)
RUN uv sync --frozen --no-dev --no-install-project

# Copy application source
COPY README.md ./
COPY src/ src/
COPY sdk/ sdk/
COPY scripts/ scripts/
COPY alembic/ alembic/
COPY alembic.ini ./

# Install the project itself
RUN uv sync --frozen --no-dev

# ---------- Stage 2: runtime ----------
FROM python:3.12-slim AS runtime

# Non-root user for security
RUN groupadd --gid 1000 arena && \
    useradd --uid 1000 --gid arena --shell /bin/bash --create-home arena

WORKDIR /app

# Copy the virtual environment and source from builder
COPY --from=builder /app/.venv /app/.venv
COPY --from=builder /app/src /app/src
COPY --from=builder /app/sdk /app/sdk
COPY --from=builder /app/scripts /app/scripts
COPY --from=builder /app/alembic /app/alembic
COPY --from=builder /app/alembic.ini /app/alembic.ini

# Put venv on PATH
ENV PATH="/app/.venv/bin:$PATH" \
    PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1

# Alembic + uvicorn entrypoint
EXPOSE 8000

# Switch to non-root
USER arena

ENV PORT=8000

HEALTHCHECK --interval=30s --timeout=5s --start-period=10s --retries=3 \
    CMD python -c "import os,urllib.request; urllib.request.urlopen(f'http://localhost:{os.environ.get(\"PORT\",8000)}/health')"

# Run migrations then start server (PORT is set by Railway/Fly.io at runtime)
CMD ["sh", "-c", "alembic upgrade head && uvicorn tradearena.api.main:app --host 0.0.0.0 --port ${PORT:-8000} --no-server-header"]
