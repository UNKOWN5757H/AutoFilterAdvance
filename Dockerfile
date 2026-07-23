# ================================
#   PYROGRAM TELEGRAM BOT IMAGE
#   Optimized for Speed & Stability
# ================================

# --- Base Image ---
FROM python:3.11-slim

# --- Environment Setup ---
ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    DEBIAN_FRONTEND=noninteractive \
    TZ=UTC

# --- Set Working Directory ---
WORKDIR /app

# --- Install Core System Dependencies ---
RUN apt-get update && apt-get install -y --no-install-recommends \
    build-essential \
    curl \
    wget \
    ffmpeg \
    git \
    tzdata \
    && apt-get clean \
    && rm -rf /var/lib/apt/lists/*

# --- Copy requirements first (for caching) ---
COPY requirements.txt .

# --- Install Python Dependencies ---
RUN pip install --upgrade pip setuptools wheel && \
    pip install --no-cache-dir \
        pymongo==4.6.3 \
        motor==3.3.2 \
        umongo==3.1.0 \
        marshmallow==3.26.2 \
        -r requirements.txt

# --- Copy Bot Source Code ---
COPY . .

# --- Expose Flask Keep-Alive Port ---
EXPOSE 8080

# --- Healthcheck (Koyeb / Docker) ---
HEALTHCHECK --interval=60s --timeout=10s --start-period=30s CMD curl -f http://localhost:8080/health || exit 1

# --- Run Gunicorn (for Flask) and Pyrogram Bot ---
# web_server:app  →  Flask app entry (must exist in web_server.py)
# python3 bot.py  →  main Telegram bot
CMD gunicorn web_server:app --bind 0.0.0.0:8080 --timeout 120 --log-level info & python3 bot.py
