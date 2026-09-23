FROM python:3.12-slim

# ------------------------------------------------------------
# System packages
# ------------------------------------------------------------

RUN apt-get update && apt-get install -y --no-install-recommends \
    ffmpeg \
    ca-certificates \
    curl \
    unzip \
    git \
    && rm -rf /var/lib/apt/lists/*


# ------------------------------------------------------------
# Install Deno
# ------------------------------------------------------------

RUN curl -fsSL -o /tmp/deno.zip \
    https://github.com/denoland/deno/releases/latest/download/deno-x86_64-unknown-linux-gnu.zip \
    && unzip -q /tmp/deno.zip -d /usr/local/bin \
    && chmod +x /usr/local/bin/deno \
    && rm /tmp/deno.zip


# ------------------------------------------------------------
# App
# ------------------------------------------------------------

WORKDIR /app


# ------------------------------------------------------------
# Python dependencies
# ------------------------------------------------------------

COPY requirements.txt .

RUN pip install --no-cache-dir -r requirements.txt


# ------------------------------------------------------------
# BgUtils 2.0.0
# ------------------------------------------------------------

RUN git clone \
    --depth 1 \
    --branch 2.0.0 \
    https://github.com/Brainicism/bgutil-ytdlp-pot-provider.git \
    /opt/bgutil-ytdlp-pot-provider


# ------------------------------------------------------------
# Install BgUtils server dependencies
# ------------------------------------------------------------

WORKDIR /opt/bgutil-ytdlp-pot-provider/server

RUN deno install \
    --allow-scripts=npm:canvas \
    --frozen


# ------------------------------------------------------------
# Return to application
# ------------------------------------------------------------

WORKDIR /app

COPY server.py .


# ------------------------------------------------------------
# Environment
# ------------------------------------------------------------

ENV PORT=10000
ENV BGUTIL_PORT=4416

EXPOSE 10000


# ------------------------------------------------------------
# Start BgUtils + FastAPI
# ------------------------------------------------------------

CMD ["sh", "-c", "\
cd /opt/bgutil-ytdlp-pot-provider/server/node_modules && \
deno run \
--allow-env \
--allow-net \
--allow-ffi=. \
--allow-read=. \
../src/main.ts \
--host 127.0.0.1 \
--port ${BGUTIL_PORT} & \
uvicorn server:app \
--host 0.0.0.0 \
--port ${PORT} \
"]
