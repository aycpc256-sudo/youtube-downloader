import os
import re
import shutil
import socket
import subprocess
import tempfile
import urllib.request
from importlib.metadata import version as pkg_version
from pathlib import Path
from urllib.parse import urlparse

import yt_dlp
from fastapi import FastAPI, HTTPException, Query
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from starlette.background import BackgroundTask


app = FastAPI(title="Personal YouTube Downloader API")


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
    ],
)


# ============================================================
# 기본 설정
# ============================================================

HOSTS = {
    "youtube.com",
    "www.youtube.com",
    "m.youtube.com",
    "youtu.be",
}

BGUTIL_PORT = int(
    os.environ.get("BGUTIL_PORT", "4416")
)


# ============================================================
# 유틸리티
# ============================================================

def validate(url: str) -> str:
    p = urlparse(url)

    if (
        p.scheme not in {"http", "https"}
        or (p.hostname or "").lower() not in HOSTS
    ):
        raise HTTPException(
            status_code=400,
            detail="YouTube 주소만 사용할 수 있습니다.",
        )

    return url


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


def get_base_options():
    """
    yt-dlp 기본 옵션.
    BgUtils HTTP Provider를 로컬 4416 포트에 연결한다.
    """

    return {
        "outtmpl": "%(title)s.%(ext)s",

        "noplaylist": True,

        "quiet": True,

        "no_warnings": True,

        "retries": 3,

        "fragment_retries": 3,

        "continuedl": True,

        "socket_timeout": 30,

        "extractor_args": {
            "youtubepot-bgutilhttp": {
                "base_url": f"http://127.0.0.1:{BGUTIL_PORT}"
            }
        },
    }


# ============================================================
# Health
# ============================================================

@app.get("/api/health")
def health():
    """
    서버 기본 상태 확인.
    """

    try:
        yt_version = pkg_version("yt-dlp")
    except Exception:
        yt_version = "unknown"

    return {
        "ok": True,
        "service": "youtube-downloader",
        "yt_dlp": yt_version,
        "cookies": False,
        "user_agent": False,
        "pot_provider": True,
        "js_runtime": "deno",
        "player_client": "mweb",
    }


# ============================================================
# 진단 API
# ============================================================

@app.get("/api/diag")
def diag():

    result = {}

    # --------------------------------------------------------
    # 1. 실제 yt-dlp 패키지 버전
    # --------------------------------------------------------

    try:
        result["yt_dlp_pkg"] = pkg_version("yt-dlp")

    except Exception as e:
        result["yt_dlp_pkg"] = f"error: {e}"


    # --------------------------------------------------------
    # 2. BgUtils TCP 연결
    # --------------------------------------------------------

    try:

        sock = socket.create_connection(
            (
                "127.0.0.1",
                BGUTIL_PORT,
            ),
            timeout=3,
        )

        sock.close()

        result["bgutil_tcp"] = True

    except Exception as e:

        result["bgutil_tcp"] = (
            f"error: {e}"
        )


    # --------------------------------------------------------
    # 3. BgUtils HTTP 응답
    # --------------------------------------------------------

    try:

        url = (
            f"http://127.0.0.1:"
            f"{BGUTIL_PORT}/ping"
        )

        with urllib.request.urlopen(
            url,
            timeout=5,
        ) as response:

            body = response.read().decode(
                errors="ignore"
            )

            result["bgutil_ping"] = body[:200]

    except Exception as e:

        result["bgutil_ping"] = (
            f"error: {e}"
        )


    # --------------------------------------------------------
    # 4. yt-dlp 실제 실행
    #
    # 공식 테스트 영상에서
    # 다운로드 없이 제목만 가져온다.
    # --------------------------------------------------------

    try:

        process = subprocess.run(
            [
                "yt-dlp",

                "-v",

                "--skip-download",

                "--no-warnings",

                "--socket-timeout",
                "20",

                "-O",
                "title",

                "https://www.youtube.com/watch?v=BaW_jenozKc",
            ],

            capture_output=True,

            text=True,

            timeout=180,
        )

        output = (
            (process.stderr or "")
            + "\n"
            + (process.stdout or "")
        )

        lines = output.splitlines()


        result["ytdlp_exit_code"] = (
            process.returncode
        )


        # Provider 관련 로그
        result["pot_provider_lines"] = [
            line.strip()

            for line in lines

            if (
                "bgutil"
                in line.lower()
                or "[pot]"
                in line.lower()
                or "po token"
                in line.lower()
                or "po_token"
                in line.lower()
            )
        ][:30]


        # 오류 관련 로그
        result["errors"] = [
            line.strip()

            for line in lines

            if (
                "sign in"
                in line.lower()

                or "error"
                in line.lower()

                or "403"
                in line.lower()

                or "forbidden"
                in line.lower()

                or "bot"
                in line.lower()
            )
        ][:15]


    except Exception as e:

        result["ytdlp_run_error"] = str(e)


    return result


