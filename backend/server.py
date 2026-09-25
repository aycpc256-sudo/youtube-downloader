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
from typing import Optional

import yt_dlp

from fastapi import FastAPI, HTTPException, Query
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from starlette.background import BackgroundTask


# ============================================================
# FastAPI
# ============================================================

app = FastAPI(
    title="YouTube Downloader API",
    version="2.0-diagnostic",
)


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
# 공통 함수
# ============================================================

def validate_url(url: str):
    if not RE_URL.match(url):
        raise HTTPException(
            status_code=400,
            detail="URL 형식이 아닙니다."
        )


def safe_filename(name: str) -> str:
    name = re.sub(
        r'["\\/\r\n\x00-\x1f]',
        "",
        name
    )

    return name.strip() or "download"


def get_yt_dlp_version():
    try:
        return pkg_version("yt-dlp")
    except Exception:
        return "unknown"


# ============================================================
# Cookie
# ============================================================

def get_raw_cookie_value() -> str:
    return os.environ.get(
        "YOUTUBE_COOKIES",
        ""
    ).strip()


def prepare_youtube_cookies():
    """
    Render Environment Variable:

        YOUTUBE_COOKIES

    내용을 /tmp/youtube-cookies.txt 로 생성한다.

    쿠키 값 자체는 로그에 출력하지 않는다.
    """

    raw_value = get_raw_cookie_value()

    if not raw_value:
        return None

    cookie_text = raw_value

    # --------------------------------------------------------
    # Base64로 저장된 경우 지원
    # --------------------------------------------------------

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


def inspect_cookie_configuration():
    """
    쿠키 내용 자체는 절대 반환하지 않는다.
    """

    raw = get_raw_cookie_value()

    result = {
        "configured": bool(raw),
        "format": "not_configured",
        "valid_structure": False,
        "line_count": 0,
        "cookie_count": 0,
        "youtube_domain_count": 0,
        "message": "",
    }

    if not raw:
        result["message"] = (
            "YOUTUBE_COOKIES 환경변수가 없습니다."
        )
        return result

    text = raw

    # Base64 가능성
    if not raw.startswith("#"):

        try:
            decoded = base64.b64decode(
                raw,
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

    result["line_count"] = len(lines)

    first_line = ""

    for line in lines:
        if line.strip():
            first_line = line.strip()
            break

    if first_line == "# Netscape HTTP Cookie File":
        result["format"] = "netscape"
    elif first_line == "# HTTP Cookie File":
        result["format"] = "http_cookie"
    else:
        result["format"] = "unknown"

    cookie_count = 0
    youtube_domain_count = 0

    for line in lines:

        line = line.strip()

        if not line:
            continue

        if line.startswith("#"):
            continue

        parts = line.split("\t")

        if len(parts) >= 7:

            cookie_count += 1

            domain = parts[0].lower()

            if (
                "youtube.com" in domain
                or "google.com" in domain
                or "googleusercontent.com" in domain
            ):
                youtube_domain_count += 1

    result["cookie_count"] = cookie_count
    result["youtube_domain_count"] = youtube_domain_count

    result["valid_structure"] = (
        result["format"] in (
            "netscape",
            "http_cookie",
        )
        and cookie_count > 0
    )

    if not result["valid_structure"]:
        result["message"] = (
            "쿠키 파일 구조를 확인해야 합니다."
        )
    elif youtube_domain_count == 0:
        result["message"] = (
            "쿠키 구조는 정상이나 YouTube 관련 쿠키가 없습니다."
        )
    else:
        result["message"] = (
            "쿠키 파일 구조가 정상입니다."
        )

    return result


# ============================================================
# BgUtils
# ============================================================

def check_bgutil():
    result = {
        "ok": False,
        "tcp": False,
        "ping": False,
        "ping_response": None,
        "error": None,
    }

    # TCP
    try:

        sock = socket.create_connection(
            ("127.0.0.1", BGUTIL_PORT),
            timeout=3
        )

        sock.close()

        result["tcp"] = True

    except Exception as e:

        result["error"] = str(e)

    # HTTP ping
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
            result["ping_response"] = body[:300]

    except Exception as e:

        if not result["error"]:
            result["error"] = str(e)

    result["ok"] = (
        result["tcp"]
        and result["ping"]
    )

    return result


# ============================================================
# FFmpeg
# ============================================================

def check_ffmpeg():

    path = shutil.which("ffmpeg")

    if not path:
        return {
            "ok": False,
            "path": None,
            "version": None,
        }

    version_text = None

    try:

        proc = subprocess.run(
            [
                path,
                "-version"
            ],
            capture_output=True,
            text=True,
            timeout=5,
        )

        first_line = (
            proc.stdout or ""
        ).splitlines()

        if first_line:
            version_text = first_line[0]

    except Exception:
        pass

    return {
        "ok": True,
        "path": path,
        "version": version_text,
    }


# ============================================================
# YouTube HTTP 연결
# ============================================================

def check_youtube_http():

    result = {
        "ok": False,
        "status": None,
        "message": "",
    }

    url = "https://www.youtube.com/generate_204"

    request = urllib.request.Request(
        url,
        headers={
            "User-Agent": (
                "Mozilla/5.0 "
                "(Windows NT 10.0; Win64; x64) "
                "AppleWebKit/537.36 "
                "(KHTML, like Gecko) "
                "Chrome/131.0.0.0 Safari/537.36"
            )
        }
    )

    try:

        with urllib.request.urlopen(
            request,
            timeout=15
        ) as response:

            result["status"] = response.status
            result["ok"] = (
                200 <= response.status < 400
            )

            result["message"] = (
                "YouTube 기본 연결 성공"
            )

    except urllib.error.HTTPError as e:

        result["status"] = e.code

        if e.code == 429:
            result["message"] = (
                "HTTP 429: 요청 제한 가능성"
            )
        elif e.code in (401, 403):
            result["message"] = (
                f"HTTP {e.code}: 접근 제한 가능성"
            )
        else:
            result["message"] = (
                f"HTTP {e.code}"
            )

    except Exception as e:

        result["message"] = str(e)

    return result


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
            "youtubepot-bgutilhttp": {
                "base_url": (
                    f"http://127.0.0.1:{BGUTIL_PORT}"
                )
            }
        },
    }

    cookie_path = prepare_youtube_cookies()

    if cookie_path:
        options["cookiefile"] = cookie_path

    return options


