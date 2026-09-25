import base64
import json
import os
import re
import shutil
import socket
import subprocess
import tempfile
import urllib.error
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
# 공통 유틸
# ============================================================

def validate_url(url: str):
    if not RE_URL.match(url):
        raise HTTPException(
            status_code=400,
            detail="URL 형식이 아닙니다."
        )


def safe_filename(name: str) -> str:
    name = re.sub(
        r'["\\\r\n\x00-\x1f]',
        "",
        name
    )
    return name.strip() or "download"


def command_exists(command: str) -> bool:
    return shutil.which(command) is not None


def get_command_version(command: str):
    try:
        proc = subprocess.run(
            [command, "--version"],
            capture_output=True,
            text=True,
            timeout=10,
        )

        output = (
            proc.stdout or proc.stderr or ""
        ).strip()

        return output.splitlines()[0][:300] if output else None

    except Exception:
        return None


# ============================================================
# YouTube 쿠키
#
# Render Environment Variable:
# YOUTUBE_COOKIES
#
# 실제 cookie 내용은 API 응답으로 절대 반환하지 않음.
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
# Cookie 구조 진단
# ============================================================

def inspect_cookie_configuration():

    raw = os.environ.get(
        "YOUTUBE_COOKIES",
        ""
    ).strip()

    if not raw:
        return {
            "configured": False,
            "valid_structure": False,
            "line_count": 0,
            "cookie_count": 0,
        }

    text = raw

    # Base64라면 디코드
    if not text.startswith("#"):

        try:

            decoded = base64.b64decode(
                text,
                validate=True
            ).decode(
                "utf-8",
                errors="ignore"
            )

            if decoded.startswith("#"):
                text = decoded

        except Exception:
            pass

    lines = text.splitlines()

    data_lines = [
        line
        for line in lines
        if line.strip()
        and not line.lstrip().startswith("#")
    ]

    valid_rows = 0

    for line in data_lines:

        fields = line.split("\t")

        if len(fields) >= 7:
            valid_rows += 1

    return {
        "configured": True,
        "valid_structure": (
            valid_rows > 0
        ),
        "line_count": len(lines),
        "cookie_count": valid_rows,
    }


# ============================================================
# yt-dlp 공통 옵션
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

    bgutil_ok = False

    try:

        sock = socket.create_connection(
            (
                "127.0.0.1",
                BGUTIL_PORT
            ),
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

        "js_runtime": (
            "deno"
            if command_exists("deno")
            else "not_found"
        ),

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
# 다운로드
#
# MP3 / M4A / MP4 모두 유지
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
            "%(title)s [%(id)s].%(ext)s"
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
                    "bestaudio[ext=m4a]/bestaudio",

                "postprocessors": [
                    {
                        "key":
                            "FFmpegExtractAudio",

                        "preferredcodec":
                            "m4a",

                        "preferredquality":
                            bitrate,
                    }
                ],
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
                    f"[vcodec^=avc1]"
                    f"+bestaudio[ext=m4a]/"

                    f"best"
                    f"[height<={height}]"
                    f"[vcodec^=avc1]/"

                    f"bestvideo"
                    f"[height<={height}]"
                    f"[ext=mp4]"
                    f"+bestaudio[ext=m4a]/"

                    f"best"
                )

            else:

                format_spec = (

                    "bestvideo"
                    "[vcodec^=avc1]"
                    "+bestaudio[ext=m4a]/"

                    "best"
                    "[vcodec^=avc1]/"

                    "bestvideo[ext=mp4]"
                    "+bestaudio[ext=m4a]/"

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
            detail=(
                f"다운로드 실패: {e}"
            )
        )


# ============================================================
# BgUtils 기본 진단
# ============================================================

