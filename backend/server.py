import base64
import json
import os
import re
import shutil
import subprocess
import tempfile
import time
from pathlib import Path
from typing import Optional

import yt_dlp
from fastapi import FastAPI, HTTPException, Query
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from starlette.background import BackgroundTask


# =========================================================
# 기본 설정
# =========================================================

app = FastAPI(title="YouTube Downloader API")


ALLOWED_ORIGINS = [
    "https://aycpc256-sudo.github.io",
    "http://localhost:8000",
    "http://127.0.0.1:8000",
]


app.add_middleware(
    CORSMiddleware,
    allow_origins=ALLOWED_ORIGINS,
    allow_methods=["GET", "POST", "OPTIONS"],
    allow_headers=["*"],
)


BGUTIL_PORT = int(os.getenv("BGUTIL_PORT", "4416"))

RE_URL = re.compile(r"^https?://", re.IGNORECASE)


# =========================================================
# YouTube client 후보
#
# 하나를 고정하지 않는다.
# 앞에서 성공하는 client를 사용한다.
# =========================================================

YOUTUBE_CLIENTS = [
    "mweb",
    "web_safari",
    "web_embedded",
    "android_vr",
    "tv",
]


# =========================================================
# 마지막 성공 client 임시 캐시
#
# Render 인스턴스 메모리 안에서만 유지.
# 없어도 fallback이 다시 동작한다.
# =========================================================

CLIENT_CACHE = {}

CLIENT_CACHE_TTL = 10 * 60


def get_cached_client(url: str) -> Optional[str]:
    item = CLIENT_CACHE.get(url)

    if not item:
        return None

    client, timestamp = item

    if time.time() - timestamp > CLIENT_CACHE_TTL:
        CLIENT_CACHE.pop(url, None)
        return None

    return client


def cache_client(url: str, client: str):
    CLIENT_CACHE[url] = (client, time.time())


# =========================================================
# URL / 파일명
# =========================================================

def validate_url(url: str):
    if not RE_URL.match(url):
        raise HTTPException(
            status_code=400,
            detail={
                "code": "INVALID_URL",
                "message": "URL 형식이 아닙니다.",
            },
        )


def safe_filename(name: str) -> str:
    name = name.replace('"', "")
    name = name.replace("\\", "")
    name = name.replace("/", "_")
    name = name.strip()

    return name or "download"


# =========================================================
# YouTube cookies
#
# Render Environment Variable:
# YOUTUBE_COOKIES
#
# Netscape 형식 또는 base64
# =========================================================

def prepare_youtube_cookies() -> Optional[str]:
    raw = os.getenv("YOUTUBE_COOKIES", "").strip()

    if not raw:
        return None

    if raw.startswith("# Netscape HTTP Cookie File"):
        path = "/tmp/youtube-cookies.txt"

        try:
            Path(path).write_text(
                raw,
                encoding="utf-8",
            )
            return path
        except Exception:
            return None

    # base64 cookies 지원
    try:
        decoded = base64.b64decode(raw).decode("utf-8")

        if decoded.startswith("# Netscape HTTP Cookie File"):
            path = "/tmp/youtube-cookies.txt"

            Path(path).write_text(
                decoded,
                encoding="utf-8",
            )

            return path

    except Exception:
        pass

    return None


# =========================================================
# 기본 yt-dlp 옵션
# =========================================================

def get_base_options(player_client: str):
    options = {
        "quiet": True,
        "no_warnings": True,
        "noplaylist": True,
        "no_mtime": True,
        "no_overwrites": True,

        "retries": 2,
        "fragment_retries": 2,

        "socket_timeout": 30,

        # 현재 yt-dlp YouTube JS challenge 대응
        "js_runtimes": {
            "deno": {},
        },

        # yt-dlp-ejs remote component
        "remote_components": {
            "ejs": ["github"],
        },

        "extractor_args": {
            "youtube": {
                "player_client": [player_client],
            },

            "youtubepot-bgutilhttp": {
                "base_url": (
                    f"http://127.0.0.1:{BGUTIL_PORT}"
                ),
            },
        },
    }

    cookie_path = prepare_youtube_cookies()

    if cookie_path:
        options["cookiefile"] = cookie_path

    return options


