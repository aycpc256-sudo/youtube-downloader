import base64
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
    expose_headers=[
        "Content-Disposition",
        "Content-Length",
        "Content-Type",
    ],
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
    name = re.sub(
        r'["\\\r\n\x00-\x1f]',
        "",
        name
    )

    return name.strip() or "download"


# ============================================================
# YouTube 쿠키 준비
#
# Render Environment Variable:
# YOUTUBE_COOKIES
# ============================================================

def prepare_youtube_cookies():
    raw_value = os.environ.get(
        "YOUTUBE_COOKIES",
        ""
    ).strip()

    if not raw_value:
        return None

    cookie_path = "/tmp/youtube-cookies.txt"

    cookie_text = raw_value

    # Base64 형태도 허용
    if not raw_value.startswith("#"):
        try:
            decoded = base64.b64decode(
                raw_value,
                validate=True
            ).decode(
                "utf-8",
                errors="ignore"
            )

            if (
                decoded.startswith(
                    "# Netscape HTTP Cookie File"
                )
                or decoded.startswith(
                    "# HTTP Cookie File"
                )
            ):
                cookie_text = decoded

        except Exception:
            pass

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
            "youtube": {
                "player_client": [
                    "mweb"
                ]
            },

            "youtubepot-bgutilhttp": {
                "base_url": (
                    f"http://127.0.0.1:{BGUTIL_PORT}"
                )
            },
        },
    }

    cookie_path = prepare_youtube_cookies()

    if cookie_path:
        options["cookiefile"] = cookie_path

    return options


# ============================================================
# FFmpeg 검사
# ============================================================

def check_ffmpeg():

    try:

        proc = subprocess.run(
            [
                "ffmpeg",
                "-version"
            ],
            capture_output=True,
            text=True,
            timeout=10,
        )

        first_line = (
            proc.stdout.splitlines()[0]
            if proc.stdout
            else ""
        )

        return {
            "ok": proc.returncode == 0,
            "message": first_line or "FFmpeg 확인 완료",
        }

    except Exception as e:

        return {
            "ok": False,
            "message": str(e),
        }


# ============================================================
# BgUtils 검사
# ============================================================

def check_bgutil():

    result = {
        "tcp": False,
        "ping": False,
        "message": "",
    }

    try:

        sock = socket.create_connection(
            (
                "127.0.0.1",
                BGUTIL_PORT
            ),
            timeout=3
        )

        sock.close()

        result["tcp"] = True

    except Exception as e:

        result["message"] = (
            f"TCP 실패: {e}"
        )

    try:

        with urllib.request.urlopen(
            f"http://127.0.0.1:{BGUTIL_PORT}/ping",
            timeout=5
        ) as response:

            body = (
                response.read()
                .decode(
                    errors="ignore"
                )
            )

            result["ping"] = True
            result["message"] = body[:200]

    except Exception as e:

        if not result["message"]:
            result["message"] = (
                f"ping 실패: {e}"
            )

    return result


# ============================================================
# YouTube HTTP 검사
# ============================================================

def check_youtube_http():

    try:

        request = urllib.request.Request(
            "https://www.youtube.com/",
            headers={
                "User-Agent": (
                    "Mozilla/5.0 "
                    "(Windows NT 10.0; Win64; x64) "
                    "AppleWebKit/537.36 "
                    "(KHTML, like Gecko) "
                    "Chrome/131.0 Safari/537.36"
                )
            }
        )

        with urllib.request.urlopen(
            request,
            timeout=15
        ) as response:

            return {
                "ok": True,
                "status": response.status,
                "message": "YouTube 연결 성공",
            }

    except Exception as e:

        return {
            "ok": False,
            "status": None,
            "message": str(e),
        }


# ============================================================
# Health
# ============================================================

@app.get("/api/health")
def health():

    try:
        yt_version = pkg_version(
            "yt-dlp"
        )

    except Exception:
        yt_version = "unknown"

    cookie_enabled = bool(
        os.environ.get(
            "YOUTUBE_COOKIES",
            ""
        ).strip()
    )

    bgutil = check_bgutil()

    return {
        "ok": True,
        "service": "youtube-downloader",
        "yt_dlp": yt_version,
        "cookies": cookie_enabled,
        "pot_provider": (
            bgutil["tcp"]
            and bgutil["ping"]
        ),
        "js_runtime": "deno",
        "player_client": "mweb",
    }