@app.get("/api/diag")
def diag():

    result = {}

    # yt-dlp
    try:
        result["yt_dlp_pkg"] = pkg_version(
            "yt-dlp"
        )
    except Exception as e:
        result["yt_dlp_pkg"] = (
            f"error: {e}"
        )

    # Cookie
    result["cookies_configured"] = bool(
        os.environ.get(
            "YOUTUBE_COOKIES",
            ""
        ).strip()
    )

    result["cookie_structure"] = (
        inspect_cookie_configuration()
    )

    # Deno
    result["deno"] = {
        "available":
            command_exists("deno"),
        "version":
            get_command_version("deno"),
    }

    # FFmpeg
    result["ffmpeg"] = {
        "available":
            command_exists("ffmpeg"),
        "version":
            get_command_version("ffmpeg"),
    }

    # BgUtils TCP
    try:

        sock = socket.create_connection(
            (
                "127.0.0.1",
                BGUTIL_PORT
            ),
            timeout=3
        )

        sock.close()

        result["bgutil_tcp"] = True

    except Exception as e:

        result["bgutil_tcp"] = (
            f"error: {e}"
        )

    # BgUtils ping
    try:

        with urllib.request.urlopen(
            f"http://127.0.0.1:{BGUTIL_PORT}/ping",
            timeout=5
        ) as r:

            result["bgutil_ping"] = (
                r.read()
                .decode(
                    errors="ignore"
                )[:500]
            )

    except Exception as e:

        result["bgutil_ping"] = (
            f"error: {e}"
        )

    return result


# ============================================================
# YouTube HTTP 상태 검사
# ============================================================

def check_youtube_http(url: str):

    req = urllib.request.Request(

        url,

        headers={
            "User-Agent":
                (
                    "Mozilla/5.0 "
                    "(Windows NT 10.0; Win64; x64) "
                    "AppleWebKit/537.36 "
                    "(KHTML, like Gecko) "
                    "Chrome/138.0.0.0 Safari/537.36"
                )
        }
    )

    try:

        with urllib.request.urlopen(
            req,
            timeout=20
        ) as response:

            return {
                "ok": True,
                "status":
                    response.status,
                "final_url":
                    response.geturl(),
            }

    except urllib.error.HTTPError as e:

        return {
            "ok": False,
            "status":
                e.code,
            "reason":
                str(e.reason),
        }

    except Exception as e:

        return {
            "ok": False,
            "status": None,
            "error": str(e),
        }


# ============================================================
# 오류 분류
# ============================================================

def classify_error(text: str):

    value = (
        text or ""
    ).lower()

    if (
        "429" in value
        or "too many requests" in value
    ):
        return (
            "YOUTUBE_429",
            "YouTube가 현재 서버 요청을 429로 제한했습니다."
        )

    if (
        "sign in to confirm"
        in value
        or "not a bot"
        in value
        or "bot" in value
    ):
        return (
            "YOUTUBE_BOT_CHECK",
            "YouTube가 서버 요청에 봇 확인을 요구했습니다."
        )

    if (
        "failed to extract any player response"
        in value
        or "player response"
        in value
    ):
        return (
            "PLAYER_RESPONSE",
            "YouTube Player Response를 가져오지 못했습니다."
        )

    if (
        "403" in value
        or "forbidden" in value
    ):
        return (
            "HTTP_403",
            "YouTube가 스트림 요청을 403으로 거부했습니다."
        )

    if (
        "ffmpeg" in value
        or "postprocessing" in value
    ):
        return (
            "FFMPEG",
            "FFmpeg 또는 후처리 단계에서 문제가 발생했습니다."
        )

    if (
        "requested format"
        in value
        or "format is not available"
        in value
    ):
        return (
            "FORMAT",
            "요청한 다운로드 형식을 사용할 수 없습니다."
        )

    if (
        "video unavailable"
        in value
        or "private video"
        in value
        or "members-only"
        in value
    ):
        return (
            "VIDEO_UNAVAILABLE",
            "영상 자체가 현재 서버에서 접근할 수 없는 상태입니다."
        )

    return (
        "UNKNOWN",
        "정확한 원인을 자동 분류하지 못했습니다."
    )


# ============================================================
# Client 하나 테스트
# ============================================================

