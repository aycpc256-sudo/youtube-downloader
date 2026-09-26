import base64
import os
import re
import shutil
import subprocess
import tempfile
import urllib.error
import urllib.request
from pathlib import Path
from urllib.parse import urlparse

import yt_dlp
from fastapi import FastAPI, HTTPException, Query
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from starlette.background import BackgroundTask


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
# YouTube URL
# =========================================================

HOSTS = {
    "youtube.com",
    "www.youtube.com",
    "m.youtube.com",
    "youtu.be",
}


def validate_youtube_url(url: str):
    parsed = urlparse(url)
    hostname = (parsed.hostname or "").lower()

    if parsed.scheme not in {"http", "https"}:
        raise HTTPException(
            400,
            "http 또는 https 주소만 사용할 수 있습니다.",
        )

    if hostname not in HOSTS:
        raise HTTPException(
            400,
            "YouTube 주소만 사용할 수 있습니다.",
        )

    return url


# =========================================================
# Cookie
#
# 지원:
# 1) YOUTUBE_COOKIES = Netscape cookies.txt 전체 내용
# 2) YT_COOKIES_B64 = cookies.txt Base64
#
# 쿠키 내용은 API 응답으로 절대 노출하지 않음
# =========================================================

COOKIE_FILE = "/tmp/youtube-cookies.txt"


def prepare_cookies():
    raw_cookie = os.environ.get(
        "YOUTUBE_COOKIES",
        "",
    ).strip()

    if raw_cookie:
        try:
            Path(COOKIE_FILE).write_text(
                raw_cookie,
                encoding="utf-8",
            )

            if Path(COOKIE_FILE).stat().st_size > 0:
                return COOKIE_FILE

        except Exception as e:
            print("YOUTUBE_COOKIES preparation failed:", e)

    encoded_cookie = os.environ.get(
        "YT_COOKIES_B64",
        "",
    ).strip()

    if encoded_cookie:
        try:
            data = base64.b64decode(
                encoded_cookie,
                validate=True,
            )

            Path(COOKIE_FILE).write_bytes(data)

            if Path(COOKIE_FILE).stat().st_size > 0:
                return COOKIE_FILE

        except Exception as e:
            print("YT_COOKIES_B64 preparation failed:", e)

    return None


COOKIE_PATH = prepare_cookies()


# =========================================================
# 공통 yt-dlp 설정
# =========================================================

def base_options(tmp_dir: str):
    options = {
        "outtmpl": str(
            Path(tmp_dir) / "%(title).150B [%(id)s].%(ext)s"
        ),

        "noplaylist": True,

        "quiet": True,
        "no_warnings": True,

        "retries": 3,
        "fragment_retries": 3,
        "continuedl": True,

        "nocheckcertificate": True,

        # YouTube PO Token Provider
        "extractor_args": {
            "youtube": {
                "player_client": [
                    "mweb"
                ],
            },

            "youtubepot-bgutilhttp": {
                "base_url": [
                    "http://127.0.0.1:4416"
                ],
            },
        },

        # yt-dlp JS challenge
        "js_runtimes": {
            "deno": {}
        },

        "remote_components": {
            "ejs": ["github"]
        },
    }

    if COOKIE_PATH and os.path.isfile(COOKIE_PATH):
        options["cookiefile"] = COOKIE_PATH

    return options


# =========================================================
# 파일명
# =========================================================

def safe_filename(name: str):
    name = re.sub(
        r'[<>:"/\\|?*\x00-\x1f]',
        "_",
        name,
    ).strip(" .")

    return (name or "download")[:180]


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

        "cookies": bool(COOKIE_PATH),

        "pot_provider": True,

        "js_runtime": "deno",
        "player_client": "mweb",
    }


# =========================================================
# FFmpeg 검사
# =========================================================

def check_ffmpeg():
    try:
        result = subprocess.run(
            [
                "ffmpeg",
                "-version",
            ],
            capture_output=True,
            text=True,
            timeout=10,
        )

        if result.returncode == 0:
            first_line = (
                result.stdout.strip()
                .splitlines()[0]
                if result.stdout.strip()
                else "FFmpeg 정상"
            )

            return {
                "ok": True,
                "message": first_line,
            }

        return {
            "ok": False,
            "message": "ffmpeg 실행 실패",
        }

    except Exception as e:
        return {
            "ok": False,
            "message": str(e),
        }


# =========================================================
# BgUtils 검사
# =========================================================

