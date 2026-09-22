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


# =========================================================
# App
# =========================================================

app = FastAPI(title="Personal YouTube Downloader API")


# =========================================================
# CORS
# =========================================================

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
    expose_headers=[
        "Content-Disposition",
        "Content-Length",
        "Content-Type",
    ],
)


# =========================================================
# YouTube hosts
# =========================================================

HOSTS = {
    "youtube.com",
    "www.youtube.com",
    "m.youtube.com",
    "youtu.be",
}


def validate_youtube_url(url: str) -> str:
    parsed = urlparse(url)

    if parsed.scheme not in {"http", "https"}:
        raise HTTPException(
            status_code=400,
            detail="http 또는 https 주소만 사용할 수 있습니다.",
        )

    hostname = (parsed.hostname or "").lower()

    if hostname not in HOSTS:
        raise HTTPException(
            status_code=400,
            detail="YouTube 주소만 사용할 수 있습니다.",
        )

    return url


# =========================================================
# Safe filename
# =========================================================

def safe_filename(name: str) -> str:
    name = re.sub(
        r'[<>:"/\\|?*\x00-\x1f]',
        "_",
        name,
    )

    name = name.strip(" .")

    if not name:
        name = "download"

    return name[:180]


# =========================================================
# Optional cookies
#
# Render Environment Variable:
#
# YOUTUBE_COOKIES_BASE64
#
# 값이 있으면 Base64로 저장된 cookies.txt를 사용합니다.
# GitHub 코드에는 쿠키를 절대 넣지 않습니다.
# =========================================================

def create_cookie_file(tmp_dir: str):
    encoded = os.environ.get("YOUTUBE_COOKIES_BASE64", "").strip()

    if not encoded:
        return None

    try:
        cookie_path = Path(tmp_dir) / "cookies.txt"

        decoded = base64.b64decode(encoded)

        cookie_path.write_bytes(decoded)

        return str(cookie_path)

    except Exception as e:
        raise RuntimeError(
            f"YOUTUBE_COOKIES_BASE64를 읽을 수 없습니다: {e}"
        )


# =========================================================
# yt-dlp common options
# =========================================================

def common_options(tmp_dir: str, cookie_file: str | None):
    options = {
        "outtmpl": str(
            Path(tmp_dir) / "%(title)s.%(ext)s"
        ),

        "noplaylist": True,

        "quiet": True,

        "no_warnings": True,

        "retries": 3,

        "fragment_retries": 3,

        "continuedl": True,

        "nocheckcertificate": False,

        # YouTube JS challenge 대응
        "js_runtimes": {
            "deno": {},
        },

        # EJS를 GitHub에서 가져올 수 있도록 허용
        "remote_components": {
            "ejs": ["github"],
        },

        # 너무 많은 로그 출력 방지
        "logger": None,
    }

    if cookie_file:
        options["cookiefile"] = cookie_file

    return options


# =========================================================
# YouTube client profiles
#
# 하나가 실패하면 다음 profile을 시도합니다.
# =========================================================

CLIENT_PROFILES = [
    {
        "name": "tv",
        "extractor_args": {
            "youtube": {
                "player_client": ["tv"],
            }
        },
    },
    {
        "name": "web_safari",
        "extractor_args": {
            "youtube": {
                "player_client": ["web_safari"],
            }
        },
    },
    {
        "name": "android_vr",
        "extractor_args": {
            "youtube": {
                "player_client": ["android_vr"],
            }
        },
    },
]


# =========================================================
# yt-dlp download helper
# =========================================================