# ============================================================
# 다운로드
# ============================================================

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

    # --------------------------------------------------------
    # URL 검사
    # --------------------------------------------------------

    validate(url)


    # --------------------------------------------------------
    # 임시 폴더
    # --------------------------------------------------------

    tmp = tempfile.mkdtemp(
        prefix="ytdl_"
    )


    try:

        base = get_base_options()

        # 파일 저장 위치를 임시 폴더로 지정
        base["outtmpl"] = str(
            Path(tmp)
            / "%(title)s.%(ext)s"
        )


        # ====================================================
        # MP3
        # ====================================================

        if format == "mp3":

            q = re.sub(
                r"\D",
                "",
                quality,
            ) or "192"


            if q not in {
                "320",
                "256",
                "192",
                "128",
                "96",
            }:

                q = "192"


            postprocessors = [
                {
                    "key":
                        "FFmpegExtractAudio",

                    "preferredcodec":
                        "mp3",

                    "preferredquality":
                        q,
                }
            ]


            # 1차: 기본 설정
            options = {
                **base,

                "format":
                    "bestaudio/best",

                "postprocessors":
                    postprocessors,
            }


            media_type = "audio/mpeg"

            extensions = (
                ".mp3",
            )


        # ====================================================
        # MP4
        # ====================================================

        else:

            if quality == "best":

                fmt = (
                    "bestvideo+bestaudio/"
                    "best"
                )

            else:

                h = re.sub(
                    r"\D",
                    "",
                    quality,
                ) or "1080"


                fmt = (
                    f"bestvideo"
                    f"[height<={h}]"
                    f"[ext=mp4]+"
                    f"bestaudio[ext=m4a]/"

                    f"best"
                    f"[height<={h}]"
                    f"[ext=mp4]/"

                    f"best"
                    f"[height<={h}]/"

                    f"best"
                )


            options = {
                **base,

                "format": fmt,

                "merge_output_format":
                    "mp4",
            }


            media_type = "video/mp4"

            extensions = (
                ".mp4",
            )


        # ----------------------------------------------------
        # 다운로드
        # ----------------------------------------------------

        with yt_dlp.YoutubeDL(
            options
        ) as ydl:

            ydl.download(
                [url]
            )


        # ----------------------------------------------------
        # 결과 파일 찾기
        # ----------------------------------------------------

        files = [

            p

            for p in Path(tmp).iterdir()

            if (
                p.is_file()
                and p.stat().st_size > 0
                and p.suffix.lower()
                in extensions
            )
        ]


        if not files:

            raise HTTPException(
                status_code=500,

                detail=(
                    "다운로드된 파일을 "
                    "찾지 못했습니다."
                ),
            )


        # 가장 큰 파일 선택
        path = max(
            files,
            key=lambda p:
                p.stat().st_size,
        )


        # ----------------------------------------------------
        # 파일 반환
        # ----------------------------------------------------

        return FileResponse(

            path,

            media_type=media_type,

            filename=safe_filename(
                path.name
            ),

            background=BackgroundTask(
                shutil.rmtree,

                tmp,

                ignore_errors=True,
            ),
        )


    # ========================================================
    # HTTPException
    # ========================================================

    except HTTPException:

        shutil.rmtree(
            tmp,
            ignore_errors=True,
        )

        raise


    # ========================================================
    # 기타 오류
    # ========================================================

    except Exception as e:

        shutil.rmtree(
            tmp,
            ignore_errors=True,
        )

        raise HTTPException(

            status_code=500,

            detail=(
                "다운로드 실패: "
                f"{e}"
            ),
        )
