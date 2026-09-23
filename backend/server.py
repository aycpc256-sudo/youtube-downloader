import base64
import os
import re
import shutil
import socket
import subprocess
import tempfile
import threading
import time
import urllib.request
import uuid
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
    allow_methods=["GET", "POST", "OPTIONS"],
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

# 작업(job)이 이 시간(초)보다 오래 방치되면 자동 정리한다.
JOB_MAX_AGE_SECONDS = 2 * 60 * 60

# 저사양 서버(Render 무료 플랜 등)에서 동시에 처리할 수 있는
# 다운로드/인코딩 작업 수 상한. 초과 시 429로 응답한다.
MAX_CONCURRENT_JOBS = 2


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

    if not raw_value.startswith("#"):
        try:
            decoded = base64.b64decode(
                raw_value,
                validate=True
            ).decode("utf-8", errors="ignore")

            if (
                decoded.startswith("# Netscape HTTP Cookie File")
                or decoded.startswith("# HTTP Cookie File")
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
        "socket_timeout": 60,
        "http_chunk_size": 10485760,

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
# 작업(Job) 관리 - 전방 선언
#
# run_ffmpeg_with_progress()가 JOBS/JOBS_LOCK/JobCancelled를
# 참조하므로, 아래 코덱/변환 함수들보다 먼저 정의한다.
# ============================================================

JOBS: dict = {}
JOBS_LOCK = threading.Lock()


class JobCancelled(Exception):
    pass


# ============================================================
# ffmpeg 진행률 추적 실행기
#
# ffmpeg의 '-progress pipe:1' 옵션으로 out_time_ms(진행 시간),
# speed(배속) 등을 실시간으로 읽어와 job 상태(progress/message)에
# 반영한다. 후처리(오디오 인코딩, iOS 호환 변환 등) 단계에서도
# 다운로드 단계처럼 실시간 진행률/속도를 보여주기 위함이며,
# 루프 안에서 cancel_requested를 체크해 취소도 즉시 반영한다.
# ============================================================

def run_ffmpeg_with_progress(
    cmd: list,
    duration: float,
    job_id: str,
    message_prefix: str = "변환 중",
    timeout_seconds: float = None,
):
    tracked_cmd = [cmd[0], "-progress", "pipe:1", "-nostats"] + cmd[1:]

    proc = subprocess.Popen(
        tracked_cmd,
        stdout=subprocess.PIPE,
        stderr=subprocess.DEVNULL,
        text=True,
        bufsize=1,
    )

    start_time = time.time()
    last_percent = 0.0

    def _job_cancelled():
        with JOBS_LOCK:
            job = JOBS.get(job_id)
            return bool(job and job.get("cancel_requested"))

    try:
        for line in proc.stdout:
            if timeout_seconds and (time.time() - start_time) > timeout_seconds:
                proc.kill()
                raise subprocess.TimeoutExpired(tracked_cmd, timeout_seconds)

            if job_id and _job_cancelled():
                proc.kill()
                raise JobCancelled()

            line = line.strip()
            if "=" not in line:
                continue

            key, _, value = line.partition("=")
            value = value.strip()

            if key == "out_time_ms" and duration:
                try:
                    seconds = int(value) / 1_000_000
                    last_percent = min(seconds / duration * 100, 99)
                except ValueError:
                    pass

                if job_id:
                    with JOBS_LOCK:
                        if job_id in JOBS:
                            JOBS[job_id]["progress"] = round(last_percent, 1)
                            JOBS[job_id]["message"] = (
                                f"{message_prefix}... {round(last_percent)}%"
                            )

            elif key == "speed" and value and value != "0x":
                if job_id:
                    with JOBS_LOCK:
                        if job_id in JOBS:
                            JOBS[job_id]["message"] = (
                                f"{message_prefix}... {round(last_percent)}% ({value})"
                            )

        proc.wait(timeout=30)

    except JobCancelled:
        if proc.poll() is None:
            proc.kill()
        raise
    except subprocess.TimeoutExpired:
        if proc.poll() is None:
            proc.kill()
        raise
    finally:
        if proc.poll() is None:
            proc.terminate()

    if proc.returncode != 0:
        raise subprocess.CalledProcessError(proc.returncode, tracked_cmd)


# ============================================================
# 코덱/길이 확인
# ============================================================

def probe_codecs(filepath: Path):
    try:
        proc = subprocess.run(
            [
                "ffprobe", "-v", "error",
                "-select_streams", "v:0",
                "-show_entries", "stream=codec_name",
                "-of", "csv=p=0",
                str(filepath),
            ],
            capture_output=True,
            text=True,
            timeout=30,
        )
        video_codec = proc.stdout.strip().lower()
    except Exception:
        video_codec = ""

    try:
        proc = subprocess.run(
            [
                "ffprobe", "-v", "error",
                "-select_streams", "a:0",
                "-show_entries", "stream=codec_name",
                "-of", "csv=p=0",
                str(filepath),
            ],
            capture_output=True,
            text=True,
            timeout=30,
        )
        audio_codec = proc.stdout.strip().lower()
    except Exception:
        audio_codec = ""

    return video_codec, audio_codec


def probe_duration_seconds(filepath: Path) -> float:
    try:
        proc = subprocess.run(
            [
                "ffprobe", "-v", "error",
                "-show_entries", "format=duration",
                "-of", "csv=p=0",
                str(filepath),
            ],
            capture_output=True,
            text=True,
            timeout=10,
        )
        return float(proc.stdout.strip())
    except Exception:
        return 0.0


# ============================================================
# 오디오 변환 (mp3 / m4a) - 진행률 추적
#
# yt-dlp 내장 후처리기(FFmpegExtractAudio)는 진행률을 넘겨주지
# 않으므로, 다운로드는 원본 그대로 받고 mp3/m4a 인코딩은 직접
# ffmpeg를 호출해 run_ffmpeg_with_progress로 진행률을 추적한다.
# ============================================================

def encode_to_mp3(filepath: Path, bitrate: str, job_id: str) -> Path:
    duration = probe_duration_seconds(filepath)
    out_path = filepath.with_suffix(".mp3")

    cmd = [
        "ffmpeg", "-y", "-i", str(filepath),
        "-vn",
        "-c:a", "libmp3lame",
        "-b:a", f"{bitrate}k",
        str(out_path),
    ]

    encode_timeout = max(1800, int(duration * 3)) if duration else 1800

    run_ffmpeg_with_progress(
        cmd, duration, job_id,
        message_prefix="오디오 변환(MP3) 중",
        timeout_seconds=encode_timeout,
    )

    filepath.unlink(missing_ok=True)
    return out_path


def ensure_m4a(filepath: Path, job_id: str) -> Path:
    _, audio_codec = probe_codecs(filepath)
    out_path = filepath.with_suffix(".m4a")

    # 이미 m4a/aac면 재인코딩 없이 이름만 맞춰 반환 (가장 빠름)
    if filepath.suffix.lower() == ".m4a" and audio_codec == "aac":
        if filepath != out_path:
            filepath.rename(out_path)
        return out_path

    duration = probe_duration_seconds(filepath)
    cmd = ["ffmpeg", "-y", "-i", str(filepath), "-vn"]

    if audio_codec == "aac":
        # 컨테이너만 다른 경우: remux만 하면 되므로 매우 빠르다.
        cmd += ["-c:a", "copy"]
    else:
        cmd += ["-c:a", "aac", "-b:a", "256k"]

    cmd += [str(out_path)]

    encode_timeout = max(1800, int(duration * 3)) if duration else 1800

    run_ffmpeg_with_progress(
        cmd, duration, job_id,
        message_prefix="오디오 변환(M4A) 중",
        timeout_seconds=encode_timeout,
    )

    filepath.unlink(missing_ok=True)
    return out_path


# ============================================================
# iOS 호환성 보장 (mp4) - 진행률 추적
# ============================================================

# 저사양 서버(예: Render 무료 플랜)에서 재인코딩이 현실적인 시간 안에
# 끝나지 않을 수 있는 영상 길이. 이보다 길면 재인코딩을 시도하지 않고
# 원본을 그대로 반환하되, 호환성 경고를 job에 남긴다.
REENCODE_MAX_DURATION_SECONDS = 60 * 60


def ensure_ios_compatible_mp4(filepath: Path, job_id: str = None) -> Path:
    video_codec, audio_codec = probe_codecs(filepath)

    video_ok = video_codec in ("h264",)
    audio_ok = audio_codec in ("aac",)

    if video_ok and audio_ok:
        return filepath

    duration = probe_duration_seconds(filepath)

    if duration and duration > REENCODE_MAX_DURATION_SECONDS:
        # 긴 영상은 재인코딩만 건너뛰고(시간 절약), 별도 경고 메시지는
        # 띄우지 않는다.
        return filepath

    fixed_path = filepath.with_name(
        filepath.stem + "_ios" + filepath.suffix
    )

    cmd = ["ffmpeg", "-y", "-i", str(filepath)]

    if video_ok:
        cmd += ["-c:v", "copy"]
    else:
        # 긴 영상일수록 인코딩 부담이 크므로 속도 우선 프리셋 사용
        preset = "ultrafast" if duration > 900 else "veryfast"
        cmd += [
            "-c:v", "libx264",
            "-preset", preset,
            "-crf", "22",
            "-pix_fmt", "yuv420p",
        ]

    if audio_ok:
        cmd += ["-c:a", "copy"]
    else:
        cmd += ["-c:a", "aac", "-b:a", "192k"]

    cmd += ["-movflags", "+faststart", str(fixed_path)]

    # 영상 길이에 비례해 타임아웃을 넉넉히 준다 (최소 30분, 길이의 3배).
    encode_timeout = max(1800, int(duration * 3)) if duration else 1800

    try:
        run_ffmpeg_with_progress(
            cmd, duration, job_id,
            message_prefix="iOS 호환 변환 중",
            timeout_seconds=encode_timeout,
        )
    except JobCancelled:
        raise
    except (subprocess.CalledProcessError, subprocess.TimeoutExpired):
        # 재인코딩이 실패/타임아웃이면 최소한 원본이라도 전달한다.
        if job_id:
            with JOBS_LOCK:
                if job_id in JOBS:
                    JOBS[job_id]["compat_warning"] = (
                        "iOS 호환 변환에 실패해 원본 형식으로 제공됩니다. "
                        "일부 기기에서 재생이 안 될 수 있습니다."
                    )
        return filepath

    filepath.unlink(missing_ok=True)
    return fixed_path


# ============================================================
# 작업(Job) 관리
#
# 다운로드+변환을 백그라운드 스레드에서 실행하고, 프론트엔드는
# 짧은 폴링 요청으로 진행 상황만 확인한다. 이렇게 하면 연결이
# 오래 "조용한" 상태로 유지되지 않아 iOS Safari나 Render 프록시가
# 타임아웃으로 끊는 문제("Load failed")를 피할 수 있다.
# ============================================================

class JobLogger:
    """yt-dlp가 내는 경고/에러 중 마지막 것만 job에 기록한다.
    (전체 로그를 남기면 메모리/노이즈가 커지므로 마지막 것만 유지)"""

    def __init__(self, job_id: str):
        self.job_id = job_id

    def _record(self, msg: str):
        with JOBS_LOCK:
            if self.job_id in JOBS:
                JOBS[self.job_id]["last_log"] = str(msg)[:300]

    def debug(self, msg):
        pass

    def warning(self, msg):
        self._record(msg)

    def error(self, msg):
        self._record(msg)


def cleanup_stale_jobs():
    now = time.time()

    with JOBS_LOCK:
        stale_ids = [
            jid for jid, job in JOBS.items()
            if now - job.get("created_at", now) > JOB_MAX_AGE_SECONDS
        ]

        stale_jobs = [JOBS.pop(jid) for jid in stale_ids]

    for job in stale_jobs:
        tmpdir = job.get("tmpdir")
        if tmpdir:
            shutil.rmtree(tmpdir, ignore_errors=True)


def make_progress_hook(job_id: str):

    def hook(d):
        with JOBS_LOCK:
            job = JOBS.get(job_id)

        if job is None:
            return

        if job.get("cancel_requested"):
            raise JobCancelled()

        if d.get("status") == "downloading":
            total = (
                d.get("total_bytes")
                or d.get("total_bytes_estimate")
            )
            downloaded = d.get("downloaded_bytes", 0)

            if total:
                percent = min(downloaded / total * 100, 99)
            else:
                percent = job.get("progress", 0)

            speed = d.get("speed")
            speed_text = (
                f" ({speed / 1048576:.1f} MB/s)" if speed else ""
            )

            eta_seconds = d.get("eta")

            eta_text = ""
            if eta_seconds is not None and eta_seconds >= 0:
                m, s = divmod(int(eta_seconds), 60)
                h, m = divmod(m, 60)
                if h:
                    eta_text = f" · 남은 시간 약 {h}시간 {m}분"
                elif m:
                    eta_text = f" · 남은 시간 약 {m}분 {s}초"
                else:
                    eta_text = f" · 남은 시간 약 {s}초"

            with JOBS_LOCK:
                if job_id in JOBS:
                    JOBS[job_id]["status"] = "downloading"
                    JOBS[job_id]["progress"] = round(percent, 1)
                    JOBS[job_id]["eta_seconds"] = eta_seconds
                    JOBS[job_id]["message"] = (
                        f"다운로드 중... {round(percent)}%{speed_text}{eta_text}"
                    )

        elif d.get("status") == "finished":
            with JOBS_LOCK:
                if job_id in JOBS:
                    JOBS[job_id]["status"] = "processing"
                    JOBS[job_id]["progress"] = 0
                    JOBS[job_id]["message"] = "변환 준비 중..."

    return hook


def run_download_job(job_id: str, url: str, fmt: str, quality: str):

    tmpdir = tempfile.mkdtemp(prefix="ytdl_")

    with JOBS_LOCK:
        if job_id in JOBS:
            JOBS[job_id]["tmpdir"] = tmpdir
            JOBS[job_id]["status"] = "downloading"
            JOBS[job_id]["message"] = "다운로드 시작..."

    try:
        outtmpl = os.path.join(tmpdir, "%(title)s.%(ext)s")

        base = get_base_options()
        base["outtmpl"] = outtmpl
        base["progress_hooks"] = [make_progress_hook(job_id)]
        base["logger"] = JobLogger(job_id)

        bitrate = "192"

        if fmt == "mp3":
            bitrate_match = re.search(r"(\d+)", quality)
            bitrate = bitrate_match.group(1) if bitrate_match else "192"

            # 후처리 진행률을 직접 추적하기 위해 yt-dlp 기본 오디오
            # 추출 후처리기는 쓰지 않고 원본 오디오만 내려받는다.
            # 실제 mp3 인코딩은 아래에서 진행률을 추적하며 직접 실행한다.
            ydl_opts = {
                **base,
                "format": "bestaudio/best",
            }
            media_type = "audio/mpeg"

        elif fmt == "m4a":
            ydl_opts = {
                **base,
                "format": "bestaudio[ext=m4a]/bestaudio/best",
            }
            media_type = "audio/mp4"

        else:
            height_match = re.search(r"(\d+)", quality)
            height = height_match.group(1) if height_match else "1080"

            # 코덱을 미리 avc1로 강제하지 않는다. 1080p 이상은 h264
            # 단일/분리 스트림이 아예 없는 영상이 많아, 강제하면 오히려
            # 원치 않는 코덱(av1 등)으로 떨어져 다운로드 후 강제 재인코딩
            # (가장 느린 단계)을 유발하는 경우가 많았다.
            # 대신 yt-dlp가 고르는 진짜 "최선"을 그대로 받고, 다운로드 후
            # ensure_ios_compatible_mp4()가 실제로 필요한 경우에만 변환한다.
            format_spec = (
                f"best[height<={height}][ext=mp4]/"
                f"bestvideo[height<={height}]+bestaudio/"
                f"best[height<={height}]/"
                f"best"
            )

            ydl_opts = {
                **base,
                "format": format_spec,
                "merge_output_format": "mp4",
            }
            media_type = "video/mp4"

        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            ydl.extract_info(url, download=True)

        with JOBS_LOCK:
            if job_id in JOBS:
                JOBS[job_id]["status"] = "processing"
                JOBS[job_id]["message"] = "변환 준비 중..."
                JOBS[job_id]["progress"] = 0

        files = [f for f in Path(tmpdir).iterdir() if f.is_file()]

        if not files:
            raise RuntimeError("다운로드된 파일이 없습니다.")

        filepath = max(files, key=lambda f: f.stat().st_size)

        if fmt == "mp3":
            filepath = encode_to_mp3(filepath, bitrate, job_id)
        elif fmt == "m4a":
            filepath = ensure_m4a(filepath, job_id)
        else:
            filepath = ensure_ios_compatible_mp4(filepath, job_id=job_id)

        filename = safe_filename(filepath.name)

        with JOBS_LOCK:
            if job_id in JOBS:
                JOBS[job_id].update({
                    "status": "done",
                    "progress": 100,
                    "message": "완료",
                    "filepath": str(filepath),
                    "filename": filename,
                    "media_type": media_type,
                })

    except Exception as e:
        shutil.rmtree(tmpdir, ignore_errors=True)

        # yt-dlp/ffmpeg 실행부가 progress 루프에서 던진 JobCancelled를
        # 자체 에러 타입으로 감쌀 수 있으므로, 예외 타입만으로 판단하지
        # 않고 취소 플래그를 함께 확인한다.
        with JOBS_LOCK:
            job = JOBS.get(job_id)
            was_cancel_requested = bool(
                job and job.get("cancel_requested")
            )

        is_cancel = isinstance(e, JobCancelled) or was_cancel_requested

        with JOBS_LOCK:
            if job_id in JOBS:
                if is_cancel:
                    JOBS[job_id].update({
                        "status": "cancelled",
                        "message": "취소되었습니다.",
                    })
                else:
                    last_log = JOBS[job_id].get("last_log")
                    message = str(e)
                    if last_log and last_log not in message:
                        message = f"{message} ({last_log})"

                    JOBS[job_id].update({
                        "status": "error",
                        "message": message,
                    })


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
        "pot_provider": bgutil_ok,
        "active_jobs": len(JOBS),
    }


