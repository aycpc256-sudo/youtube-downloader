import os
import re
import shutil
import socket
import subprocess
import tempfile
import urllib.request
from importlib.metadata import version as pkg_version
from pathlib import Path

import yt_dlp
from fastapi import FastAPI, HTTPException, Query
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from starlette.background import BackgroundTask


# ============================================================
# FastAPI
# ============================================================

app = FastAPI(title="YouTube Downloader API")


# ============================================================
# CORS
# ============================================================

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
)


# ============================================================
# 기본 설정
# ============================================================

BGUTIL_PORT = int(
    os.environ.get("BGUTIL_PORT", "4416")
)

RE_URL = re.compile(
    r"^https?://",
    re.IGNORECASE
)


# ============================================================
# URL 검사
# ============================================================

def validate_url(url: str):
    if not RE_URL.match(url):
        raise HTTPException(
            status_code=400,
            detail="URL 형식이 아닙니다."
        )


# ============================================================
# 파일명 정리
# ============================================================

def safe_filename(name: str) -> str:
    # HTTP 헤더를 깨뜨리는 문자만 제거 (한글/공백/쉼표 등은 유지)
    name = re.sub(r'["\\\r\n\x00-\x1f]', "", name)
    return name.strip() or "download"


# ============================================================
# YouTube 쿠키 준비
#
# Render Environment Variable:
#
# YOUTUBE_COOKIES
#
# ↓
#
# /tmp/youtube-cookies.txt
# ============================================================

def prepare_youtube_cookies():
    cookie_text = os.environ.get(
        "YOUTUBE_COOKIES",
        ""
    ).strip()

    if not cookie_text:
        return None

    cookie_path = "/tmp/youtube-cookies.txt"

    try:
        with open(
            cookie_path,
            "w",
            encoding="utf-8",
            newline="\n"
        ) as f:
            f.write(cookie_text)

            if not cookie_text.endswith("\n"):
                f.write("\n")

        return cookie_path

    except Exception as e:
        raise RuntimeError(
            f"YouTube 쿠키 파일 생성 실패: {e}"
        )


# ============================================================
# 공통 yt-dlp 옵션
# ============================================================

def get_base_options():

    options = {
        "quiet": True,
        "no_warnings": True,
        "noplaylist": True,
        "no_mtime": True,
        "no_overwrites": True,
        "retries": 3,
        "fragment_retries": 3,
        "socket_timeout": 30,

        "extractor_args": {
            "youtubepot-bgutilhttp": {
                "base_url": (
                    f"http://127.0.0.1:{BGUTIL_PORT}"
                )
            }
        },
    }

    # --------------------------------------------------------
    # YouTube cookies
    # --------------------------------------------------------

    cookie_path = prepare_youtube_cookies()

    if cookie_path:
        options["cookiefile"] = cookie_path

    return options


# ============================================================
# Health
# ============================================================

@app.get("/api/health")
def health():

    try:
        yt_version = pkg_version("yt-dlp")
    except Exception:
        yt_version = "unknown"

    cookie_enabled = bool(
        os.environ.get("YOUTUBE_COOKIES", "").strip()
    )

    bgutil_ok = False

    try:
        sock = socket.create_connection(
            ("127.0.0.1", BGUTIL_PORT),
            timeout=2
        )
        sock.close()
        bgutil_ok = True
    except Exception:
        pass

    return {
        "ok": True,
        "service": "youtube-downloader",
        "yt_dlp": yt_version,
        "cookies": cookie_enabled,
        "user_agent": False,
        "pot_provider": bgutil_ok,
        "js_runtime": "deno",
        "player_client": "mweb",
    }


# ============================================================
# Test endpoint
# ============================================================

@app.get("/api/test123")
def test123():

    return {
        "ok": True,
        "message": "NEW_SERVER_PY_IS_RUNNING"
    }


# ============================================================
# Video information
# ============================================================

@app.get("/api/info")
def info(
    url: str = Query(..., min_length=10)
):

    validate_url(url)

    options = get_base_options()

    options.update({
        "skip_download": True,
    })

    try:

        with yt_dlp.YoutubeDL(options) as ydl:

            data = ydl.extract_info(
                url,
                download=False
            )

    except Exception as e:

        raise HTTPException(
            status_code=400,
            detail=(
                f"영상 정보를 가져올 수 없습니다: {e}"
            )
        )

    return {
        "title": data.get("title"),
        "duration": data.get("duration"),
        "uploader": data.get("uploader"),
        "thumbnail": data.get("thumbnail"),
        "id": data.get("id"),
    }


# ============================================================
# 실제 다운로드
# ============================================================

