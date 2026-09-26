import base64
import json
import os
import re
import shutil
import socket
import tempfile
import time
import urllib.request
from concurrent.futures import ThreadPoolExecutor, as_completed
from importlib.metadata import version as pkg_version
from pathlib import Path
from typing import Optional

import yt_dlp

from fastapi import FastAPI, HTTPException, Query
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from starlette.background import BackgroundTask


# ============================================================
# 기본 설정
# ============================================================

APP_TITLE = "YouTube Downloader API"

BGUTIL_HOST = "127.0.0.1"
BGUTIL_PORT = int(os.getenv("BGUTIL_PORT", "4416"))
BGUTIL_URL = f"http://{BGUTIL_HOST}:{BGUTIL_PORT}"

ALLOWED_ORIGINS = [
    "https://aycpc256-sudo.github.io",
    "http://localhost:8000",
    "http://127.0.0.1:8000",
]

# client 순서 (성공률 순)
YOUTUBE_CLIENTS = [
    "mweb",
    "web_safari",
    "web_embedded",
    "android_vr",
    "tv_downgraded",
    "tv",
]

CLIENT_CACHE = {}
CLIENT_CACHE_TTL = 10 * 60

RE_URL = re.compile(r"^https?://", re.IGNORECASE)

app = FastAPI(title=APP_TITLE)


# ============================================================
# CORS
# ============================================================

app.add_middleware(
    CORSMiddleware,
    allow_origins=ALLOWED_ORIGINS,
    allow_methods=["GET", "POST", "OPTIONS"],
    allow_headers=["*"],
    expose_headers=[
        "Content-Disposition",
        "Content-Length",
        "Content-Type",
        "X-YTDLP-Client",
    ],
)


# ============================================================
# 공통 함수
# ============================================================

def get_yt_dlp_version() -> str:
    try:
        return pkg_version("yt-dlp")
    except Exception:
        return "unknown"


def validate_url(url: str):
    if not RE_URL.match(url):
        raise HTTPException(
            status_code=400,
            detail="URL 형식이 아닙니다.",
        )


def safe_filename(name: str) -> str:
    """Content-Disposition 안전 처리 (제어문자/개행 제거)"""
    name = re.sub(r'["\\\r\n\x00-\x1f]', "", str(name))
    name = name.replace("/", "_")
    name = name.strip()
    return name or "download"


def classify_error(error_text: str) -> str:
    text = (error_text or "").lower()

    if "failed to extract any player response" in text:
        return "PLAYER_RESPONSE"
    if "player response" in text:
        return "PLAYER_RESPONSE"
    if "429" in text or "too many requests" in text:
        return "RATE_LIMIT"
    if "sign in to confirm" in text:
        return "BOT_CHECK"
    if "not a bot" in text:
        return "BOT_CHECK"
    if "login required" in text:
        return "LOGIN_REQUIRED"
    if "403" in text or "forbidden" in text:
        return "HTTP_403"
    if "404" in text or "not found" in text:
        return "NOT_FOUND"
    if "timed out" in text or "timeout" in text:
        return "TIMEOUT"
    if "js runtime" in text or "deno" in text:
        return "JS_RUNTIME"
    if "pot" in text or "po token" in text or "bgutil" in text:
        return "PO_TOKEN"
    if "ffmpeg" in text:
        return "FFMPEG"

    return "UNKNOWN"


def prepare_youtube_cookies() -> Optional[str]:
    """
    Render 환경변수 YOUTUBE_COOKIES 처리.
    raw Netscape 또는 base64 둘 다 지원.
    """
    value = os.getenv("YOUTUBE_COOKIES", "").strip()

    if not value:
        return None

    if "# Netscape HTTP Cookie File" in value:
        cookie_text = value
    else:
        try:
            decoded = base64.b64decode(value).decode("utf-8")
            if "# Netscape HTTP Cookie File" in decoded:
                cookie_text = decoded
            else:
                cookie_text = value
        except Exception:
            cookie_text = value

    path = "/tmp/youtube-cookies.txt"

    try:
        with open(path, "w", encoding="utf-8") as f:
            f.write(cookie_text)
        os.chmod(path, 0o600)
        return path
    except Exception:
        return None


# ============================================================
# yt-dlp 옵션
# ============================================================