def run_client_test(
    url: str,
    client: str
):

    result = {

        "client": client,

        "success": False,

        "title": None,

        "video_id": None,

        "duration": None,

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

        result["error"] = str(e)[:2000]

    return result


# ============================================================
# Client 비교
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
            run_client_test(
                url,
                client
            )
        )

    return {

        "ok": True,

        "url": url,

        "cookies":
            bool(
                os.environ.get(
                    "YOUTUBE_COOKIES",
                    ""
                ).strip()
            ),

        "results":
            results,
    }


# ============================================================
# YouTube 상세 디버그
# ============================================================

@app.get("/api/test-youtube-debug")
def test_youtube_debug(
    url: str = Query(
        ...,
        min_length=10
    )
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

                "player_client": [
                    "mweb"
                ],

                "pot_trace": [
                    "true"
                ],
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

            "cookies":
                bool(
                    os.environ.get(
                        "YOUTUBE_COOKIES",
                        ""
                    ).strip()
                ),

            "title":
                info.get("title"),

            "video_id":
                info.get("id"),

            "duration":
                info.get("duration"),

            "format_count":
                len(
                    info.get("formats") or []
                ),

            "logs":
                logs[-150:],
        }

    except Exception as e:

        return {

            "ok": False,

            "cookies":
                bool(
                    os.environ.get(
                        "YOUTUBE_COOKIES",
                        ""
                    ).strip()
                ),

            "error":
                str(e),

            "logs":
                logs[-150:],
        }


# ============================================================
# ★ 신규 통합 진단
#
# /api/diagnose?url=...
# ============================================================

