FROM python:3.12-slim

ENV DEBIAN_FRONTEND=noninteractive
ENV PORT=10000
ENV BGUTIL_PORT=4416
ENV DENO_NO_UPDATE_CHECK=1

# ---------------------------------------------------------
# 시스템 패키지
# ---------------------------------------------------------
RUN apt-get update && apt-get install -y --no-install-recommends \
    ffmpeg \
    ca-certificates \
    curl \
    unzip \
    git \
    && rm -rf /var/lib/apt/lists/*

# ---------------------------------------------------------
# Deno 설치 (PO Token 생성용 JavaScript 런타임)
# ---------------------------------------------------------
RUN curl -fsSL -o /tmp/deno.zip \
    https://github.com/denoland/deno/releases/latest/download/deno-x86_64-unknown-linux-gnu.zip \
    && unzip -q /tmp/deno.zip -d /usr/local/bin \
    && chmod +x /usr/local/bin/deno \
    && rm /tmp/deno.zip

# ---------------------------------------------------------
# BgUtils POT Provider 서버 설치 (플러그인과 동일한 2.0.0)
# - --single-branch --branch 2.0.0 --depth 1 로 정확히 지정
# ---------------------------------------------------------
WORKDIR /opt
RUN git clone --single-branch --branch 2.0.0 --depth 1 \
    https://github.com/Brainicism/bgutil-ytdlp-pot-provider.git bgutil

WORKDIR /opt/bgutil/server
RUN deno install --allow-scripts=npm:canvas --frozen

# ---------------------------------------------------------
# FastAPI 애플리케이션
# ---------------------------------------------------------
WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY server.py .

EXPOSE 10000

# ---------------------------------------------------------
# bgutil POT 서버 :4416 + FastAPI :$PORT 동시 실행
# - deno run ... ../src/main.ts --host 127.0.0.1 --port 4416
# ---------------------------------------------------------
CMD ["sh", "-c", "cd /opt/bgutil/server && deno run --allow-env --allow-net --allow-ffi=. --allow-read=. ../src/main.ts --host 127.0.0.1 --port ${BGUTIL_PORT} & uvicorn server:app --host 0.0.0.0 --port ${PORT}"]
