FROM python:3.12-slim

# ============================================================
# OS 패키지
# ============================================================
RUN apt-get update && apt-get install -y --no-install-recommends \
    ffmpeg \
    ca-certificates \
    curl \
    unzip \
    git \
    && rm -rf /var/lib/apt/lists/*

# ============================================================
# Deno 2.9.5 (검증된 버전, 2026.08.06 릴리스)
# ============================================================
RUN curl -fsSL -o /tmp/deno.zip \
    https://github.com/denoland/deno/releases/download/v2.9.5/deno-x86_64-unknown-linux-gnu.zip \
    && unzip -q /tmp/deno.zip -d /usr/local/bin \
    && chmod +x /usr/local/bin/deno \
    && rm /tmp/deno.zip \
    && deno --version

# ============================================================
# BgUtils PO Token Provider
# ============================================================
RUN git clone \
    --single-branch \
    --branch 2.0.0 \
    https://github.com/Brainicism/bgutil-ytdlp-pot-provider.git \
    /opt/bgutil-ytdlp-pot-provider

WORKDIR /opt/bgutil-ytdlp-pot-provider/server

RUN deno install --allow-scripts=npm:canvas --frozen

# ============================================================
# Python 앱
# ============================================================
WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY server.py .

# ============================================================
# Runtime
# ============================================================
ENV PORT=10000
ENV BGUTIL_PORT=4416

EXPOSE 10000

# shell 형식 CMD (JSON 이스케이프 문제 회피)
CMD cd /opt/bgutil-ytdlp-pot-provider/server/node_modules && \
    deno run --allow-env --allow-net --allow-ffi=. --allow-read=. ../src/main.ts --host 127.0.0.1 --port ${BGUTIL_PORT} & \
    cd /app && \
    uvicorn server:app --host 0.0.0.0 --port ${PORT}
