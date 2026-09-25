import os
import re
import shutil
import tempfile
import subprocess

from pathlib import Path

import yt_dlp

from fastapi import FastAPI, HTTPException, Query
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from starlette.background import BackgroundTask


# ======================================================
# APP
# ======================================================

app = FastAPI(
    title="YouTube Downloader API"
)


# ======================================================
# CORS
# ======================================================

ALLOWED_ORIGINS = [
    "https://aycpc256-sudo.github.io",
    "http://localhost:8000",
    "http://127.0.0.1:8000",
]


app.add_middleware(
    CORSMiddleware,

    allow_origins=ALLOWED_ORIGINS,

    allow_methods=[
        "GET",
        "OPTIONS"
    ],

    allow_headers=["*"],
)


# ======================================================
# URL
# ======================================================

RE_URL = re.compile(
    r"^https?://",
    re.IGNORECASE
)


# ======================================================
# 파일명
# ======================================================

def safe_filename(name: str) -> str:

    name = (
        name
        .replace('"', "")
        .replace("\\", "")
        .replace("/", "_")
    )

    return name.strip() or "download"


# ======================================================
# 기본 yt-dlp 옵션
# ======================================================

def base_options():

    options = {
        "quiet": True,

        "no_warnings": True,

        "noplaylist": True,

        "no_mtime": True,

        "no_overwrites": True,

        "retries": 3,

        "nocheckcertificate": True,

        "user_agent": (
            "Mozilla/5.0 "
            "(Windows NT 10.0; Win64; x64) "
            "AppleWebKit/537.36 "
            "(KHTML, like Gecko) "
            "Chrome/122.0.0.0 "
            "Safari/537.36"
        ),
    }


    # --------------------------------------------------
    # 사용자 쿠키가 Render 환경변수에 있으면 사용
    # --------------------------------------------------

    cookie_text =
        os.getenv("YOUTUBE_COOKIES", "").strip()


    if cookie_text:

        cookie_file =
            "/tmp/youtube-cookies.txt"

        try:

            with open(
                cookie_file,
                "w",
                encoding="utf-8"
            ) as f:

                f.write(cookie_text)


            options["cookiefile"] =
                cookie_file

        except Exception:

            pass


    # --------------------------------------------------
    # BgUtils PO Token Provider
    # --------------------------------------------------

    bgutil_port =
        os.getenv(
            "BGUTIL_PORT",
            "4416"
        )


    options[
        "extractor_args"
    ] = {

        "youtube": {

            "pot_provider": [
                "bgutil:http"
            ],

            "player_client": [
                "mweb"
            ]

        }

    }


    options[
        "youtubepot-bgutilhttp-base-url"
    ] = (
        f"http://127.0.0.1:{bgutil_port}"
    )


    return options


# ======================================================
# HEALTH
# ======================================================

@app.get("/api/health")
def health():

    return {
        "ok": True,
        "service": "youtube-downloader",
        "yt_dlp": yt_dlp.version.__version__,
        "cookies": bool(
            os.getenv(
                "YOUTUBE_COOKIES"
            )
        ),
        "pot_provider": True,
    }


# ======================================================
# INFO
# ======================================================

@app.get("/api/info")
def info(
    url: str = Query(...)
):

    if not RE_URL.match(url):

        raise HTTPException(
            400,
            "URL 형식이 아닙니다."
        )


    opts = {
        **base_options(),

        "skip_download": True,

        "noplaylist": True,

        "quiet": True,

        "no_warnings": True,
    }


    try:

        with yt_dlp.YoutubeDL(
            opts
        ) as ydl:

            data =
                ydl.extract_info(
                    url,
                    download=False
                )


    except Exception as e:

        raise HTTPException(
            400,
            "영상 정보를 가져올 수 없습니다: "
            + str(e)
        )


    # --------------------------------------------------
    # MP4에서 사용할 실제 포맷만 정리
    # --------------------------------------------------

    formats = []


    for f in (
        data.get("formats") or []
    ):

        height = f.get("height")

        if not height:
            continue


        height = int(height)


        ext = (
            f.get("ext")
            or ""
        ).lower()


        video_ext = (
            f.get("video_ext")
            or ""
        ).lower()


        # 실제 MP4 계열 영상만
        if (
            ext == "mp4"
            or video_ext == "mp4"
        ):

            formats.append({

                "format_id":
                    f.get("format_id"),

                "height":
                    height,

                "width":
                    f.get("width"),

                "fps":
                    f.get("fps"),

                "ext":
                    ext,

                "video_ext":
                    video_ext,

                "has_audio":
                    bool(
                        f.get("acodec")
                        and
                        f.get("acodec")
                        != "none"
                    ),

                "filesize":
                    f.get("filesize"),

                "vcodec":
                    f.get("vcodec"),

            })


    # 중복 해상도 제거
    unique = {}

    for f in formats:

        h = f["height"]

        if h not in unique:

            unique[h] = f


    formats =
        sorted(
            unique.values(),
            key=lambda x:
                x["height"],
            reverse=True
        )


    return {

        "title":
            data.get("title"),

        "duration":
            data.get("duration"),

        "uploader":
            data.get("uploader"),

        "thumbnail":
            data.get("thumbnail"),

        "formats":
            formats,

    }


# ======================================================
# DOWNLOAD
# ======================================================