def run_download(
    url: str,
    tmp_dir: str,
    file_format: str,
    quality: str,
    cookie_file: str | None,
):
    errors = []

    for profile in CLIENT_PROFILES:

        profile_name = profile["name"]

        try:
            options = common_options(
                tmp_dir,
                cookie_file,
            )

            options["extractor_args"] = (
                profile["extractor_args"]
            )

            # -------------------------------------------------
            # MP3
            # -------------------------------------------------

            if file_format == "mp3":

                q = re.sub(r"\D", "", quality)

                if q not in {
                    "320",
                    "256",
                    "192",
                    "128",
                    "96",
                }:
                    q = "192"

                options.update(
                    {
                        "format": "bestaudio/best",

                        "postprocessors": [
                            {
                                "key": "FFmpegExtractAudio",
                                "preferredcodec": "mp3",
                                "preferredquality": q,
                            }
                        ],
                    }
                )

                expected_extensions = {".mp3"}

            # -------------------------------------------------
            # MP4
            # -------------------------------------------------

            else:

                if quality == "best":

                    fmt = (
                        "bestvideo+bestaudio/"
                        "best"
                    )

                else:

                    height = re.sub(
                        r"\D",
                        "",
                        quality,
                    ) or "1080"

                    fmt = (
                        f"bestvideo[height<={height}]"
                        "[ext=mp4]+"
                        "bestaudio[ext=m4a]/"
                        f"best[height<={height}]"
                        "[ext=mp4]/"
                        f"best[height<={height}]/"
                        "best"
                    )

                options.update(
                    {
                        "format": fmt,

                        "merge_output_format": "mp4",
                    }
                )

                expected_extensions = {".mp4"}

            # -------------------------------------------------
            # Execute yt-dlp
            # -------------------------------------------------

            with yt_dlp.YoutubeDL(options) as ydl:

                ydl.download([url])

            # -------------------------------------------------
            # Find resulting file
            # -------------------------------------------------

            files = []

            for path in Path(tmp_dir).iterdir():

                if not path.is_file():
                    continue

                if path.stat().st_size <= 0:
                    continue

                if path.suffix.lower() not in expected_extensions:
                    continue

                files.append(path)

            if files:

                return max(
                    files,
                    key=lambda p: p.stat().st_size,
                )

            errors.append(
                f"{profile_name}: "
                "다운로드 파일을 찾지 못했습니다."
            )

        except Exception as e:

            message = str(e)

            # 너무 긴 yt-dlp 로그를 그대로 반환하지 않음
            if len(message) > 1500:
                message = message[-1500:]

            errors.append(
                f"{profile_name}: {message}"
            )

    # ---------------------------------------------------------
    # 모든 profile 실패
    # ---------------------------------------------------------

    raise RuntimeError(
        "모든 YouTube 다운로드 방식이 실패했습니다.\n\n"
        + "\n\n".join(errors)
    )


# =========================================================
# Health
# =========================================================

@app.get("/api/health")
def health():

    return {
        "ok": True,
        "service": "youtube-downloader",
        "yt_dlp": getattr(
            yt_dlp,
            "__version__",
            "unknown",
        ),
    }


# =========================================================
# Download
# =========================================================

@app.get("/api/download")
def download(
    url: str = Query(
        ...,
        min_length=10,
    ),

    format: str = Query(
        "mp3",
        pattern="^(mp3|mp4)$",
    ),

    quality: str = Query(
        "192",
    ),
):

    # ---------------------------------------------------------
    # Validate URL
    # ---------------------------------------------------------

    validate_youtube_url(url)

    # ---------------------------------------------------------
    # Temporary directory
    # ---------------------------------------------------------

    tmp_dir = tempfile.mkdtemp(
        prefix="ytdl_"
    )

    try:

        # -----------------------------------------------------
        # Optional cookies
        # -----------------------------------------------------

        cookie_file = create_cookie_file(
            tmp_dir
        )

        # -----------------------------------------------------
        # Download
        # -----------------------------------------------------

        output_file = run_download(
            url=url,
            tmp_dir=tmp_dir,
            file_format=format,
            quality=quality,
            cookie_file=cookie_file,
        )

        # -----------------------------------------------------
        # Response settings
        # -----------------------------------------------------

        if format == "mp3":

            media_type = "audio/mpeg"

            extension = ".mp3"

        else:

            media_type = "video/mp4"

            extension = ".mp4"

        # -----------------------------------------------------
        # Ensure extension
        # -----------------------------------------------------

        filename = safe_filename(
            output_file.name
        )

        if not filename.lower().endswith(
            extension
        ):
            filename += extension

        # -----------------------------------------------------
        # Send file
        #
        # Temporary folder is removed AFTER response finishes.
        # -----------------------------------------------------

        return FileResponse(
            path=output_file,
            media_type=media_type,
            filename=filename,
            background=BackgroundTask(
                shutil.rmtree,
                tmp_dir,
                ignore_errors=True,
            ),
        )

    except HTTPException:

        shutil.rmtree(
            tmp_dir,
            ignore_errors=True,
        )

        raise

    except Exception as e:

        shutil.rmtree(
            tmp_dir,
            ignore_errors=True,
        )

        message = str(e)

        if len(message) > 3000:
            message = message[-3000:]

        raise HTTPException(
            status_code=500,
            detail=(
                "다운로드 실패:\n"
                + message
            ),
        )