# =========================================================
# yt-dlp 버전
# =========================================================

def get_yt_dlp_version():
    try:
        return yt_dlp.version.__version__
    except Exception:
        try:
            return yt_dlp.version.VERSION
        except Exception:
            return "unknown"


# =========================================================
# Deno 검사
# =========================================================

def check_deno():
    try:
        result = subprocess.run(
            ["deno", "--version"],
            capture_output=True,
            text=True,
            timeout=10,
        )

        if result.returncode == 0:
            first_line = (
                result.stdout.strip().splitlines()[0]
                if result.stdout.strip()
                else ""
            )

            return {
                "ok": True,
                "version": first_line,
            }

        return {
            "ok": False,
            "version": None,
            "error": result.stderr.strip()[:500],
        }

    except Exception as e:
        return {
            "ok": False,
            "version": None,
            "error": str(e),
        }


# =========================================================
# FFmpeg 검사
# =========================================================

def check_ffmpeg():
    try:
        result = subprocess.run(
            ["ffmpeg", "-version"],
            capture_output=True,
            text=True,
            timeout=10,
        )

        if result.returncode == 0:
            first_line = (
                result.stdout.strip().splitlines()[0]
                if result.stdout.strip()
                else ""
            )

            return {
                "ok": True,
                "version": first_line,
            }

        return {
            "ok": False,
            "version": None,
        }

    except Exception as e:
        return {
            "ok": False,
            "version": None,
            "error": str(e),
        }


# =========================================================
# 에러 분류
# =========================================================

def classify_error(error_text: str) -> str:
    text = (error_text or "").lower()

    if "failed to extract any player response" in text:
        return "PLAYER_RESPONSE"

    if "429" in text:
        return "RATE_LIMIT"

    if "sign in" in text or "login" in text:
        return "BOT_CHECK"

    if "403" in text:
        return "FORBIDDEN"

    if "po token" in text or "pot" in text:
        return "PO_TOKEN"

    if "javascript" in text or "deno" in text:
        return "JAVASCRIPT"

    if "ffmpeg" in text:
        return "FFMPEG"

    if "timed out" in text or "timeout" in text:
        return "TIMEOUT"

    return "UNKNOWN"


# =========================================================
# MP4 화질 추출
# =========================================================

def extract_mp4_qualities(data):
    heights = set()

    for fmt in data.get("formats", []) or []:
        try:
            ext = (fmt.get("ext") or "").lower()
            height = fmt.get("height")
            vcodec = fmt.get("vcodec")

            if (
                ext == "mp4"
                and height
                and vcodec
                and vcodec != "none"
            ):
                heights.add(int(height))

        except Exception:
            continue

    return sorted(heights, reverse=True)


# =========================================================
# 하나의 client로 영상 정보 추출
# =========================================================

def extract_with_client(url: str, client: str):
    options = get_base_options(client)

    with yt_dlp.YoutubeDL(options) as ydl:
        return ydl.extract_info(
            url,
            download=False,
        )


# =========================================================
# fallback 정보 추출
#
# cached client가 있으면 먼저 사용
# 그 후 전체 후보군
# =========================================================

def extract_with_fallback(url: str):
    errors = []

    cached = get_cached_client(url)

    clients = []

    if cached:
        clients.append(cached)

    for client in YOUTUBE_CLIENTS:
        if client not in clients:
            clients.append(client)

    for client in clients:
        try:
            data = extract_with_client(
                url,
                client,
            )

            if data:
                cache_client(url, client)

                return {
                    "data": data,
                    "client": client,
                    "attempts": errors,
                }

        except Exception as e:
            error_text = str(e)

            errors.append(
                {
                    "client": client,
                    "ok": False,
                    "code": classify_error(error_text),
                    "error": error_text[:1500],
                }
            )

    raise RuntimeError(
        json.dumps(
            {
                "message": (
                    "모든 YouTube client에서 "
                    "영상 정보를 가져오지 못했습니다."
                ),
                "attempts": errors,
            },
            ensure_ascii=False,
        )
    )


