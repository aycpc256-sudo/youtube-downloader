FROM python:3.11-slim

ENV PYTHONUNBUFFERED=1
ENV PYTHONDONTWRITEBYTECODE=1

RUN apt-get update \
    && apt-get install -y --no-install-recommends \
        ffmpeg \
        curl \
        ca-certificates \
    && rm -rf /var/lib/apt/lists/*

# =========================================================
# Deno 2.x
# =========================================================

RUN curl -fsSL https://deno.land/install.sh \
    | DENO_INSTALL=/usr/local sh -s v2.1.4

RUN /usr/local/bin/deno --version

# =========================================================

WORKDIR /app

COPY requirements.txt .

RUN pip install \
    --no-cache-dir \
    -r requirements.txt

COPY server.py .

ENV PORT=8080

EXPOSE 8080

CMD ["sh", "-c", "uvicorn server:app --host 0.0.0.0 --port ${PORT}"]