@app.get("/api/download")
def download(
    url: str = Query(..., min_length=10),
    format: str = Query(
        "mp3",
        pattern="^(mp3|mp4)$"
    ),
    quality: str = Query("192 kbps"),
):

    validate_url(url)

    tmpdir = tempfile.mkdtemp(
        prefix="ytdl_"
    )

    try:

        outtmpl = os.path.join(
            tmpdir,
            "%(title)s.%(ext)s"
        )

        base = get_base_options()

        base.update({
            "outtmpl": outtmpl,
        })

        # ====================================================
        # MP3
        # ====================================================

        if format == "mp3":

            bitrate_match = re.search(
                r"(\d+)",
                quality
            )

            bitrate = (
                bitrate_match.group(1)
                if bitrate_match
                else "192"
            )

            ydl_opts = {
                **base,

                "format": (
                    "bestaudio/best"
                ),

                "postprocessors": [
                    {
                        "key": "FFmpegExtractAudio",
                        "preferredcodec": "mp3",
                        "preferredquality": bitrate,
                    }
                ],
            }

            media_type = "audio/mpeg"

        # ====================================================
        # MP4
        # ====================================================

        else:

            height_match = re.search(
                r"(\d+)",
                quality
            )

            if height_match:

                height = height_match.group(1)

                format_spec = (
                    f"bestvideo[height<={height}]"
                    f"[ext=mp4]+"
                    f"bestaudio[ext=m4a]/"
                    f"best[height<={height}]"
                    f"[ext=mp4]/"
                    f"best"
                )

            else:

                format_spec = (
                    "bestvideo[ext=mp4]+"
                    "bestaudio[ext=m4a]/"
                    "best[ext=mp4]/"
                    "best"
                )

            ydl_opts = {
                **base,

                "format": format_spec,

                "merge_output_format": "mp4",
            }

            media_type = "video/mp4"

        # ====================================================
        # yt-dlp 실행
        # ====================================================

        with yt_dlp.YoutubeDL(
            ydl_opts
        ) as ydl:

            ydl.extract_info(
                url,
                download=True
            )

        # ====================================================
        # 결과 파일 찾기
        # ====================================================

        files = [
            f
            for f in Path(tmpdir).iterdir()
            if f.is_file()
        ]

        if not files:

            raise HTTPException(
                status_code=500,
                detail="다운로드된 파일이 없습니다."
            )

        filepath = max(
            files,
            key=lambda f: f.stat().st_size
        )

        filename = safe_filename(
            filepath.name
        )

        return FileResponse(
            path=str(filepath),
            media_type=media_type,
            filename=filename,
            background=BackgroundTask(
                shutil.rmtree,
                tmpdir,
                ignore_errors=True
            ),
        )

    except HTTPException:

        shutil.rmtree(
            tmpdir,
            ignore_errors=True
        )

        raise

    except Exception as e:

        shutil.rmtree(
            tmpdir,
            ignore_errors=True
        )

        raise HTTPException(
            status_code=500,
            detail=f"다운로드 실패: {e}"
        )


# ============================================================
# BgUtils + yt-dlp 진단
#
# 실제 테스트 영상:
# ACnbMg6o8z0
# ============================================================

@app.get("/api/diag")
def diag():

    result = {}

    # --------------------------------------------------------
    # yt-dlp 버전
    # --------------------------------------------------------

    try:

        result["yt_dlp_pkg"] = pkg_version(
            "yt-dlp"
        )

    except Exception as e:

        result["yt_dlp_pkg"] = (
            f"error: {e}"
        )

    # --------------------------------------------------------
    # 쿠키 존재 여부
    # --------------------------------------------------------

    result["cookies_configured"] = bool(
        os.environ.get(
            "YOUTUBE_COOKIES",
            ""
        ).strip()
    )

    # --------------------------------------------------------
    # BgUtils TCP
    # --------------------------------------------------------

    port = int(
        os.environ.get(
            "BGUTIL_PORT",
            "4416"
        )
    )

    try:

        s = socket.create_connection(
            ("127.0.0.1", port),
            timeout=3
        )

        s.close()

        result["bgutil_tcp"] = True

    except Exception as e:

        result["bgutil_tcp"] = (
            f"error: {e}"
        )

    # --------------------------------------------------------
    # BgUtils /ping
    # --------------------------------------------------------

    try:

        with urllib.request.urlopen(
            f"http://127.0.0.1:{port}/ping",
            timeout=5
        ) as r:

            result["bgutil_ping"] = (
                r.read()
                .decode(errors="ignore")[:200]
            )

    except Exception as e:

        result["bgutil_ping"] = (
            f"error: {e}"
        )

    # --------------------------------------------------------
    # 실제 YouTube 테스트
    # --------------------------------------------------------

    test_url = (
        "https://youtu.be/ACnbMg6o8z0"
    )

    try:

        options = get_base_options()

        options.update({
            "skip_download": True,
            "socket_timeout": 30,
        })

        proc = subprocess.run(
            [
                "yt-dlp",
                "-v",
                "--skip-download",
                "--no-warnings",
                "--socket-timeout",
                "30",
                "-O",
                "title",
                test_url,
            ],
            capture_output=True,
            text=True,
            timeout=180,
            env=os.environ.copy(),
        )

        output = (
            proc.stderr or ""
        ) + "\n" + (
            proc.stdout or ""
        )

        lines = output.splitlines()

        result["ytdlp_exit_code"] = (
            proc.returncode
        )

        result["pot_provider_lines"] = [
            line.strip()
            for line in lines
            if (
                "bgutil" in line.lower()
                or "[pot]" in line.lower()
                or "po token" in line.lower()
                or "po_token" in line.lower()
            )
        ][:30]

        result["errors"] = [
            line.strip()
            for line in lines
            if (
                "sign in" in line.lower()
                or "error" in line.lower()
                or "403" in line.lower()
                or "429" in line.lower()
                or "forbidden" in line.lower()
                or "bot" in line.lower()
            )
        ][:20]

    except Exception as e:

        result["ytdlp_run_error"] = str(e)

    return result