# =========================================================
# health
# =========================================================

@app.get("/api/health")
def health():

    return {
        "ok": True,
        "service": "youtube-downloader",
        "yt_dlp": get_yt_dlp_version(),
        "cookies": bool(
            os.getenv("YOUTUBE_COOKIES", "").strip()
        ),
        "pot_provider": True,
        "js_runtime": "deno",
        "player_client": "fallback",
        "clients": YOUTUBE_CLIENTS,
        "deno": check_deno(),
        "ffmpeg": check_ffmpeg(),
    }


# =========================================================
# test123
# =========================================================

@app.get("/api/test123")
def test123():

    return {
        "ok": True,
        "message": "NEW_SERVER_PY_IS_RUNNING_V2",
    }


# =========================================================
# info
# =========================================================

@app.get("/api/info")
def info(
    url: str = Query(
        ...,
        min_length=10,
    )
):

    validate_url(url)

    try:
        result = extract_with_fallback(url)

        data = result["data"]
        client = result["client"]

        qualities = extract_mp4_qualities(data)

        return {
            "ok": True,
            "id": data.get("id"),
            "title": data.get("title"),
            "duration": data.get("duration"),
            "uploader": data.get("uploader"),
            "thumbnail": data.get("thumbnail"),

            "mp4_qualities": qualities,

            "format_count": len(
                data.get("formats", []) or []
            ),

            "player_client": client,

            "attempts": result["attempts"],
        }

    except Exception as e:

        error_text = str(e)

        raise HTTPException(
            status_code=400,
            detail={
                "code": classify_error(error_text),
                "message": error_text,
            },
        )


# =========================================================
# 다운로드용 client 후보
# =========================================================

def get_download_clients(
    url: str,
    preferred_client: Optional[str] = None,
):
    clients = []

    if preferred_client in YOUTUBE_CLIENTS:
        clients.append(preferred_client)

    cached = get_cached_client(url)

    if cached and cached not in clients:
        clients.append(cached)

    for client in YOUTUBE_CLIENTS:
        if client not in clients:
            clients.append(client)

    return clients


# =========================================================
# 실제 다운로드
# =========================================================