def get_base_options(client: Optional[str] = None):
    options = {
        "quiet": True,
        "no_warnings": True,
        "noplaylist": True,
        "no_mtime": True,
        "no_overwrites": True,

        "retries": 2,
        "fragment_retries": 2,
        "socket_timeout": 20,

        # Deno JavaScript 런타임
        "js_runtimes": {
            "deno": {},
        },

        # EJS 원격 컴포넌트
        "remote_components": [
            "ejs:github",
        ],

        # BgUtils PO Token Provider
        "extractor_args": {
            "youtubepot-bgutilhttp": {
                "base_url": BGUTIL_URL,
            }
        },

        "nocheckcertificate": True,

        "user_agent": (
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
            "AppleWebKit/537.36 (KHTML, like Gecko) "
            "Chrome/140.0.0.0 Safari/537.36"
        ),
    }

    if client:
        options["extractor_args"]["youtube"] = {
            "player_client": [client],
        }

    cookie_path = prepare_youtube_cookies()
    if cookie_path:
        options["cookiefile"] = cookie_path

    return options


# ============================================================
# client cache
# ============================================================

def cleanup_client_cache():
    now = time.time()

    expired = [
        key for key, value in CLIENT_CACHE.items()
        if now - value["time"] > CLIENT_CACHE_TTL
    ]

    for key in expired:
        CLIENT_CACHE.pop(key, None)

    if len(CLIENT_CACHE) > 500:
        items = sorted(
            CLIENT_CACHE.items(),
            key=lambda x: x[1]["time"],
        )
        for key, _ in items[:100]:
            CLIENT_CACHE.pop(key, None)


def get_cached_client(url: str) -> Optional[str]:
    cleanup_client_cache()
    item = CLIENT_CACHE.get(url)
    if not item:
        return None
    if time.time() - item["time"] > CLIENT_CACHE_TTL:
        CLIENT_CACHE.pop(url, None)
        return None
    return item["client"]


def cache_client(url: str, client: str):
    cleanup_client_cache()
    CLIENT_CACHE[url] = {
        "client": client,
        "time": time.time(),
    }


def get_client_order(url: str):
    cached = get_cached_client(url)
    if not cached:
        return list(YOUTUBE_CLIENTS)

    return [
        cached,
        *[c for c in YOUTUBE_CLIENTS if c != cached],
    ]


# ============================================================
# 단일 client 정보 추출
# ============================================================

def extract_info_with_client(url: str, client: str):
    options = get_base_options(client)
    options.update({"skip_download": True})

    with yt_dlp.YoutubeDL(options) as ydl:
        return ydl.extract_info(url, download=False)


# ============================================================
# MP4 화질 추출
# ============================================================

def extract_mp4_qualities(data):
    heights = set()

    for fmt in data.get("formats", []):
        try:
            ext = fmt.get("ext")
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


# ============================================================
# fallback 정보 추출
# ============================================================

def extract_info_with_fallback(url: str):
    last_errors = []

    for client in get_client_order(url):
        try:
            data = extract_info_with_client(url, client)
            if data:
                cache_client(url, client)
                return {
                    "data": data,
                    "client": client,
                    "errors": last_errors,
                }
        except Exception as e:
            error_text = str(e)
            last_errors.append({
                "client": client,
                "code": classify_error(error_text),
                "error": error_text[:1500],
            })

    error_summary = " / ".join(
        f"{x['client']}: {x['code']}"
        for x in last_errors
    )

    raise HTTPException(
        status_code=400,
        detail={
            "code": "ALL_CLIENTS_FAILED",
            "message": "YouTube 영상 정보를 가져오지 못했습니다.",
            "clients": last_errors,
            "summary": error_summary,
        },
    )


# ============================================================
# health checks
# ============================================================

def check_deno():
    import subprocess

    try:
        p = subprocess.run(
            ["deno", "--version"],
            capture_output=True,
            text=True,
            timeout=5,
        )

        if p.returncode == 0:
            first_line = (
                p.stdout.strip().splitlines()[0]
                if p.stdout.strip()
                else ""
            )
            return {"ok": True, "version": first_line}

        return {"ok": False, "version": None}

    except Exception as e:
        return {"ok": False, "version": None, "error": str(e)}


def check_bgutil():
    # 1. TCP
    try:
        with socket.create_connection(
            (BGUTIL_HOST, BGUTIL_PORT),
            timeout=2,
        ):
            pass
    except Exception as e:
        return {
            "ok": False,
            "url": BGUTIL_URL,
            "error": f"TCP: {e}",
        }

    # 2. HTTP /ping
    try:
        with urllib.request.urlopen(
            f"{BGUTIL_URL}/ping",
            timeout=3,
        ) as r:
            body = r.read().decode(errors="ignore")[:200]

        return {
            "ok": True,
            "url": BGUTIL_URL,
            "ping": body,
        }

    except Exception as e:
        return {
            "ok": False,
            "url": BGUTIL_URL,
            "error": f"PING: {e}",
        }