# ============================================================
# 테스트 엔드포인트
# ============================================================

@app.get("/api/test123")
def test123():

    return {
        "ok": True,
        "message": "NEW_SERVER_PY_IS_RUNNING"
    }


# ============================================================
# 영상 정보
# ============================================================

@app.get("/api/info")
def info(
    url: str = Query(
        ...,
        min_length=10
    )
):

    validate_url(url)

    options = get_base_options()

    options.update({
        "skip_download": True,
    })

    try:

        with yt_dlp.YoutubeDL(
            options
        ) as ydl:

            data = ydl.extract_info(
                url,
                download=False
            )

    except Exception as e:

        raise HTTPException(
            status_code=400,
            detail=(
                "영상 정보를 가져올 수 없습니다: "
                f"{e}"
            )
        )

    formats = []

    for f in data.get("formats") or []:

        formats.append({
            "format_id": f.get("format_id"),
            "ext": f.get("ext"),
            "height": f.get("height"),
            "width": f.get("width"),
            "fps": f.get("fps"),
            "vcodec": f.get("vcodec"),
            "acodec": f.get("acodec"),
            "video_ext": f.get("video_ext"),
            "audio_ext": f.get("audio_ext"),
            "filesize": f.get("filesize"),
        })

    return {
        "title": data.get("title"),
        "duration": data.get("duration"),
        "uploader": data.get("uploader"),
        "thumbnail": data.get("thumbnail"),
        "id": data.get("id"),
        "formats": formats,
    }


# ============================================================
# 실제 다운로드
# ============================================================

@app.get("/api/download")
def download(
    url: str = Query(
        ...,
        min_length=10
    ),

    format: str = Query(
        "mp3",
        pattern="^(mp3|m4a|mp4)$"
    ),

    quality: str = Query(
        "192 kbps"
    ),
):

    validate_url(url)

    tmpdir = tempfile.mkdtemp(
        prefix="ytdl_"
    )

    try:

        outtmpl = os.path.join(
            tmpdir,
            "%(title).150B [%(id)s].%(ext)s"
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

                "format":
                    "bestaudio/best",

                "postprocessors": [
                    {
                        "key":
                            "FFmpegExtractAudio",

                        "preferredcodec":
                            "mp3",

                        "preferredquality":
                            bitrate,
                    }
                ],
            }

            media_type = "audio/mpeg"


        # ====================================================
        # M4A
        # ====================================================

        elif format == "m4a":

            ydl_opts = {
                **base,

                "format":
                    "bestaudio[ext=m4a]/"
                    "bestaudio/best",
            }

            media_type = "audio/mp4"


        # ====================================================
        # MP4
        # ====================================================

        else:

            height_match = re.search(
                r"(\d+)",
                quality
            )

            if height_match:

                height = (
                    height_match.group(1)
                )

                format_spec = (
                    f"bestvideo"
                    f"[height<={height}]"
                    f"[vcodec^=avc1]+"
                    f"bestaudio[ext=m4a]/"

                    f"best[height<={height}]"
                    f"[vcodec^=avc1]/"

                    f"bestvideo"
                    f"[height<={height}]"
                    f"[ext=mp4]+"
                    f"bestaudio[ext=m4a]/"

                    f"best[height<={height}]"
                )

            else:

                format_spec = (
                    "bestvideo[vcodec^=avc1]+"
                    "bestaudio[ext=m4a]/"

                    "best[vcodec^=avc1]/"

                    "bestvideo[ext=mp4]+"
                    "bestaudio[ext=m4a]/"

                    "best"
                )

            ydl_opts = {
                **base,

                "format":
                    format_spec,

                "merge_output_format":
                    "mp4",
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
        # 결과 파일
        # ====================================================

        files = [
            f
            for f in Path(
                tmpdir
            ).iterdir()
            if f.is_file()
        ]

        if not files:

            raise HTTPException(
                status_code=500,
                detail=(
                    "다운로드된 파일이 없습니다."
                )
            )


        # 가장 큰 파일 선택
        filepath = max(
            files,
            key=lambda f:
                f.stat().st_size
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
            )
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
            detail=(
                f"다운로드 실패: {e}"
            )
        )


