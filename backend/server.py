import socket
import subprocess
import urllib.request
from importlib.metadata import version as pkg_version


@app.get("/api/diag")
def diag():
    result = {}

    # 1) 실제 yt-dlp 패키지 버전
    try:
        result["yt_dlp_pkg"] = pkg_version("yt-dlp")
    except Exception as e:
        result["yt_dlp_pkg"] = f"error: {e}"

    # 2) bgutil 서버 TCP 연결
    port = int(os.environ.get("BGUTIL_PORT", "4416"))
    try:
        s = socket.create_connection(("127.0.0.1", port), timeout=3)
        s.close()
        result["bgutil_tcp"] = True
    except Exception as e:
        result["bgutil_tcp"] = f"error: {e}"

    # 3) bgutil /ping 응답
    try:
        with urllib.request.urlopen(
            f"http://127.0.0.1:{port}/ping", timeout=5
        ) as r:
            result["bgutil_ping"] = r.read().decode(errors="ignore")[:100]
    except Exception as e:
        result["bgutil_ping"] = f"error: {e}"

    # 4) yt-dlp verbose 실행 → Provider 감지 + PO Token 생성 여부 확인
    #    (yt-dlp 공식 테스트 영상, 다운로드 없이 메타데이터만)
    try:
        proc = subprocess.run(
            [
                "yt-dlp", "-v", "--skip-download", "--no-warnings",
                "--socket-timeout", "20",
                "-O", "title",
                "https://www.youtube.com/watch?v=BaW_jenozKc",
            ],
            capture_output=True, text=True, timeout=180,
        )
        output = (proc.stderr or "") + "\n" + (proc.stdout or "")
        lines = output.splitlines()

        result["ytdlp_exit_code"] = proc.returncode
        result["pot_provider_lines"] = [
            l.strip() for l in lines
            if "bgutil" in l.lower() or "[pot]" in l.lower()
        ][:20]
        result["errors"] = [
            l.strip() for l in lines
            if "sign in" in l.lower() or "error" in l.lower()
        ][:5]
    except Exception as e:
        result["ytdlp_run_error"] = str(e)

    return result