@app.get("/api/health")
def health():
    deno = check_deno()
    bgutil = check_bgutil()

    return {
        "ok": True,
        "service": "youtube-downloader",
        "yt_dlp": get_yt_dlp_version(),
        "cookies": bool(os.getenv("YOUTUBE_COOKIES", "").strip()),
        "pot_provider": bgutil["ok"],
        "bgutil": bgutil,
        "deno": deno,
        "js_runtime": "deno",
        "player_clients": YOUTUBE_CLIENTS,
        "cached_clients": len(CLIENT_CACHE),
    }


# ============================================================
# 테스트 endpoint
# ============================================================

@app.get("/api/test123")
def test123():
    return {
        "ok": True,
        "message": "NEW_SERVER_PY_IS_RUNNING",
    }


# ============================================================
# 영상 정보
# ============================================================

@app.get("/api/info")
def info(url: str = Query(..., min_length=10)):
    validate_url(url)

    result = extract_info_with_fallback(url)

    data = result["data"]
    client = result["client"]
    mp4_qualities = extract_mp4_qualities(data)

    return {
        "ok": True,
        "id": data.get("id"),
        "title": data.get("title"),
        "duration": data.get("duration"),
        "uploader": data.get("uploader"),
        "thumbnail": data.get("thumbnail"),
        "client": client,
        "mp4_qualities": mp4_qualities,
        "format_count": len(data.get("formats", [])),
        "fallback_errors": result["errors"],
    }


# ============================================================
# 다운로드 옵션
# ============================================================

def build_download_options(
    tmpdir: str,
    format_name: str,
    quality: str,
    client: str,
):
    outtmpl = os.path.join(
        tmpdir,
        "%(title).150B [%(id)s].%(ext)s",
    )

    base = get_base_options(client)
    base.update({
        "outtmpl": outtmpl,
        "no_color": True,
        "paths": {"home": tmpdir},
    })

    if format_name == "mp3":
        bitrate = re.sub(r"[^\d]", "", quality) or "192"
        base.update({
            "format": "bestaudio/best",
            "postprocessors": [
                {
                    "key": "FFmpegExtractAudio",
                    "preferredcodec": "mp3",
                    "preferredquality": bitrate,
                }
            ],
        })
        return base, "audio/mpeg"

    if format_name == "m4a":
        base.update({
            "format": "bestaudio[ext=m4a]/bestaudio/best",
        })
        return base, "audio/mp4"

    # MP4
    m = re.search(r"(\d+)", quality)

    if m:
        height = m.group(1)
        fmt_spec = (
            f"bestvideo[height<={height}][ext=mp4]+"
            f"bestaudio[ext=m4a]/"
            f"bestvideo[height<={height}]+"
            f"bestaudio/"
            f"best[height<={height}][ext=mp4]/"
            f"best[height<={height}]/"
            f"best"
        )
    else:
        fmt_spec = (
            "bestvideo[ext=mp4]+"
            "bestaudio[ext=m4a]/"
            "bestvideo+bestaudio/"
            "best[ext=mp4]/"
            "best"
        )

    base.update({
        "format": fmt_spec,
        "merge_output_format": "mp4",
    })

    return base, "video/mp4"


# ============================================================
# 다운로드
# ============================================================