def check_bgutil():
    url = "http://127.0.0.1:4416/ping"

    try:
        request = urllib.request.Request(
            url,
            method="GET",
        )

        with urllib.request.urlopen(
            request,
            timeout=8,
        ) as response:

            body = response.read().decode(
                "utf-8",
                errors="replace",
            )

            return {
                "ok": True,
                "status": response.status,
                "message": body[:1000],
            }

    except Exception as e:
        return {
            "ok": False,
            "message": str(e),
        }


# =========================================================
# YouTube HTTP 연결 검사
# =========================================================

def check_youtube_http():
    url = "https://www.youtube.com/"

    try:
        request = urllib.request.Request(
            url,
            headers={
                "User-Agent": (
                    "Mozilla/5.0 "
                    "(Windows NT 10.0; Win64; x64) "
                    "AppleWebKit/537.36 "
                    "(KHTML, like Gecko) "
                    "Chrome/140.0 Safari/537.36"
                ),
            },
        )

        with urllib.request.urlopen(
            request,
            timeout=15,
        ) as response:

            return {
                "ok": True,
                "status": response.status,
                "message": "YouTube 연결 정상",
            }

    except urllib.error.HTTPError as e:
        return {
            "ok": False,
            "status": e.code,
            "message": f"HTTP {e.code}",
        }

    except Exception as e:
        return {
            "ok": False,
            "message": str(e),
        }


# =========================================================
# Player Client 검사
#
# 각 client의 실제 오류를 보존해서 반환
# =========================================================

PLAYER_CLIENTS = [
    "mweb",
    "web_safari",
    "web_embedded",
    "android_vr",
    "tv",
]


def test_player_client(
    url: str,
    client: str,
):
    options = {
        "quiet": True,
        "no_warnings": True,
        "skip_download": True,
        "noplaylist": True,

        "extractor_args": {
            "youtube": {
                "player_client": [
                    client
                ],
            },

            "youtubepot-bgutilhttp": {
                "base_url": [
                    "http://127.0.0.1:4416"
                ],
            },
        },

        "js_runtimes": {
            "deno": {}
        },

        "remote_components": {
            "ejs": ["github"]
        },
    }

    if COOKIE_PATH and os.path.isfile(COOKIE_PATH):
        options["cookiefile"] = COOKIE_PATH

    try:
        with yt_dlp.YoutubeDL(options) as ydl:
            data = ydl.extract_info(
                url,
                download=False,
            )

        return {
            "client": client,
            "ok": True,
            "title": data.get("title"),
            "formats": len(
                data.get("formats") or []
            ),
        }

    except Exception as e:
        message = str(e)

        return {
            "client": client,
            "ok": False,
            "error": message[-2500:],
        }


# =========================================================
# 진단 API
# =========================================================

@app.get("/api/diagnose")
def diagnose(
    url: str = Query(..., min_length=10),
):
    validate_youtube_url(url)

    result = {
        "ok": False,
        "yt_dlp": getattr(
            yt_dlp,
            "__version__",
            "unknown",
        ),

        "cookies": {
            "configured": bool(COOKIE_PATH),
        },

        "youtube_http": None,
        "bgutil": None,
        "ffmpeg": None,

        "clients": [],

        "diagnosis": {
            "level": "warn",
            "title": "진단 중",
        },
    }

    # -----------------------------------------------------
    # YouTube HTTP
    # -----------------------------------------------------

    result["youtube_http"] = check_youtube_http()

    # -----------------------------------------------------
    # BgUtils
    # -----------------------------------------------------

    result["bgutil"] = check_bgutil()

    # -----------------------------------------------------
    # FFmpeg
    # -----------------------------------------------------

    result["ffmpeg"] = check_ffmpeg()

    # -----------------------------------------------------
    # Player clients
    # -----------------------------------------------------

    for client in PLAYER_CLIENTS:
        result["clients"].append(
            test_player_client(
                url,
                client,
            )
        )

    successful_clients = [
        item
        for item in result["clients"]
        if item.get("ok") is True
    ]

    # -----------------------------------------------------
    # 종합 진단
    # -----------------------------------------------------

    if successful_clients:
        result["ok"] = True

        result["diagnosis"] = {
            "level": "ok",
            "title": (
                "사용 가능한 YouTube Player Client가 "
                "확인되었습니다."
            ),
        }

    elif not result["youtube_http"]["ok"]:
        status = result["youtube_http"].get(
            "status"
        )

        result["diagnosis"] = {
            "level": "error",
            "title": (
                f"YouTube 연결 실패 "
                f"(HTTP {status})"
                if status
                else "YouTube 연결 실패"
            ),
        }

    elif not result["bgutil"]["ok"]:
        result["diagnosis"] = {
            "level": "error",
            "title": (
                "BgUtils / PO Token Provider 연결 실패"
            ),
        }

    else:
        result["diagnosis"] = {
            "level": "error",
            "title": (
                "모든 Player Client에서 "
                "YouTube player response를 가져오지 못했습니다."
            ),
        }

    return result