# ============================================================
# Player Client 개별 테스트
# ============================================================

def test_player_client(
    url: str,
    client: str
):

    result = {
        "client": client,
        "success": False,
        "title": None,
        "video_id": None,
        "format_count": 0,
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
                    "player_client": [
                        client
                    ]
                },

                "youtubepot-bgutilhttp": {
                    "base_url":
                        (
                            f"http://127.0.0.1:"
                            f"{BGUTIL_PORT}"
                        )
                },
            },
        })

        with yt_dlp.YoutubeDL(
            options
        ) as ydl:

            data = ydl.extract_info(
                url,
                download=False
            )

        result["success"] = True

        result["title"] = (
            data.get("title")
        )

        result["video_id"] = (
            data.get("id")
        )

        result["format_count"] = len(
            data.get("formats") or []
        )

    except Exception as e:

        result["error"] = str(e)[:2000]

    return result


# ============================================================
# 진단
# ============================================================

def run_diagnosis(url: str):

    result = {}

    # --------------------------------------------------------
    # yt-dlp
    # --------------------------------------------------------

    try:

        result["yt_dlp"] = {
            "ok": True,
            "version":
                pkg_version("yt-dlp"),
        }

    except Exception as e:

        result["yt_dlp"] = {
            "ok": False,
            "error": str(e),
        }


    # --------------------------------------------------------
    # YouTube HTTP
    # --------------------------------------------------------

    youtube_http = (
        check_youtube_http()
    )

    result["youtube_http"] = (
        youtube_http
    )


    # --------------------------------------------------------
    # BgUtils
    # --------------------------------------------------------

    bgutil = check_bgutil()

    result["bgutil"] = bgutil


    # --------------------------------------------------------
    # FFmpeg
    # --------------------------------------------------------

    ffmpeg = check_ffmpeg()

    result["ffmpeg"] = ffmpeg


    # --------------------------------------------------------
    # Cookies
    # --------------------------------------------------------

    result["cookies"] = {
        "configured": bool(
            os.environ.get(
                "YOUTUBE_COOKIES",
                ""
            ).strip()
        )
    }


    # --------------------------------------------------------
    # Player Clients
    # --------------------------------------------------------

    clients = [
        "mweb",
        "web_safari",
        "web_embedded",
        "android_vr",
        "tv",
    ]

    client_results = []

    for client in clients:

        client_results.append(
            test_player_client(
                url,
                client
            )
        )

    result["clients"] = (
        client_results
    )


    # --------------------------------------------------------
    # 최종 판단
    # --------------------------------------------------------

    client_ok = any(
        x.get("success") is True
        for x in client_results
    )

    if client_ok:

        level = "ok"

        title = (
            "사용 가능한 YouTube Player Client가 확인되었습니다."
        )

    elif (
        result["yt_dlp"].get("ok")
        and bgutil.get("tcp")
    ):

        level = "warn"

        title = (
            "서버 구성은 동작하지만 "
            "YouTube Player 응답 추출에 실패했습니다."
        )

    else:

        level = "error"

        title = (
            "YouTube 연결 구성에 문제가 있습니다."
        )


    result["diagnosis"] = {
        "level": level,
        "title": title,
    }

    return result


# ============================================================
# /api/diagnose
# ============================================================

@app.get("/api/diagnose")
def diagnose(
    url: str = Query(
        ...,
        min_length=10
    )
):

    validate_url(url)

    try:

        result = run_diagnosis(
            url
        )

        return result

    except Exception as e:

        return {
            "diagnosis": {
                "level": "error",
                "title": "진단 실행 중 오류가 발생했습니다.",
            },

            "error": str(e),

            "clients": [],
        }


# ============================================================
# 기존 /api/diag도 유지
# ============================================================

@app.get("/api/diag")
def diag(
    url: str = Query(
        "https://youtu.be/DerxkQjViXg",
        min_length=10
    )
):

    validate_url(url)

    return run_diagnosis(
        url
    )


# ============================================================
# 기존 Player Client 테스트 API
# ============================================================

@app.get("/api/test-clients")
def test_clients(
    url: str = Query(
        ...,
        min_length=10
    )
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

        results.append(
            test_player_client(
                url,
                client
            )
        )

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