# ============================================================
# 여러 YouTube client 테스트
# ============================================================

@app.get("/api/test-clients")
def test_clients(
    url: str = Query(..., min_length=10)
):

    validate_url(url)

    clients = [
        "mweb",
        "web_safari",
        "web_embedded",
        "android_vr",
        "tv",
    ]

    results = []

    for client in clients:

        result = {
            "client": client,
            "success": False,
            "title": None,
            "error": None,
        }

        try:

            options = get_base_options()

            options.update({
                "quiet": True,
                "no_warnings": True,
                "skip_download": True,
                "socket_timeout": 30,

                "extractor_args": {
                    "youtube": {
                        "player_client": [client]
                    },

                    "youtubepot-bgutilhttp": {
                        "base_url": (
                            f"http://127.0.0.1:{BGUTIL_PORT}"
                        )
                    },
                },
            })

            with yt_dlp.YoutubeDL(
                options
            ) as ydl:

                info = ydl.extract_info(
                    url,
                    download=False
                )

                result["success"] = True

                result["title"] = (
                    info.get("title")
                )

                result["video_id"] = (
                    info.get("id")
                )

                result["duration"] = (
                    info.get("duration")
                )

                result["format_count"] = len(
                    info.get("formats") or []
                )

        except Exception as e:

            result["error"] = str(e)[:1500]

        results.append(result)

    return {
        "ok": True,
        "url": url,
        "cookies": bool(
            os.environ.get(
                "YOUTUBE_COOKIES",
                ""
            ).strip()
        ),
        "results": results,
    }


# ============================================================
# YouTube 상세 디버그
# ============================================================

@app.get("/api/test-youtube-debug")
def test_youtube_debug(
    url: str = Query(..., min_length=10)
):

    validate_url(url)

    logs = []

    class Logger:

        def debug(self, msg):
            logs.append(
                f"DEBUG: {msg}"
            )

        def warning(self, msg):
            logs.append(
                f"WARNING: {msg}"
            )

        def error(self, msg):
            logs.append(
                f"ERROR: {msg}"
            )

    options = get_base_options()

    options.update({
        "quiet": False,
        "no_warnings": False,
        "skip_download": True,
        "socket_timeout": 30,

        "logger": Logger(),

        "extractor_args": {
            "youtube": {
                "player_client": ["mweb"],
                "pot_trace": ["true"],
            },

            "youtubepot-bgutilhttp": {
                "base_url": (
                    f"http://127.0.0.1:{BGUTIL_PORT}"
                )
            },
        },
    })

    try:

        with yt_dlp.YoutubeDL(
            options
        ) as ydl:

            info = ydl.extract_info(
                url,
                download=False
            )

        return {
            "ok": True,
            "cookies": bool(
                os.environ.get(
                    "YOUTUBE_COOKIES",
                    ""
                ).strip()
            ),
            "title": info.get("title"),
            "video_id": info.get("id"),
            "duration": info.get("duration"),
            "format_count": len(
                info.get("formats") or []
            ),
            "logs": logs[-150:],
        }

    except Exception as e:

        return {
            "ok": False,
            "cookies": bool(
                os.environ.get(
                    "YOUTUBE_COOKIES",
                    ""
                ).strip()
            ),
            "error": str(e),
            "logs": logs[-150:],
        }