# =========================================================
# 영상 정보
# =========================================================

@app.get("/api/info")
def info(
    url: str = Query(..., min_length=10),
):
    validate_youtube_url(url)

    options = base_options(
        tempfile.mkdtemp(
            prefix="ytdl_info_"
        )
    )

    # 정보 조회에서는 다운로드하지 않음
    options["skip_download"] = True

    try:
        with yt_dlp.YoutubeDL(options) as ydl:
            data = ydl.extract_info(
                url,
                download=False,
            )

        formats = []

        for f in data.get("formats") or []:
            height = f.get("height")

            if not height:
                continue

            ext = (
                f.get("ext")
                or ""
            ).lower()

            video_ext = (
                f.get("video_ext")
                or ""
            ).lower()

            if ext != "mp4" and video_ext != "mp4":
                continue

            formats.append({
                "format_id": f.get("format_id"),
                "height": height,
                "width": f.get("width"),
                "ext": ext,
                "video_ext": video_ext,
                "fps": f.get("fps"),
                "vcodec": f.get("vcodec"),
                "acodec": f.get("acodec"),
                "filesize": f.get("filesize"),
            })

        # 높이 중복 제거
        unique_heights = {}

        for item in formats:
            h = item["height"]

            if h not in unique_heights:
                unique_heights[h] = item

        clean_formats = sorted(
            unique_heights.values(),
            key=lambda x: x["height"],
            reverse=True,
        )

        return {
            "title": data.get("title"),
            "duration": data.get("duration"),
            "uploader": data.get("uploader"),
            "thumbnail": data.get("thumbnail"),
            "formats": clean_formats,
        }

    except Exception as e:
        raise HTTPException(
            400,
            f"영상 정보를 가져올 수 없습니다: {str(e)[-3000:]}",
        )


# =========================================================
# 다운로드
# =========================================================

@app.get("/api/download")
def download(
    url: str = Query(..., min_length=10),
    format: str = Query(
        "mp3",
        pattern="^(mp3|m4a|mp4)$",
    ),
    quality: str = Query("192"),
):
    validate_youtube_url(url)

    tmp_dir = tempfile.mkdtemp(
        prefix="ytdl_"
    )

    try:
        options = base_options(
            tmp_dir
        )

        # -------------------------------------------------
        # MP3
        # -------------------------------------------------

        if format == "mp3":

            q = re.sub(
                r"\D",
                "",
                quality,
            )

            if q not in {
                "320",
                "256",
                "192",
                "128",
                "96",
            }:
                q = "192"

            options.update({
                "format": (
                    "bestaudio/best"
                ),

                "postprocessors": [{
                    "key": "FFmpegExtractAudio",
                    "preferredcodec": "mp3",
                    "preferredquality": q,
                }],
            })

            media_type = "audio/mpeg"
            extensions = {".mp3"}

        # -------------------------------------------------
        # M4A
        # -------------------------------------------------

        elif format == "m4a":

            options.update({
                "format": (
                    "bestaudio[ext=m4a]/"
                    "bestaudio"
                ),
            })

            media_type = "audio/mp4"
            extensions = {".m4a"}

        # -------------------------------------------------
        # MP4
        # -------------------------------------------------

        else:

            if quality == "best":

                fmt = (
                    "bestvideo[ext=mp4]+"
                    "bestaudio[ext=m4a]/"
                    "best[ext=mp4]/"
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
                    f"[ext=mp4]+"
                    f"bestaudio[ext=m4a]/"
                    f"best[height<={height}]"
                    f"[ext=mp4]/"
                    f"best[height<={height}]/"
                    f"best"
                )

            options.update({
                "format": fmt,
                "merge_output_format": "mp4",
            })

            media_type = "video/mp4"
            extensions = {".mp4"}

        # -------------------------------------------------
        # 실행
        # -------------------------------------------------

        with yt_dlp.YoutubeDL(
            options
        ) as ydl:

            ydl.download([url])

        files = [
            p
            for p in Path(tmp_dir).iterdir()
            if (
                p.is_file()
                and p.stat().st_size > 0
                and p.suffix.lower()
                in extensions
            )
        ]

        if not files:
            raise HTTPException(
                500,
                "다운로드된 파일을 찾지 못했습니다.",
            )

        output_file = max(
            files,
            key=lambda p: p.stat().st_size,
        )

        filename = safe_filename(
            output_file.name
        )

        return FileResponse(
            output_file,
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

        raise HTTPException(
            500,
            f"다운로드 실패: {message[-4000:]}",
        )
