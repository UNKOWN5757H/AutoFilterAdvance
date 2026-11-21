# syntax=docker/dockerfile:1.7
# ============================================================
#   ULTRA-FAST PYROGRAM BOT DOCKERFILE (MULTI-STAGE + UV)
#   • ~5x-10x faster pip installs via Astral uv
#   • Tiny slim runtime image (no gcc/build tools in final layer)
#   • Pre-compiled .pyc bytecode for instant cold-start boot
# ============================================================

# --- Stage 1: Ultra-Fast Builder ---
FROM python:3.11-slim AS builder

ENV PYTHONDONTWRITEBYTECODE=1 \
    UV_COMPILE_BYTECODE=1 \
    UV_LINK_MODE=copy \
    UV_SYSTEM_PYTHON=1

RUN apt-get update && apt-get install -y --no-install-recommends \
    gcc \
    g++ \
    git \
    && rm -rf /var/lib/apt/lists/*

# Install Astral 'uv' (Rust-powered ultra-fast pip replacement)
COPY --from=ghcr.io/astral-sh/uv:latest /uv /usr/local/bin/uv

WORKDIR /app
COPY requirements.txt .

# Install all packages & pre-compile bytecode in seconds
RUN --mount=type=cache,target=/root/.cache/uv \
    uv pip install --system --no-cache -r requirements.txt

# --- Stage 2: Minimal Ultra-Fast Runtime ---
FROM python:3.11-slim

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    DEBIAN_FRONTEND=noninteractive \
    TZ=UTC \
    PORT=8080

# Only install curl for healthcheck (no compilers = tiny image & fast deploy pull)
RUN apt-get update && apt-get install -y --no-install-recommends \
    curl \
    tzdata \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

# Copy pre-built site-packages & binaries from builder
COPY --from=builder /usr/local/lib/python3.11/site-packages /usr/local/lib/python3.11/site-packages
COPY --from=builder /usr/local/bin /usr/local/bin

# Copy bot source code & pre-compile app bytecode for instant startup
COPY . .
RUN python3 -m compileall -q .

EXPOSE 8080

HEALTHCHECK --interval=30s --timeout=5s --start-period=15s --retries=3 \
    CMD curl -fsS "http://127.0.0.1:${PORT:-8080}/health" || exit 1

CMD ["python3", "-O", "bot.py"]