@app.get("/api/download")
def download(
    url: str = Query(...),
    format: str = Query(
        "mp3",
        pattern="^(mp3|m4a|mp4)$",
    ),
    quality: str = Query("192 kbps"),
    player_client: Optional[str] = Query(None),
):

    validate_url(url)

    tmpdir = tempfile.mkdtemp(
        prefix="ytdl_"
    )

    try:

        outtmpl = os.path.join(
            tmpdir,
            "%(title).150B [%(id)s].%(ext)s",
        )

        clients = get_download_clients(
            url,
            player_client,
        )

        last_errors = []

        for client in clients:

            try:

                base = get_base_options(client)

                base["outtmpl"] = outtmpl

                # -----------------------------------------
                # MP3
                # -----------------------------------------

                if format == "mp3":

                    bitrate = (
                        re.sub(
                            r"[^\d]",
                            "",
                            quality,
                        )
                        or "192"
                    )

                    ydl_opts = {
                        **base,

                        "format": (
                            "bestaudio/best"
                        ),

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

                # -----------------------------------------
                # M4A
                # -----------------------------------------

                elif format == "m4a":

                    ydl_opts = {
                        **base,

                        "format": (
                            "bestaudio[ext=m4a]/"
                            "bestaudio/best"
                        ),
                    }

                    media_type = "audio/mp4"

                # -----------------------------------------
                # MP4
                # -----------------------------------------

                else:

                    match = re.search(
                        r"(\d+)",
                        quality,
                    )

                    if match:

                        height = match.group(1)

                        fmt_spec = (
                            f"bestvideo[height<={height}]"
                            f"[ext=mp4]+"
                            f"bestaudio[ext=m4a]/"

                            f"bestvideo[height<={height}]"
                            f"+bestaudio/"

                            f"best[height<={height}]"
                            f"[ext=mp4]/"

                            "best[ext=mp4]/best"
                        )

                    else:

                        fmt_spec = (
                            "bestvideo[ext=mp4]+"
                            "bestaudio[ext=m4a]/"

                            "bestvideo+bestaudio/"

                            "best[ext=mp4]/best"
                        )

                    ydl_opts = {
                        **base,

                        "format": fmt_spec,

                        "merge_output_format":
                            "mp4",
                    }

                    media_type = "video/mp4"

                # -----------------------------------------
                # 실제 다운로드
                # -----------------------------------------

                with yt_dlp.YoutubeDL(
                    ydl_opts
                ) as ydl:

                    ydl.extract_info(
                        url,
                        download=True,
                    )

                files = [
                    f
                    for f in Path(
                        tmpdir
                    ).iterdir()
                    if f.is_file()
                ]

                if not files:
                    raise RuntimeError(
                        "다운로드된 파일이 없습니다."
                    )

                # 확장자 우선
                if format == "mp4":

                    preferred = [
                        f
                        for f in files
                        if f.suffix.lower()
                        == ".mp4"
                    ]

                elif format == "m4a":

                    preferred = [
                        f
                        for f in files
                        if f.suffix.lower()
                        == ".m4a"
                    ]

                else:

                    preferred = [
                        f
                        for f in files
                        if f.suffix.lower()
                        == ".mp3"
                    ]

                filepath = (
                    max(
                        preferred or files,
                        key=lambda f:
                            f.stat().st_size,
                    )
                )

                cache_client(
                    url,
                    client,
                )

                filename = safe_filename(
                    filepath.name
                )

                return FileResponse(
                    path=filepath,
                    media_type=media_type,
                    filename=filename,
                    background=BackgroundTask(
                        shutil.rmtree,
                        tmpdir,
                        ignore_errors=True,
                    ),
                )

            except Exception as e:

                error_text = str(e)

                last_errors.append(
                    {
                        "client": client,
                        "code":
                            classify_error(
                                error_text
                            ),
                        "error":
                            error_text[:1500],
                    }
                )

                continue

        raise RuntimeError(
            json.dumps(
                {
                    "message":
                        "모든 client에서 다운로드에 실패했습니다.",
                    "attempts":
                        last_errors,
                },
                ensure_ascii=False,
            )
        )

    except HTTPException:

        shutil.rmtree(
            tmpdir,
            ignore_errors=True,
        )

        raise

    except Exception as e:

        shutil.rmtree(
            tmpdir,
            ignore_errors=True,
        )

        error_text = str(e)

        raise HTTPException(
            status_code=500,
            detail={
                "code":
                    classify_error(
                        error_text
                    ),
                "message":
                    error_text,
            },
        )


# =========================================================
# client 하나 진단
# =========================================================

def diagnose_client(
    url: str,
    client: str,
):

    command = [
        "yt-dlp",

        "--no-warnings",
        "--skip-download",
        "--no-playlist",

        "--socket-timeout",
        "15",

        "--js-runtimes",
        "deno",

        "--remote-components",
        "ejs:github",

        "--extractor-args",
        f"youtube:player_client={client}",

        "--extractor-args",
        (
            "youtubepot-bgutilhttp:"
            f"base_url=http://127.0.0.1:{BGUTIL_PORT}"
        ),

        "--print",
        "%(id)s|%(title)s",

        url,
    ]

    cookie_path = prepare_youtube_cookies()

    if cookie_path:
        command.extend(
            [
                "--cookies",
                cookie_path,
            ]
        )

    started = time.time()

    try:

        result = subprocess.run(
            command,
            capture_output=True,
            text=True,
            timeout=20,
        )

        elapsed = round(
            time.time() - started,
            2,
        )

        stdout = (
            result.stdout.strip()
            if result.stdout
            else ""
        )

        stderr = (
            result.stderr.strip()
            if result.stderr
            else ""
        )

        if result.returncode == 0:

            return {
                "client": client,
                "ok": True,
                "elapsed": elapsed,
                "output":
                    stdout[:1000],
            }

        return {
            "client": client,
            "ok": False,
            "elapsed": elapsed,
            "code":
                classify_error(
                    stderr
                    or stdout
                ),
            "error":
                (
                    stderr
                    or stdout
                    or "yt-dlp 실패"
                )[:1500],
        }

    except subprocess.TimeoutExpired:

        return {
            "client": client,
            "ok": False,
            "code": "TIMEOUT",
            "error":
                "20초 timeout",
        }

    except Exception as e:

        return {
            "client": client,
            "ok": False,
            "code":
                classify_error(
                    str(e)
                ),
            "error":
                str(e)[:1500],
        }


# =========================================================
# 종합 진단
# =========================================================

@app.get("/api/diagnose")
def diagnose(
    url: str = Query(
        ...,
        min_length=10,
    )
):

    validate_url(url)

    results = []

    for client in YOUTUBE_CLIENTS:

        result = diagnose_client(
            url,
            client,
        )

        results.append(result)

        # 하나라도 성공하면 캐시
        if result.get("ok"):
            cache_client(
                url,
                client,
            )

    return {
        "ok": True,

        "url": url,

        "yt_dlp":
            get_yt_dlp_version(),

        "deno":
            check_deno(),

        "ffmpeg":
            check_ffmpeg(),

        "cookies":
            bool(
                os.getenv(
                    "YOUTUBE_COOKIES",
                    "",
                ).strip()
            ),

        "pot_provider": True,

        "clients":
            results,
    }


# =========================================================
# test-clients
# =========================================================

@app.get("/api/test-clients")
def test_clients(
    url: str = Query(
        ...,
        min_length=10,
    )
):

    validate_url(url)

    results = []

    for client in YOUTUBE_CLIENTS:

        try:

            data = extract_with_client(
                url,
                client,
            )

            results.append(
                {
                    "client": client,
                    "ok": True,
                    "id":
                        data.get("id"),
                    "title":
                        data.get("title"),
                    "format_count":
                        len(
                            data.get(
                                "formats",
                                [],
                            )
                            or []
                        ),
                }
            )

        except Exception as e:

            results.append(
                {
                    "client": client,
                    "ok": False,
                    "code":
                        classify_error(
                            str(e)
                        ),
                    "error":
                        str(e)[:1500],
                }
            )

    return {
        "ok": True,
        "results": results,
    }


# =========================================================
# 간단 진단 alias
# =========================================================

@app.get("/api/diag")
def diag():

    return {
        "ok": True,
        "yt_dlp":
            get_yt_dlp_version(),
        "deno":
            check_deno(),
        "ffmpeg":
            check_ffmpeg(),
        "cookies":
            bool(
                os.getenv(
                    "YOUTUBE_COOKIES",
                    "",
                ).strip()
            ),
        "pot_provider": True,
        "clients": YOUTUBE_CLIENTS,
    }


# =========================================================
# 디버그 endpoint
# =========================================================

@app.get("/api/test-youtube-debug")
def test_youtube_debug(
    url: str = Query(
        ...,
        min_length=10,
    )
):

    validate_url(url)

    try:

        result = extract_with_fallback(
            url
        )

        data = result["data"]

        return {
            "ok": True,
            "player_client":
                result["client"],
            "id":
                data.get("id"),
            "title":
                data.get("title"),
            "format_count":
                len(
                    data.get(
                        "formats",
                        [],
                    )
                    or []
                ),
            "mp4_qualities":
                extract_mp4_qualities(
                    data
                ),
            "attempts":
                result["attempts"],
        }

    except Exception as e:

        raise HTTPException(
            status_code=400,
            detail={
                "code":
                    classify_error(
                        str(e)
                    ),
                "message":
                    str(e),
            },
        )