# ============================================================
# Video information (프론트에서 길이 확인용으로도 사용)
# ============================================================

@app.get("/api/info")
def info(
    url: str = Query(..., min_length=10)
):

    validate_url(url)

    options = get_base_options()
    options.update({"skip_download": True})

    try:
        with yt_dlp.YoutubeDL(options) as ydl:
            data = ydl.extract_info(url, download=False)

    except Exception as e:
        raise HTTPException(
            status_code=400,
            detail=f"영상 정보를 가져올 수 없습니다: {e}"
        )

    return {
        "title": data.get("title"),
        "duration": data.get("duration"),
        "uploader": data.get("uploader"),
        "thumbnail": data.get("thumbnail"),
        "id": data.get("id"),
    }


# ============================================================
# 작업 생성: 다운로드를 백그라운드에서 시작하고 job_id를 즉시 반환
# ============================================================

@app.post("/api/jobs")
def create_job(
    url: str = Query(..., min_length=10),
    format: str = Query("mp3", pattern="^(mp3|m4a|mp4)$"),
    quality: str = Query("192 kbps"),
):

    validate_url(url)
    cleanup_stale_jobs()

    with JOBS_LOCK:
        active = sum(
            1 for j in JOBS.values()
            if j.get("status") in ("queued", "downloading", "processing")
        )

        if active >= MAX_CONCURRENT_JOBS:
            raise HTTPException(
                status_code=429,
                detail=(
                    "다른 다운로드가 진행 중입니다. "
                    "잠시 후 다시 시도해주세요."
                )
            )

        job_id = uuid.uuid4().hex

        JOBS[job_id] = {
            "status": "queued",
            "progress": 0,
            "message": "대기 중...",
            "created_at": time.time(),
        }

    thread = threading.Thread(
        target=run_download_job,
        args=(job_id, url, format, quality),
        daemon=True,
    )
    thread.start()

    return {"job_id": job_id}


