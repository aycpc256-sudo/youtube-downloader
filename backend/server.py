import base64
import os
import re
import shutil
import tempfile
from pathlib import Path
from urllib.parse import urlparse

import yt_dlp
from fastapi import FastAPI, HTTPException, Query
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from starlette.background import BackgroundTask

app = FastAPI(title="Personal YouTube Downloader API")

ALLOWED_ORIGINS = [
    "https://aycpc256-sudo.github.io",
    "http://localhost:8000",
    "http://127.0.0.1:8000",
]

app.add_middleware(
    CORSMiddleware,
    allow_origins=ALLOWED_ORIGINS,
    allow_methods=["GET", "OPTIONS"],
    allow_headers=["*"],
    expose_headers=["Content-Disposition", "Content-Length", "Content-Type"],
)

HOSTS = {"youtube.com", "www.youtube.com", "m.youtube.com", "youtu.be"}

COOKIE_FILE = "/tmp/youtube-cookies.txt"

def prepare_cookies():
    encoded = os.environ.get("YT_COOKIES_B64", "").strip()
    if not encoded:
        return None
    try:
        data = base64.b64decode(encoded, validate=True)
        Path(COOKIE_FILE).write_bytes(data)
        return COOKIE_FILE
    except Exception as e:
        print("Cookie preparation failed:", e)
        return None

COOKIE_PATH = prepare_cookies()

def validate_youtube_url(url: str):
    parsed = urlparse(url)
    hostname = (parsed.hostname or "").lower()
    if parsed.scheme not in {"http", "https"}:
        raise HTTPException(400, "http 또는 https 주소만 사용할 수 있습니다.")
    if hostname not in HOSTS:
        raise HTTPException(400, "YouTube 주소만 사용할 수 있습니다.")
    return url

def safe_filename(name: str):
    name = re.sub(r'[<>:"/\\|?*\x00-\x1f]', "_", name).strip(" .")
    return (name or "download")[:180]

def base_options(tmp_dir: str):
    options = {
        "outtmpl": str(Path(tmp_dir) / "%(title)s.%(ext)s"),
        "noplaylist": True,
        "quiet": True,
        "no_warnings": True,
        "retries": 3,
        "fragment_retries": 3,
        "continuedl": True,
        # PO Token Provider
        "extractor_args": {
            "youtube": {
                "player_client": ["mweb"],
            },
            "youtubepot-bgutilhttp": {
                "base_url": ["http://127.0.0.1:4416"],
            },
        },
        # Deno JS runtime
        "js_runtimes": {"deno": {}},
        "remote_components": {"ejs": ["github"]},
    }
    if COOKIE_PATH and os.path.isfile(COOKIE_PATH):
        options["cookiefile"] = COOKIE_PATH
    return options

@app.get("/api/health")
def health():
    return {
        "ok": True,
        "service": "youtube-downloader",
        "yt_dlp": getattr(yt_dlp, "__version__", "unknown"),
        "cookies": bool(COOKIE_PATH),
        "pot_provider": True,
    }

@app.get("/api/download")
def download(
    url: str = Query(..., min_length=10),
    format: str = Query("mp3", pattern="^(mp3|mp4)$"),
    quality: str = Query("192"),
):
    validate_youtube_url(url)
    tmp_dir = tempfile.mkdtemp(prefix="ytdl_")
    try:
        options = base_options(tmp_dir)

        if format == "mp3":
            q = re.sub(r"\D", "", quality)
            if q not in {"320", "256", "192", "128", "96"}:
                q = "192"
            options.update({
                "format": "bestaudio/best",
                "postprocessors": [{
                    "key": "FFmpegExtractAudio",
                    "preferredcodec": "mp3",
                    "preferredquality": q,
                }],
            })
            media_type = "audio/mpeg"
            extensions = {".mp3"}
        else:
            if quality == "best":
                fmt = "bestvideo+bestaudio/best"
            else:
                height = re.sub(r"\D", "", quality) or "1080"
                fmt = (f"bestvideo[height<={height}][ext=mp4]+"
                       f"bestaudio[ext=m4a]/"
                       f"best[height<={height}][ext=mp4]/"
                       f"best[height<={height}]/best")
            options.update({
                "format": fmt,
                "merge_output_format": "mp4",
            })
            media_type = "video/mp4"
            extensions = {".mp4"}

        with yt_dlp.YoutubeDL(options) as ydl:
            ydl.download([url])

        files = [
            p for p in Path(tmp_dir).iterdir()
            if p.is_file() and p.stat().st_size > 0 and p.suffix.lower() in extensions
        ]
        if not files:
            raise HTTPException(500, "다운로드된 파일을 찾지 못했습니다.")

        output_file = max(files, key=lambda p: p.stat().st_size)
        filename = safe_filename(output_file.name)

        return FileResponse(
            output_file,
            media_type=media_type,
            filename=filename,
            background=BackgroundTask(shutil.rmtree, tmp_dir, ignore_errors=True),
        )
    except HTTPException:
        shutil.rmtree(tmp_dir, ignore_errors=True)
        raise
    except Exception as e:
        shutil.rmtree(tmp_dir, ignore_errors=True)
        message = str(e)[-4000:]
        raise HTTPException(500, f"다운로드 실패: {message}")