# ============================================================
# 오류 분류
# ============================================================

def classify_error(error_text: str):

    text = (
        error_text or ""
    ).lower()

    if (
        "429" in text
        or "too many requests" in text
    ):
        return {
            "code": "YOUTUBE_429",
            "title": "YouTube 요청 제한",
            "message": (
                "Render 서버에서 YouTube 요청이 제한되고 있을 가능성이 있습니다."
            )
        }

    if (
        "sign in to confirm" in text
        or "not a bot" in text
        or "confirm you’re not a bot" in text
        or "confirm you're not a bot" in text
    ):
        return {
            "code": "YOUTUBE_BOT_CHECK",
            "title": "YouTube 봇 확인",
            "message": (
                "YouTube가 현재 서버 요청을 인증/봇 확인 대상으로 보고 있습니다."
            )
        }

    if (
        "failed to extract any player response"
        in text
    ):
        return {
            "code": "PLAYER_RESPONSE",
            "title": "Player Response 추출 실패",
            "message": (
                "YouTube player response를 가져오지 못했습니다."
            )
        }

    if (
        "video unavailable" in text
        or "this video is unavailable" in text
    ):
        return {
            "code": "VIDEO_UNAVAILABLE",
            "title": "영상 접근 불가",
            "message": (
                "해당 영상의 접근 상태를 확인해야 합니다."
            )
        }

    if (
        "403" in text
        or "forbidden" in text
    ):
        return {
            "code": "HTTP_403",
            "title": "접근 거부",
            "message": (
                "YouTube가 요청을 거부했습니다."
            )
        }

    if (
        "ffmpeg" in text
        and (
            "not found" in text
            or "not installed" in text
        )
    ):
        return {
            "code": "FFMPEG",
            "title": "FFmpeg 문제",
            "message": (
                "FFmpeg 설치 또는 실행 상태를 확인해야 합니다."
            )
        }

    if (
        "requested format" in text
        or "format is not available" in text
        or "no video formats" in text
    ):
        return {
            "code": "FORMAT",
            "title": "다운로드 포맷 문제",
            "message": (
                "현재 영상에서 요청한 포맷을 찾지 못했습니다."
            )
        }

    return {
        "code": "UNKNOWN",
        "title": "원인 미확인",
        "message": (
            "상세 진단 로그를 확인해야 합니다."
        )
    }


