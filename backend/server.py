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
    expose_headers=["Content-Disposition", "Content-Length"],
)

HOSTS = {"youtube.com", "www.youtube.com", "m.youtube.com", "youtu.be"}

def validate(url: str) -> str:
    p = urlparse(url)
    if p.scheme not in {"http", "https"} or (p.hostname or "").lower() not in HOSTS:
        raise HTTPException(400, "YouTube 주소만 사용할 수 있습니다.")
    return url

def safe(name: str) -> str:
    name = re.sub(r'[<>:"/\\|?*\x00-\x1f]', "_", name).strip(" .")
    return (name or "download")[:180]

@app.get("/api/health")
def health():
    return {"ok": True, "service": "youtube-downloader"}

@app.get("/api/download")
def download(
    url: str = Query(..., min_length=10),
    format: str = Query("mp3", pattern="^(mp3|mp4)$"),
    quality: str = Query("192"),
):
    validate(url)
    tmp = tempfile.mkdtemp(prefix="ytdl_")
    try:
        base = {
            "outtmpl": str(Path(tmp) / "%(title)s.%(ext)s"),
            "noplaylist": True,
            "quiet": True,
            "no_warnings": True,
            "retries": 3,
            "fragment_retries": 3,
            "continuedl": True,
            "extractor_args": {
                "youtube": {
                    "player_client": ["mweb"],
                    "pot": ["mweb"],
                }
            },
        }

        if format == "mp3":
            q = re.sub(r"\D", "", quality) or "192"
            q = q if q in {"320", "256", "192", "128", "96"} else "192"
            opts = {
                **base,
                "format": "bestaudio/best",
                "postprocessors": [{
                    "key": "FFmpegExtractAudio",
                    "preferredcodec": "mp3",
                    "preferredquality": q,
                }],
            }
            media, exts = "audio/mpeg", (".mp3",)
        else:
            if quality == "best":
                fmt = "bestvideo+bestaudio/best"
            else:
                h = re.sub(r"\D", "", quality) or "1080"
                fmt = (
                    f"bestvideo[height<={h}][ext=mp4]+bestaudio[ext=m4a]/"
                    f"best[height<={h}][ext=mp4]/best[height<={h}]/best"
                )
            opts = {**base, "format": fmt, "merge_output_format": "mp4"}
            media, exts = "video/mp4", (".mp4",)

        with yt_dlp.YoutubeDL(opts) as ydl:
            ydl.download([url])

        found = [
            p for p in Path(tmp).iterdir()
            if p.is_file() and p.stat().st_size > 0 and p.suffix.lower() in exts
        ]
        if not found:
            raise HTTPException(500, "다운로드된 파일을 찾지 못했습니다.")

        path = max(found, key=lambda p: p.stat().st_size)
        return FileResponse(
            path,
            media_type=media,
            filename=safe(path.name),
            background=BackgroundTask(shutil.rmtree, tmp, ignore_errors=True),
        )
    except HTTPException:
        shutil.rmtree(tmp, ignore_errors=True)
        raise
    except Exception as e:
        shutil.rmtree(tmp, ignore_errors=True)
        raise HTTPException(500, f"다운로드 실패: {e}")
