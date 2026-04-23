# ===============================================================
#   TrackMaster - Backend Dockerfile
#
#   Uses Microsoft's official Playwright Python image which already
#   has Chromium + all system dependencies pre-installed, so the
#   build is fast and reliable.
# ===============================================================
FROM mcr.microsoft.com/playwright/python:v1.49.1-noble

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1 \
    DEBIAN_FRONTEND=noninteractive

# Install curl for healthchecks (everything else already there)
RUN apt-get update && apt-get install -y --no-install-recommends curl \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

# ---- Python deps (cached layer) ----
COPY requirements.txt ./
RUN pip install --upgrade pip setuptools wheel \
    && pip install -r requirements.txt

# ---- Copy source ----
COPY . .

EXPOSE 8001

CMD ["uvicorn", "server:app", "--host", "0.0.0.0", "--port", "8001"]