# ============================================================
# Client 테스트
# ============================================================

YOUTUBE_CLIENTS = [
    "mweb",
    "web_safari",
    "web_embedded",
    "android_vr",
    "tv",
]


def run_client_test(
    url: str,
    client: str
):

    result = {
        "client": client,
        "ok": False,
        "title": None,
        "video_id": None,
        "format_count": 0,
        "error": None,
        "classification": None,
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
                    "player_client": [client],
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

        result["ok"] = True
        result["title"] = info.get("title")
        result["video_id"] = info.get("id")
        result["format_count"] = len(
            info.get("formats") or []
        )

    except Exception as e:

        error_text = str(e)

        result["error"] = error_text[:2000]

        result["classification"] = (
            classify_error(error_text)
        )

    return result


# ============================================================
# Health
# ============================================================

@app.get("/api/health")
def health():

    bgutil = check_bgutil()

    return {
        "ok": True,
        "service": "youtube-downloader",

        "yt_dlp": get_yt_dlp_version(),

        "cookies": bool(
            get_raw_cookie_value()
        ),

        "cookie_structure": (
            inspect_cookie_configuration()
        ),

        "ffmpeg": (
            check_ffmpeg()
        ),

        "pot_provider": bgutil["ok"],

        "bgutil": bgutil,

        "js_runtime": "deno",

        "player_client": "mweb",
    }


# ============================================================
# 간단 테스트
# ============================================================

@app.get("/api/test123")
def test123():

    return {
        "ok": True,
        "message": "NEW_DIAGNOSTIC_SERVER_IS_RUNNING",
    }


# ============================================================
# 영상 정보
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
        "format_count": len(
            data.get("formats") or []
        ),
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
                    f"[vcodec^=avc1]+"
                    f"bestaudio[ext=m4a]/"

                    f"best[height<={height}]"
                    f"[vcodec^=avc1]/"

                    f"bestvideo[height<={height}]"
                    f"[ext=mp4]+"
                    f"bestaudio[ext=m4a]/"

                    f"best"
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

                "format": format_spec,

                "merge_output_format": "mp4",
            }

            media_type = "video/mp4"

        # ====================================================
        # 다운로드
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
            detail=(
                f"다운로드 실패: {e}"
            )
        )


# ============================================================
# 기존 /api/diag
# ============================================================

@app.get("/api/diag")
def diag():

    bgutil = check_bgutil()

    youtube = check_youtube_http()

    ffmpeg = check_ffmpeg()

    cookies = inspect_cookie_configuration()

    return {
        "yt_dlp_pkg": get_yt_dlp_version(),

        "cookies_configured": (
            cookies["configured"]
        ),

        "cookie_structure": cookies,

        "youtube_http": youtube,

        "bgutil_tcp": bgutil["tcp"],

        "bgutil_ping": (
            bgutil["ping_response"]
        ),

        "bgutil_ok": bgutil["ok"],

        "ffmpeg": ffmpeg,

        "message": (
            "diagnostic endpoint"
        ),
    }


# ============================================================
# Client 5종 테스트
# ============================================================

@app.get("/api/test-clients")
def test_clients(
    url: str = Query(..., min_length=10)
):

    validate_url(url)

    results = []

    for client in YOUTUBE_CLIENTS:

        results.append(
            run_client_test(
                url,
                client
            )
        )

    return {
        "ok": True,
        "url": url,
        "cookies": bool(
            get_raw_cookie_value()
        ),
        "results": results,
    }


# ============================================================
# 상세 YouTube Debug
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

                "player_client": [
                    "mweb"
                ],

                "pot_trace": [
                    "true"
                ],
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
                get_raw_cookie_value()
            ),

            "title": info.get(
                "title"
            ),

            "video_id": info.get(
                "id"
            ),

            "duration": info.get(
                "duration"
            ),

            "format_count": len(
                info.get("formats") or []
            ),

            "logs": logs[-200:],
        }

    except Exception as e:

        error_text = str(e)

        return {
            "ok": False,

            "cookies": bool(
                get_raw_cookie_value()
            ),

            "error": error_text,

            "classification": (
                classify_error(error_text)
            ),

            "logs": logs[-200:],
        }


