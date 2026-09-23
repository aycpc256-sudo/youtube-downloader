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
    let activeObjectUrl = null;

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

    function extractFilename(disposition, fallback) {
        const utf8Match = disposition.match(/filename\*=UTF-8''([^;]+)/i);
        if (utf8Match) {
            return decodeURIComponent(utf8Match[1]);
        }

        const plainMatch = disposition.match(/filename="?([^";]+)"?/i);
        if (plainMatch) {
            return plainMatch[1];
        }

        return fallback;
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

        const params = new URLSearchParams({
            url: u,
            format: f,
            quality: q
        });

        const downloadUrl = `${API_BASE}/api/download?${params.toString()}`;

        // ----------------------------------------------------
        // mp4는 파일이 커질 수 있어(수백MB~수GB) fetch로 받아
        // 메모리(Blob)에 조립하지 않는다. 대용량 Blob 조립은
        // 특히 iOS Safari에서 메모리 부족으로 파일이 잘리거나
        // 손상되는 원인이 된다. 대신 브라우저/OS의 네이티브
        // 스트리밍 다운로드(링크 직접 열기)를 한 번만 요청한다.
        // 진행률 표시는 못 하지만 훨씬 안전하다.
        //
        // mp3는 항상 충분히 작으므로 기존처럼 fetch+Blob로
        // 받아 진행률을 보여준다.
        // ----------------------------------------------------

        if (f === "mp4") {
            setStatus(
                "서버에서 변환 중입니다. 화질에 따라 시간이 걸릴 수 있으며, " +
                "완료되면 브라우저 다운로드가 자동으로 시작됩니다.",
                10
            );

            const link = document.createElement("a");
            link.href = downloadUrl;
            // 크로스 오리진이라 link.download는 브라우저가 무시할 수 있으며,
            // 실제 파일명은 서버의 Content-Disposition 헤더로 결정된다.
            document.body.appendChild(link);
            link.click();
            link.remove();

            // 이 방식은 fetch가 아니라 네비게이션이므로 완료 시점을
            // JS에서 알 수 없다. 사용자에게 안내만 하고 종료한다.
            setStatus(
                "다운로드가 시작되었습니다. iOS는 공유 시트 또는 " +
                "다운로드 목록에서, PC/안드로이드는 다운로드 폴더에서 확인하세요.",
                100
            );

            controller = null;
            setBusy(false);
            return;
        }

        setStatus("서버에서 다운로드 준비 중...", 5);

        try {
            const response = await fetch(downloadUrl, {
                signal: controller.signal
            });

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

            const filename = extractFilename(
                disposition,
                "youtube-audio.mp3"
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
                    setStatus(`다운로드 중... ${mb.toFixed(1)} MB`, 70);
                }
            }

            const blob = new Blob(chunks, { type: "audio/mpeg" });
            const objectUrl = URL.createObjectURL(blob);
            activeObjectUrl = objectUrl;

            const link = document.createElement("a");
            link.href = objectUrl;
            link.download = filename;

            document.body.appendChild(link);
            link.click();
            link.remove();

            setTimeout(() => {
                if (activeObjectUrl === objectUrl) {
                    URL.revokeObjectURL(objectUrl);
                    activeObjectUrl = null;
                }
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