@app.get("/api/diagnose")
def diagnose(
    url: str = Query(
        ...,
        min_length=10
    )
):

    validate_url(url)

    report = {

        "ok": True,

        "url": url,

        "environment": {},

        "youtube_http": {},

        "player_response": {},

        "clients": [],

        "diagnosis": {},
    }

    # --------------------------------------------------------
    # 1. yt-dlp
    # --------------------------------------------------------

    try:

        report["environment"]["yt_dlp"] = (
            pkg_version("yt-dlp")
        )

    except Exception as e:

        report["environment"]["yt_dlp"] = (
            f"error: {e}"
        )

    # --------------------------------------------------------
    # 2. Deno
    # --------------------------------------------------------

    report["environment"]["deno"] = {

        "available":
            command_exists("deno"),

        "version":
            get_command_version("deno"),
    }

    # --------------------------------------------------------
    # 3. FFmpeg
    # --------------------------------------------------------

    report["environment"]["ffmpeg"] = {

        "available":
            command_exists("ffmpeg"),

        "version":
            get_command_version("ffmpeg"),
    }

    # --------------------------------------------------------
    # 4. Cookie
    # --------------------------------------------------------

    report["environment"]["cookies"] = (
        inspect_cookie_configuration()
    )

    # --------------------------------------------------------
    # 5. BgUtils
    # --------------------------------------------------------

    bgutil = {

        "tcp": False,

        "ping": None,

        "error": None,
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

        bgutil["tcp"] = True

    except Exception as e:

        bgutil["error"] = str(e)

    try:

        with urllib.request.urlopen(
            (
                f"http://127.0.0.1:"
                f"{BGUTIL_PORT}/ping"
            ),
            timeout=5
        ) as response:

            bgutil["ping"] = (
                response.read()
                .decode(
                    errors="ignore"
                )[:500]
            )

    except Exception as e:

        if not bgutil["error"]:
            bgutil["error"] = str(e)

    report["environment"]["bgutil"] = bgutil

    # --------------------------------------------------------
    # 6. YouTube HTTP
    # --------------------------------------------------------

    report["youtube_http"] = (
        check_youtube_http(url)
    )

    # --------------------------------------------------------
    # 7. Primary Player Response
    # --------------------------------------------------------

    primary = {

        "success": False,

        "title": None,

        "video_id": None,

        "duration": None,

        "format_count": 0,

        "error": None,
    }

    try:

        options = get_base_options()

        options.update({
            "skip_download": True,
            "socket_timeout": 30,
        })

        with yt_dlp.YoutubeDL(
            options
        ) as ydl:

            info = ydl.extract_info(
                url,
                download=False
            )

        primary["success"] = True

        primary["title"] = (
            info.get("title")
        )

        primary["video_id"] = (
            info.get("id")
        )

        primary["duration"] = (
            info.get("duration")
        )

        primary["format_count"] = len(
            info.get("formats") or []
        )

    except Exception as e:

        primary["error"] = str(e)[:3000]

    report["player_response"] = primary

    # --------------------------------------------------------
    # 8. Client 비교
    #
    # Primary 성공이면 전체 client 테스트를 생략.
    # 실패할 때만 원인 파악을 위해 테스트.
    # --------------------------------------------------------

    if not primary["success"]:

        clients = [
            "mweb",
            "web_safari",
            "web_embedded",
            "android_vr",
            "tv",
        ]

        for client in clients:

            report["clients"].append(
                run_client_test(
                    url,
                    client
                )
            )

    # --------------------------------------------------------
    # 9. 최종 원인 분류
    # --------------------------------------------------------

    primary_error = (
        primary.get("error")
        or ""
    )

    http_status = (
        report["youtube_http"].get(
            "status"
        )
    )

    combined_error = (
        primary_error
        + "\n"
        + json.dumps(
            report["clients"],
            ensure_ascii=False
        )
    )

    code, message = classify_error(
        combined_error
    )

    # HTTP 429가 직접 확인된 경우 우선
    if http_status == 429:

        code = "YOUTUBE_429"

        message = (
            "Render 서버에서 YouTube 접근 시 "
            "HTTP 429가 확인되었습니다."
        )

    # Player Response
    elif (
        not primary["success"]
        and (
            code == "UNKNOWN"
            or code == "PLAYER_RESPONSE"
        )
    ):

        code = "PLAYER_RESPONSE"

        message = (
            "yt-dlp가 YouTube Player Response를 "
            "가져오지 못했습니다."
        )

    report["diagnosis"] = {

        "code":
            code,

        "message":
            message,

        "primary_error":
            primary_error[:3000],

        "recommendation":
            diagnosis_recommendation(
                code,
                report
            ),
    }

    return report


# ============================================================
# 진단 권고
# ============================================================

def diagnosis_recommendation(
    code: str,
    report: dict
):

    if code == "YOUTUBE_429":

        return (
            "YouTube HTTP 429가 확인되었습니다. "
            "yt-dlp/PO Token 설정을 확인하고 "
            "동일 서버에서 반복 요청을 줄인 뒤 "
            "재시험하세요."
        )

    if code == "YOUTUBE_BOT_CHECK":

        return (
            "YouTube가 서버 요청을 봇으로 판단하고 "
            "추가 확인을 요구하고 있습니다. "
            "Cookie와 PO Token 상태를 함께 확인하세요."
        )

    if code == "PLAYER_RESPONSE":

        return (
            "Player Response 추출 단계에서 실패했습니다. "
            "yt-dlp 버전, JS runtime, PO Token provider, "
            "Cookie 및 YouTube HTTP 상태를 순서대로 확인하세요."
        )

    if code == "HTTP_403":

        return (
            "YouTube가 스트림 요청을 403으로 거부했습니다. "
            "PO Token과 client별 결과를 확인하세요."
        )

    if code == "FFMPEG":

        return (
            "YouTube 추출 이후 FFmpeg 후처리 단계에서 "
            "문제가 발생했을 가능성이 있습니다."
        )

    if code == "FORMAT":

        return (
            "요청한 화질/형식을 현재 영상에서 "
            "사용할 수 없는 상태입니다."
        )

    if code == "VIDEO_UNAVAILABLE":

        return (
            "영상의 공개 상태 또는 접근 권한을 확인하세요."
        )

    return (
        "상세 로그와 client별 결과를 확인하세요."
    )