# ============================================================
# 작업 상태 조회 (프론트엔드가 짧은 주기로 폴링)
# ============================================================

@app.get("/api/jobs/{job_id}")
def job_status(job_id: str):

    with JOBS_LOCK:
        job = JOBS.get(job_id)

        if not job:
            raise HTTPException(
                status_code=404,
                detail="작업을 찾을 수 없습니다."
            )

        return {
            "status": job.get("status"),
            "progress": job.get("progress", 0),
            "message": job.get("message", ""),
            "filename": job.get("filename", ""),
            "compat_warning": job.get("compat_warning", ""),
            "eta_seconds": job.get("eta_seconds"),
        }


# ============================================================
# 작업 취소 요청
# ============================================================

@app.post("/api/jobs/{job_id}/cancel")
def cancel_job(job_id: str):

    with JOBS_LOCK:
        job = JOBS.get(job_id)

        if not job:
            raise HTTPException(
                status_code=404,
                detail="작업을 찾을 수 없습니다."
            )

        job["cancel_requested"] = True

    return {"ok": True}


# ============================================================
# 완료된 작업의 파일 다운로드
# (브라우저가 직접 GET으로 스트리밍 받음 — JS에서 Blob 조립 안 함)
# ============================================================

@app.get("/api/jobs/{job_id}/file")
def job_file(job_id: str):

    with JOBS_LOCK:
        job = JOBS.get(job_id)

        if not job:
            raise HTTPException(
                status_code=404,
                detail="작업을 찾을 수 없습니다."
            )

        if job.get("status") != "done":
            raise HTTPException(
                status_code=409,
                detail="파일이 아직 준비되지 않았습니다."
            )

        filepath = job["filepath"]
        tmpdir = job["tmpdir"]
        filename = job["filename"]
        media_type = job["media_type"]

    def cleanup():
        shutil.rmtree(tmpdir, ignore_errors=True)
        with JOBS_LOCK:
            JOBS.pop(job_id, None)

    return FileResponse(
        path=filepath,
        media_type=media_type,
        filename=filename,
        background=BackgroundTask(cleanup),
    )


