const API_BASE = "https://youtube-downloader-onww.onrender.com";

document.addEventListener("DOMContentLoaded", () => {
    const url = document.getElementById("url");
    const quality = document.getElementById("quality");
    const downloadBtn = document.getElementById("downloadBtn");
    const cancelBtn = document.getElementById("cancelBtn");
    const status = document.getElementById("status");
    const bar = document.getElementById("bar");
    const formatInputs = document.querySelectorAll('input[name="format"]');

    let controller = null;

    const qualities = {
        mp3: [
            ["320", "320 kbps"],
            ["256", "256 kbps"],
            ["192", "192 kbps"],
            ["128", "128 kbps"],
            ["96", "96 kbps"]
        ],
        mp4: [
            ["best", "최고 화질"],
            ["2160", "2160p (4K)"],
            ["1440", "1440p"],
            ["1080", "1080p"],
            ["720", "720p"],
            ["480", "480p"],
            ["360", "360p"]
        ]
    };

    const getFormat = () => {
        const checked = document.querySelector(
            'input[name="format"]:checked'
        );
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
            bar.style.width =
                Math.max(0, Math.min(100, progress)) + "%";
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

        controller = new AbortController();

        setBusy(true);
        setStatus("서버에서 다운로드 준비 중...", 5);

        try {
            const params = new URLSearchParams({
                url: u,
                format: f,
                quality: q
            });

            const response = await fetch(
                `${API_BASE}/api/download?${params.toString()}`,
                {
                    signal: controller.signal
                }
            );

            if (!response.ok) {
                let message = `서버 오류 (${response.status})`;

                try {
                    const data = await response.json();

                    if (data.detail) {
                        message = data.detail;
                    }
                } catch (_) {}

                throw new Error(message);
            }

            const total = Number(
                response.headers.get("Content-Length") || 0
            );

            const disposition =
                response.headers.get("Content-Disposition") || "";

            const filenameMatch =
                disposition.match(/filename\*=UTF-8''([^;]+)/i);

            const filename = filenameMatch
                ? decodeURIComponent(filenameMatch[1])
                : (
                    f === "mp3"
                        ? "youtube-audio.mp3"
                        : "youtube-video.mp4"
                );

            if (!response.body) {
                throw new Error("다운로드 데이터를 받을 수 없습니다.");
            }

            const reader = response.body.getReader();
            const chunks = [];

            let received = 0;

            while (true) {
                const result = await reader.read();

                if (result.done) {
                    break;
                }

                chunks.push(result.value);
                received += result.value.byteLength;

                if (total > 0) {
                    const percent = received / total * 100;

                    setStatus(
                        `다운로드 중... ${Math.round(percent)}%`,
                        percent
                    );
                } else {
                    const mb = received / 1048576;

                    setStatus(
                        `다운로드 중... ${mb.toFixed(1)} MB`,
                        70
                    );
                }
            }

            const blob = new Blob(chunks, {
                type: f === "mp3"
                    ? "audio/mpeg"
                    : "video/mp4"
            });

            const objectUrl = URL.createObjectURL(blob);

            const link = document.createElement("a");

            link.href = objectUrl;
            link.download = filename;

            document.body.appendChild(link);
            link.click();
            link.remove();

            setTimeout(() => {
                URL.revokeObjectURL(objectUrl);
            }, 1500);

            setStatus("저장 완료", 100);

        } catch (error) {
            if (error.name === "AbortError") {
                setStatus("취소되었습니다.", 0);
            } else {
                setStatus(`실패: ${error.message}`, 0);
            }

        } finally {
            controller = null;
            setBusy(false);
        }
    });

    cancelBtn.addEventListener("click", () => {
        if (controller) {
            controller.abort();
        }
    });
});
