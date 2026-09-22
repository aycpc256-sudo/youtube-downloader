FROM python:3.12-slim

# ---------------------------------------------------------
# System packages
# ---------------------------------------------------------

RUN apt-get update && apt-get install -y --no-install-recommends \
    ffmpeg \
    ca-certificates \
    curl \
    unzip \
    git \
    && rm -rf /var/lib/apt/lists/*


# ---------------------------------------------------------
# Deno
# ---------------------------------------------------------

RUN curl -fsSL -o /tmp/deno.zip \
    https://github.com/denoland/deno/releases/latest/download/deno-x86_64-unknown-linux-gnu.zip \
    && unzip -q /tmp/deno.zip -d /usr/local/bin \
    && chmod +x /usr/local/bin/deno \
    && rm /tmp/deno.zip


# ---------------------------------------------------------
# Working directory
# ---------------------------------------------------------

WORKDIR /app


# ---------------------------------------------------------
# Python dependencies
# ---------------------------------------------------------

COPY requirements.txt .

RUN pip install --no-cache-dir -r requirements.txt


# ---------------------------------------------------------
# bgutil PO Token Provider
# ---------------------------------------------------------

RUN git clone \
    --depth 1 \
    --branch 2.0.0 \
    https://github.com/Brainicism/bgutil-ytdlp-pot-provider.git \
    /opt/bgutil-ytdlp-pot-provider


# ---------------------------------------------------------
# Install bgutil server dependencies
# ---------------------------------------------------------

WORKDIR /opt/bgutil-ytdlp-pot-provider/server

RUN deno install \
    --allow-scripts=npm:canvas \
    --frozen


# ---------------------------------------------------------
# Return to application
# ---------------------------------------------------------

WORKDIR /app

COPY server.py .


# ---------------------------------------------------------
# Render
# ---------------------------------------------------------

ENV PORT=10000

EXPOSE 10000


# ---------------------------------------------------------
# Start:
# 1. bgutil POT server :4416
# 2. FastAPI           :$PORT
# ---------------------------------------------------------

CMD ["sh", "-c", "cd /opt/bgutil-ytdlp-pot-provider/server && deno run --allow-env --allow-net --allow-ffi=/opt/bgutil-ytdlp-pot-provider/server/node_modules --allow-read=/opt/bgutil-ytdlp-pot-provider/server/node_modules src/main.ts --host 127.0.0.1 --port 4416 & uvicorn server:app --host 0.0.0.0 --port ${PORT}"]