# ============================================================
# 진단
# ============================================================

@app.get("/api/diag")
def diag():

    result = {}

    try:
        result["yt_dlp_pkg"] = pkg_version("yt-dlp")
    except Exception as e:
        result["yt_dlp_pkg"] = f"error: {e}"

    result["cookies_configured"] = bool(
        os.environ.get("YOUTUBE_COOKIES", "").strip()
    )

    port = int(os.environ.get("BGUTIL_PORT", "4416"))

    try:
        s = socket.create_connection(("127.0.0.1", port), timeout=3)
        s.close()
        result["bgutil_tcp"] = True
    except Exception as e:
        result["bgutil_tcp"] = f"error: {e}"

    try:
        with urllib.request.urlopen(
            f"http://127.0.0.1:{port}/ping", timeout=5
        ) as r:
            result["bgutil_ping"] = r.read().decode(errors="ignore")[:200]
    except Exception as e:
        result["bgutil_ping"] = f"error: {e}"

    for tool in ("ffmpeg", "ffprobe"):
        try:
            proc = subprocess.run(
                [tool, "-version"],
                capture_output=True,
                text=True,
                timeout=10,
            )
            result[f"{tool}_available"] = proc.returncode == 0
        except Exception as e:
            result[f"{tool}_available"] = f"error: {e}"

    with JOBS_LOCK:
        result["active_jobs"] = len(JOBS)
        result["jobs_snapshot"] = {
            jid: {"status": j.get("status"), "progress": j.get("progress")}
            for jid, j in list(JOBS.items())[:20]
        }

    test_url = "https://youtu.be/ACnbMg6o8z0"

    try:
        proc = subprocess.run(
            [
                "yt-dlp", "-v", "--skip-download", "--no-warnings",
                "--socket-timeout", "30", "-O", "title", test_url,
            ],
            capture_output=True,
            text=True,
            timeout=180,
            env=os.environ.copy(),
        )

        output = (proc.stderr or "") + "\n" + (proc.stdout or "")
        lines = output.splitlines()

        result["ytdlp_exit_code"] = proc.returncode

        result["pot_provider_lines"] = [
            line.strip() for line in lines
            if (
                "bgutil" in line.lower()
                or "[pot]" in line.lower()
                or "po token" in line.lower()
                or "po_token" in line.lower()
            )
        ][:30]

        result["errors"] = [
            line.strip() for line in lines
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
def test_clients(url: str = Query(..., min_length=10)):

    validate_url(url)

    clients = ["mweb", "web_safari", "web_embedded", "android_vr", "tv"]
    results = []

    for client in clients:
        result = {"client": client, "success": False, "title": None, "error": None}

        try:
            options = get_base_options()
            options.update({
                "quiet": True,
                "no_warnings": True,
                "skip_download": True,
                "socket_timeout": 30,
                "extractor_args": {
                    "youtube": {"player_client": [client]},
                    "youtubepot-bgutilhttp": {
                        "base_url": f"http://127.0.0.1:{BGUTIL_PORT}"
                    },
                },
            })

            with yt_dlp.YoutubeDL(options) as ydl:
                info = ydl.extract_info(url, download=False)

                result["success"] = True
                result["title"] = info.get("title")
                result["video_id"] = info.get("id")
                result["duration"] = info.get("duration")
                result["format_count"] = len(info.get("formats") or [])

        except Exception as e:
            result["error"] = str(e)[:1500]

        results.append(result)

    return {
        "ok": True,
        "url": url,
        "cookies": bool(os.environ.get("YOUTUBE_COOKIES", "").strip()),
        "results": results,
    }