@app.get("/api/download")
def download(
    url: str = Query(..., min_length=10),
    format: str = Query("mp3", pattern="^(mp3|m4a|mp4)$"),
    quality: str = Query("192 kbps"),
    player_client: Optional[str] = Query(None),
):
    validate_url(url)

    if player_client:
        clients = [
            player_client,
            *[c for c in YOUTUBE_CLIENTS if c != player_client],
        ]
    else:
        clients = get_client_order(url)

    last_errors = []

    for client in clients:
        # ★ client마다 새 tmpdir
        tmpdir = tempfile.mkdtemp(prefix="ytdl_")

        try:
            ydl_opts, media_type = build_download_options(
                tmpdir=tmpdir,
                format_name=format,
                quality=quality,
                client=client,
            )

            with yt_dlp.YoutubeDL(ydl_opts) as ydl:
                ydl.extract_info(url, download=True)

            files = [
                f for f in Path(tmpdir).iterdir()
                if f.is_file()
                and not f.name.endswith(".part")
                and not f.name.endswith(".ytdl")
            ]

            if not files:
                raise RuntimeError("다운로드된 파일이 없습니다.")

            if format == "mp3":
                preferred = [f for f in files if f.suffix.lower() == ".mp3"]
            elif format == "m4a":
                preferred = [f for f in files if f.suffix.lower() == ".m4a"]
            elif format == "mp4":
                preferred = [f for f in files if f.suffix.lower() == ".mp4"]
            else:
                preferred = []

            candidates = preferred or files
            filepath = max(candidates, key=lambda f: f.stat().st_size)
            filename = safe_filename(filepath.name)

            cache_client(url, client)

            return FileResponse(
                path=str(filepath),
                media_type=media_type,
                filename=filename,
                headers={"X-YTDLP-Client": client},
                background=BackgroundTask(
                    shutil.rmtree,
                    tmpdir,
                    ignore_errors=True,
                ),
            )

        except Exception as e:
            error_text = str(e)

            last_errors.append({
                "client": client,
                "code": classify_error(error_text),
                "error": error_text[:1500],
            })

            # ★ 실패 시 즉시 tmpdir 정리
            shutil.rmtree(tmpdir, ignore_errors=True)
            continue

    raise HTTPException(
        status_code=500,
        detail={
            "code": "DOWNLOAD_ALL_CLIENTS_FAILED",
            "message": "모든 YouTube client에서 다운로드에 실패했습니다.",
            "clients": last_errors,
        },
    )


# ============================================================
# client 진단
# ============================================================

def diagnose_client(url: str, client: str):
    started = time.time()

    try:
        options = get_base_options(client)
        options.update({
            "skip_download": True,
            "socket_timeout": 10,   # ★ 축소
        })

        with yt_dlp.YoutubeDL(options) as ydl:
            info = ydl.extract_info(url, download=False)

        elapsed = round(time.time() - started, 2)

        return {
            "client": client,
            "ok": True,
            "seconds": elapsed,
            "title": info.get("title"),
            "id": info.get("id"),
            "format_count": len(info.get("formats", [])),
            "mp4_qualities": extract_mp4_qualities(info),
        }

    except Exception as e:
        elapsed = round(time.time() - started, 2)
        error_text = str(e)

        return {
            "client": client,
            "ok": False,
            "seconds": elapsed,
            "code": classify_error(error_text),
            "error": error_text[:1500],
        }


# ============================================================
# 전체 진단
# ============================================================

@app.get("/api/diagnose")
def diagnose(url: str = Query(..., min_length=10)):
    validate_url(url)

    started = time.time()
    results = []

    # ★ 워커 3개로 축소 (OOM 방지)
    max_workers = min(3, len(YOUTUBE_CLIENTS))

    with ThreadPoolExecutor(max_workers=max_workers) as executor:
        futures = {
            executor.submit(diagnose_client, url, client): client
            for client in YOUTUBE_CLIENTS
        }

        for future in as_completed(futures):
            try:
                results.append(future.result())
            except Exception as e:
                client = futures[future]
                results.append({
                    "client": client,
                    "ok": False,
                    "code": "DIAGNOSE_EXCEPTION",
                    "error": str(e),
                })

    # 순서 정렬
    order = {
        client: index
        for index, client in enumerate(YOUTUBE_CLIENTS)
    }
    results.sort(key=lambda x: order.get(x.get("client"), 999))

    successful = [x["client"] for x in results if x.get("ok")]

    return {
        "ok": True,
        "url": url,
        "elapsed_seconds": round(time.time() - started, 2),
        "yt_dlp": get_yt_dlp_version(),
        "deno": check_deno(),
        "bgutil": check_bgutil(),
        "cookies": bool(os.getenv("YOUTUBE_COOKIES", "").strip()),
        "clients": results,
        "successful_clients": successful,
        "recommended_next_client": successful[0] if successful else None,
    }


# ============================================================
# 호환 endpoint
# ============================================================

@app.get("/api/test-clients")
def test_clients(url: str = Query(..., min_length=10)):
    return diagnose(url)


@app.get("/api/diag")
def diag():
    return {
        "ok": True,
        "yt_dlp": get_yt_dlp_version(),
        "deno": check_deno(),
        "bgutil": check_bgutil(),
        "player_clients": YOUTUBE_CLIENTS,
        "bgutil_url": BGUTIL_URL,
    }