@app.get("/api/download")
def download(

    url: str = Query(...),

    format: str = Query(
        "mp3",
        pattern="^(mp3|m4a|mp4)$"
    ),

    quality: str = Query(
        "192 kbps"
    ),

):

    if not RE_URL.match(url):

        raise HTTPException(
            400,
            "URL 형식이 아닙니다."
        )


    tmpdir =
        tempfile.mkdtemp(
            prefix="ytdl_"
        )


    try:

        outtmpl = os.path.join(
            tmpdir,
            "%(title).150B "
            "[%(id)s].%(ext)s"
        )


        base = {
            **base_options(),

            "outtmpl":
                outtmpl,
        }


        # ==================================================
        # MP3
        # ==================================================

        if format == "mp3":

            bitrate =
                re.sub(
                    r"[^\d]",
                    "",
                    quality
                ) or "192"


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


            media_type =
                "audio/mpeg"


        # ==================================================
        # M4A
        # ==================================================

        elif format == "m4a":

            # YouTube가 제공하는
            # M4A 오디오 스트림 우선
            ydl_opts = {

                **base,

                "format":
                    "bestaudio[ext=m4a]/"
                    "bestaudio",

            }


            media_type =
                "audio/mp4"


        # ==================================================
        # MP4
        # ==================================================

        else:

            match =
                re.search(
                    r"(\d+)",
                    quality
                )


            if match:

                height =
                    int(
                        match.group(1)
                    )


                fmt_spec = (

                    f"bestvideo"
                    f"[height<={height}]"
                    f"[ext=mp4]+"
                    f"bestaudio"
                    f"[ext=m4a]/"

                    f"best"
                    f"[height<={height}]"
                    f"[ext=mp4]/"

                    f"best"
                    f"[height<={height}]"

                )

            else:

                fmt_spec = (

                    "bestvideo[ext=mp4]+"
                    "bestaudio[ext=m4a]/"

                    "best[ext=mp4]/"
                    "best"

                )


            ydl_opts = {

                **base,

                "format":
                    fmt_spec,

                "merge_output_format":
                    "mp4",

            }


            media_type =
                "video/mp4"


        # ==================================================
        # 실행
        # ==================================================

        with yt_dlp.YoutubeDL(
            ydl_opts
        ) as ydl:

            ydl.extract_info(
                url,
                download=True
            )


        # ==================================================
        # 파일 찾기
        # ==================================================

        files = [

            f

            for f in Path(
                tmpdir
            ).iterdir()

            if f.is_file()

        ]


        if not files:

            raise HTTPException(
                500,
                "다운로드된 파일이 없습니다."
            )


        filepath =
            max(
                files,
                key=lambda f:
                    f.stat().st_size
            )


        filename =
            safe_filename(
                filepath.name
            )


        return FileResponse(

            path=filepath,

            media_type=media_type,

            filename=filename,

            background=
                BackgroundTask(
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

            500,

            "다운로드 실패: "
            + str(e)

        )


# ======================================================
# 진단
# ======================================================

@app.get("/api/diagnose")
def diagnose(
    url: str = Query(...)
):

    result = {

        "yt_dlp":
            yt_dlp.version.__version__,

        "youtube_http":
            "확인 필요",

        "bgutil":
            "확인 필요",

        "ffmpeg":
            "확인 필요",

        "clients": [],

        "diagnosis": {}

    }


    # --------------------------------------------------
    # FFmpeg
    # --------------------------------------------------

    try:

        p =
            subprocess.run(
                [
                    "ffmpeg",
                    "-version"
                ],
                capture_output=True,
                text=True,
                timeout=10
            )


        if p.returncode == 0:

            result["ffmpeg"] =
                "정상"

        else:

            result["ffmpeg"] =
                "실패"


    except Exception:

        result["ffmpeg"] =
            "실패"


    # --------------------------------------------------
    # YouTube 정보 추출
    # --------------------------------------------------

    try:

        opts = {
            **base_options(),

            "skip_download":
                True,

            "noplaylist":
                True,

        }


        with yt_dlp.YoutubeDL(
            opts
        ) as ydl:

            data =
                ydl.extract_info(
                    url,
                    download=False
                )


        result["youtube_http"] =
            "연결/추출 성공"


        result["diagnosis"] = {

            "level": "ok",

            "title":
                "YouTube 영상 정보 추출 성공"

        }


        result["title"] =
            data.get("title")


        return result


    except Exception as e:

        message =
            str(e)


        result["youtube_http"] =
            "추출 실패"


        # --------------------------------------------------
        # 오류 분류
        # --------------------------------------------------

        if (
            "429" in message
            or
            "Too Many Requests"
            in message
        ):

            result["diagnosis"] = {

                "level": "error",

                "title":
                    "YouTube HTTP 429 / 요청 제한"

            }


        elif (
            "Sign in"
            in message
            or
            "bot" in message.lower()
        ):

            result["diagnosis"] = {

                "level": "error",

                "title":
                    "YouTube Bot / 로그인 확인 필요"

            }


        elif (
            "player response"
            in message.lower()
        ):

            result["diagnosis"] = {

                "level": "error",

                "title":
                    "Player Response 추출 실패"

            }


        else:

            result["diagnosis"] = {

                "level": "warn",

                "title":
                    "YouTube 영상 추출 실패"

            }


        result["error"] =
            message


        return result