# ============================================================
# ★ 통합 진단
# ============================================================

@app.get("/api/diagnose")
def diagnose(
    url: str = Query(..., min_length=10)
):

    validate_url(url)

    # --------------------------------------------------------
    # 기본 환경
    # --------------------------------------------------------

    cookies = inspect_cookie_configuration()

    bgutil = check_bgutil()

    ffmpeg = check_ffmpeg()

    youtube_http = check_youtube_http()

    # --------------------------------------------------------
    # 기본 URL 분석
    # --------------------------------------------------------

    primary = {
        "ok": False,
        "title": None,
        "video_id": None,
        "format_count": 0,
        "error": None,
        "classification": None,
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

        primary["ok"] = True
        primary["title"] = info.get("title")
        primary["video_id"] = info.get("id")
        primary["format_count"] = len(
            info.get("formats") or []
        )

    except Exception as e:

        error_text = str(e)

        primary["error"] = (
            error_text[:3000]
        )

        primary["classification"] = (
            classify_error(error_text)
        )

    # --------------------------------------------------------
    # Player client 테스트
    # --------------------------------------------------------

    clients = []

    # 기본 추출 성공이면 굳이 5개를 모두 돌리지 않는다.
    # 실패했을 때만 상세 비교를 한다.

    if not primary["ok"]:

        for client in YOUTUBE_CLIENTS:

            clients.append(
                run_client_test(
                    url,
                    client
                )
            )

    # --------------------------------------------------------
    # 최종 판단
    # --------------------------------------------------------

    diagnosis = {
        "code": "OK",
        "title": "정상",
        "message": "YouTube 영상 분석이 성공했습니다.",
    }

    if not cookies["configured"]:

        diagnosis = {
            "code": "COOKIE_NOT_CONFIGURED",
            "title": "쿠키 미설정",
            "message": (
                "YOUTUBE_COOKIES가 설정되어 있지 않습니다."
            ),
        }

    if (
        cookies["configured"]
        and not cookies["valid_structure"]
    ):

        diagnosis = {
            "code": "COOKIE_FORMAT",
            "title": "쿠키 형식 문제",
            "message": (
                "YOUTUBE_COOKIES의 Netscape 형식을 확인하세요."
            ),
        }

    if (
        youtube_http["status"] == 429
    ):

        diagnosis = {
            "code": "YOUTUBE_429",
            "title": "YouTube 요청 제한",
            "message": (
                "YouTube가 Render 서버의 요청을 제한하고 있습니다."
            ),
        }

    if not bgutil["ok"]:

        diagnosis = {
            "code": "BGUTIL",
            "title": "PO Token 서버 문제",
            "message": (
                "BgUtils 연결 또는 /ping 응답을 확인해야 합니다."
            ),
        }

    if not ffmpeg["ok"]:

        diagnosis = {
            "code": "FFMPEG",
            "title": "FFmpeg 문제",
            "message": (
                "FFmpeg가 설치되어 있지 않거나 PATH에서 찾을 수 없습니다."
            ),
        }

    if not primary["ok"]:

        classification = (
            primary.get("classification")
            or {}
        )

        code = classification.get(
            "code"
        )

        if code == "YOUTUBE_429":

            diagnosis = classification

        elif code == "YOUTUBE_BOT_CHECK":

            diagnosis = classification

        elif code == "PLAYER_RESPONSE":

            diagnosis = classification

        elif code == "HTTP_403":

            diagnosis = classification

        elif code == "VIDEO_UNAVAILABLE":

            diagnosis = classification

        else:

            diagnosis = {
                "code": "PLAYER_RESPONSE",
                "title": "YouTube 분석 실패",
                "message": (
                    "Player response 또는 YouTube 요청 상태를 확인하세요."
                ),
            }

    return {

        "ok": True,

        "url": url,

        "environment": {

            "yt_dlp": (
                get_yt_dlp_version()
            ),

            "cookies": cookies,

            "youtube_http": youtube_http,

            "bgutil": bgutil,

            "ffmpeg": ffmpeg,

        },

        "primary": primary,

        "clients": clients,

        "diagnosis": diagnosis,

    }
