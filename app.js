const API_BASE = "https://youtube-downloader-onww.onrender.com";

document.addEventListener("DOMContentLoaded", () => {
    const url = document.getElementById("url");
    const quality = document.getElementById("quality");
    const downloadBtn = document.getElementById("downloadBtn");
    const cancelBtn = document.getElementById("cancelBtn");
    const status = document.getElementById("status");
    const bar = document.getElementById("bar");
    const formatInputs = document.querySelectorAll('input[name="format"]');

    const POLL_INTERVAL_MS = 2000;

    // 영상이 이 시간(초)보다 길면 처리 시간이 오래 걸릴 수 있다고
    // 미리 경고한다 (30분).
    const LONG_VIDEO_WARN_SECONDS = 30 * 60;

    let currentJobId = null;
    let pollTimer = null;
    let cancelled = false;

    const qualities = {
        mp3: [
            ["320", "320 kbps"],
            ["256", "256 kbps"],
            ["192", "192 kbps"],
            ["128", "128 kbps"],
            ["96", "96 kbps"]
        ],
        // m4a는 유튜브 원본 오디오를 그대로 remux하므로 비트레이트를
        // 고를 필요가 없다 (재인코딩 없음 = 훨씬 빠름, 화질 손실 없음).
        m4a: [
            ["original", "원본 음질 (재인코딩 없음, 가장 빠름)"]
        ],
        // 4K(2160p)는 서버 처리 시간이 급격히 늘어나 타임아웃 위험이
        // 커서 제거했습니다. 필요하시면 1440p까지 사용하세요.
        mp4: [
            ["1440", "1440p"],
            ["1080", "1080p"],
            ["720", "720p"],
            ["480", "480p"],
            ["360", "360p"]
        ]
    };

    const getFormat = () => {
        const checked = document.querySelector('input[name="format"]:checked');
        return checked ? checked.value : "mp3";
    };

    function refreshQuality() {
        const f = getFormat();
        quality.innerHTML = "";

        for (const [value, text] of qualities[f]) {
            const option = document.createElement("option");
            option.value = value;
            option.textContent = text;
            quality.appendChild(option);
        }
    }

    function setStatus(text, progress = null) {
        status.textContent = text;

        if (progress !== null) {
            bar.style.width = Math.max(0, Math.min(100, progress)) + "%";
        }
    }

    function setBusy(value) {
        downloadBtn.disabled = value;
        cancelBtn.disabled = !value;
        quality.disabled = value;
        url.disabled = value;

        formatInputs.forEach(input => {
            input.disabled = value;
        });
    }

    function stopPolling() {
        if (pollTimer) {
            clearTimeout(pollTimer);
            pollTimer = null;
        }
    }

    function formatDuration(seconds) {
        const m = Math.floor(seconds / 60);
        const s = Math.floor(seconds % 60);
        return `${m}분 ${s}초`;
    }

    formatInputs.forEach(input => {
        input.addEventListener("change", refreshQuality);
    });

    refreshQuality();

    downloadBtn.addEventListener("click", async () => {
        const u = url.value.trim();
        const f = getFormat();
        const q = quality.value;

        if (!u) {
            setStatus("YouTube 주소를 입력하세요.");
            return;
        }

        if (!/^https?:\/\/(www\.)?(youtube\.com|youtu\.be)\//i.test(u)) {
            setStatus("YouTube 주소만 입력할 수 있습니다.");
            return;
        }

        cancelled = false;
        setBusy(true);
        setStatus("영상 정보를 확인하는 중...", 2);

        // --------------------------------------------------------
        // 1) 길이가 아주 긴 영상이면 미리 경고 (처리 시간 예측 목적)
        //    이 요청이 실패해도 다운로드 자체는 계속 진행한다.
        // --------------------------------------------------------
        try {
            const infoRes = await fetch(
                `${API_BASE}/api/info?${new URLSearchParams({ url: u })}`
            );

            if (infoRes.ok) {
                const infoData = await infoRes.json();
                const duration = infoData.duration;

                if (duration && duration > LONG_VIDEO_WARN_SECONDS) {
                    const proceed = confirm(
                        `영상 길이가 ${formatDuration(duration)}입니다.\n` +
                        `길이가 길수록 서버 처리 시간이 오래 걸리며 실패 확률도 ` +
                        `높아집니다. 계속하시겠습니까?`
                    );

                    if (!proceed) {
                        setStatus("취소되었습니다.", 0);
                        setBusy(false);
                        return;
                    }
                }
            }
        } catch (_) {
            // info 조회 실패는 무시하고 계속 진행
        }

        setStatus("서버에 작업을 등록하는 중...", 5);

        try {
            // ----------------------------------------------------
            // 2) 작업 생성 (이 요청은 즉시 반환되고, 실제 다운로드는
            //    서버 백그라운드에서 진행된다)
            // ----------------------------------------------------

            const createRes = await fetch(
                `${API_BASE}/api/jobs?${new URLSearchParams({
                    url: u,
                    format: f,
                    quality: q
                })}`,
                { method: "POST" }
            );

            if (!createRes.ok) {
                let message = `작업 등록 실패 (${createRes.status})`;
                try {
                    const data = await createRes.json();
                    if (data.detail) message = data.detail;
                } catch (_) {}
                throw new Error(message);
            }

            const { job_id } = await createRes.json();
            currentJobId = job_id;

            // ----------------------------------------------------
            // 3) 짧은 주기로 상태만 확인 (긴 연결을 유지하지 않으므로
            //    iOS Safari / Render 프록시의 idle 타임아웃에 걸리지 않음)
            // ----------------------------------------------------

            await pollJob(job_id, f);

        } catch (error) {
            setStatus(`실패: ${error.message}`, 0);
            setBusy(false);
            currentJobId = null;
        }
    });

    function pollJob(jobId, format) {
        return new Promise((resolve, reject) => {

            const tick = async () => {
                if (cancelled) {
                    resolve();
                    return;
                }

                try {
                    const res = await fetch(`${API_BASE}/api/jobs/${jobId}`);

                    if (res.status === 404) {
                        throw new Error("작업을 찾을 수 없습니다. 다시 시도해주세요.");
                    }

                    if (!res.ok) {
                        throw new Error(`상태 확인 실패 (${res.status})`);
                    }

                    const data = await res.json();

                    if (data.status === "error") {
                        throw new Error(data.message || "다운로드 중 오류가 발생했습니다.");
                    }

                    if (data.status === "cancelled") {
                        setStatus("취소되었습니다.", 0);
                        setBusy(false);
                        resolve();
                        return;
                    }

                    if (data.status === "done") {
                        setStatus("완료! 다운로드를 시작합니다...", 100);
                        triggerFileDownload(jobId, data.filename);
                        setBusy(false);

                        // 상태 텍스트만으로는 놓치기 쉬우므로 명확히 alert로 알림
                        if (data.compat_warning) {
                            alert(`⚠️ ${data.compat_warning}`);
                        }

                        resolve();
                        return;
                    }

                    // queued / downloading / processing
                    setStatus(
                        data.message || "처리 중...",
                        data.progress ?? null
                    );

                    pollTimer = setTimeout(tick, POLL_INTERVAL_MS);

                } catch (error) {
                    setStatus(`실패: ${error.message}`, 0);
                    setBusy(false);
                    reject(error);
                }
            };

            tick();
        });
    }

    function triggerFileDownload(jobId, filename) {
        // 브라우저가 직접 GET으로 스트리밍 다운로드하도록 링크를 연다.
        // JS에서 Blob으로 조립하지 않으므로 iOS Safari의 메모리 문제로
        // 대용량 mp4가 손상되는 일이 없다.
        //
        // 참고: link.download는 크로스 오리진 링크에서는 브라우저가
        // 무시할 수 있고, 특히 iOS Safari는 미디어 파일을 다운로드하지
        // 않고 새 탭에서 재생만 하는 경우가 많다. 이 경우 사용자가
        // 공유 버튼 → "파일에 저장"을 눌러야 하며, 이는 iOS 자체 정책이라
        // 코드로 우회할 수 없다. 그래도 PC/Android에서는 파일명이
        // 정확히 지정되도록 download 속성은 남겨둔다.
        const fileUrl = `${API_BASE}/api/jobs/${jobId}/file`;

        const link = document.createElement("a");
        link.href = fileUrl;
        if (filename) {
            link.download = filename;
        }
        document.body.appendChild(link);
        link.click();
        link.remove();
    }

    cancelBtn.addEventListener("click", async () => {
        cancelled = true;
        stopPolling();

        if (currentJobId) {
            try {
                await fetch(`${API_BASE}/api/jobs/${currentJobId}/cancel`, {
                    method: "POST"
                });
            } catch (_) {}
        }

        setStatus("취소되었습니다.", 0);
        setBusy(false);
        currentJobId = null;
    });
});
