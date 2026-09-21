FROM python:3.12-slim
RUN apt-get update && apt-get install -y --no-install-recommends ffmpeg ca-certificates curl unzip && rm -rf /var/lib/apt/lists/*
RUN curl -fsSL https://dl.deno.land/release/latest/deno-x86_64-unknown-linux-gnu.zip -o /tmp/deno.zip && unzip -q /tmp/deno.zip -d /usr/local/bin && chmod +x /usr/local/bin/deno && rm /tmp/deno.zip
WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
COPY server.py .
ENV PORT=10000
EXPOSE 10000
CMD ["sh","-c","uvicorn server:app --host 0.0.0.0 --port ${PORT}"]
