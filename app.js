const API_BASE =
  "https://youtube-downloader-onww.onrender.com";

let currentFormat = "mp3";
let currentAbort = null;
let currentPlayerClient = null;
let currentVideoInfo = null;

const urlInput =
  document.getElementById("url");

const qualitySelect =
  document.getElementById("quality");

const qualityHint =
  document.getElementById("quality-hint");

const downloadBtn =
  document.getElementById("download-btn");

const cancelBtn =
  document.getElementById("cancel-btn");

const statusEl =
  document.getElementById("status");

const progressBar =
  document.getElementById("progress-bar");

const diagnoseButton =
  document.getElementById("diagnose-btn");

const diagnoseResult =
  document.getElementById("diagnose-result");

const videoInfoEl =
  document.getElementById("video-info");

const deviceLabel =
  document.getElementById("device-label");


// =========================================================
// 공통 상태
// =========================================================

function setStatus(message, kind = "info") {

  statusEl.textContent = message;

  const colors = {
    info: "#4a9eff",
    ok: "#4caf50",
    warn: "#ff9800",
    err: "#e53935",
  };

  statusEl.style.color =
    colors[kind] || "#888";
}


// =========================================================
// 기기
// =========================================================

function initDeviceUI() {

  const ua =
    navigator.userAgent.toLowerCase();

  let device = "PC";

  if (
    ua.includes("iphone") ||
    ua.includes("ipad")
  ) {
    device = "iPhone / iPad";
  } else if (
    ua.includes("android")
  ) {
    device = "Android";
  }

  deviceLabel.textContent =
    `${device} · 웹 다운로드`;
}


// =========================================================
// 품질
// =========================================================

function setQualityOptions(
  heights
) {

  qualitySelect.innerHTML = "";

  if (
    !Array.isArray(heights) ||
    heights.length === 0
  ) {

    const option =
      document.createElement("option");

    option.value = "";
    option.textContent =
      "사용 가능한 MP4 화질 없음";

    qualitySelect.appendChild(option);

    return;
  }

  const sorted = [
    ...new Set(
      heights
        .map(Number)
        .filter(
          Number.isFinite
        )
    ),
  ].sort(
    (a, b) => b - a
  );

  sorted.forEach(
    (height, index) => {

      const option =
        document.createElement(
          "option"
        );

      option.value =
        `${height}p`;

      option.textContent =
        index === 0
          ? `${height}p (기본)`
          : `${height}p`;

      if (index === 0) {
        option.selected = true;
      }

      qualitySelect.appendChild(
        option
      );
    }
  );
}


function renderAudioQuality() {

  qualitySelect.innerHTML = "";

  const qualities = [
    "128 kbps",
    "192 kbps",
    "256 kbps",
    "320 kbps",
  ];

  qualities.forEach(
    (quality) => {

      const option =
        document.createElement(
          "option"
        );

      option.value = quality;
      option.textContent = quality;

      if (
        quality === "192 kbps"
      ) {
        option.selected = true;
      }

      qualitySelect.appendChild(
        option
      );
    }
  );
}


// =========================================================
// 형식 선택
// =========================================================

document
  .querySelectorAll(
    "[data-format]"
  )
  .forEach((button) => {

    button.addEventListener(
      "click",
      () => {

        document
          .querySelectorAll(
            "[data-format]"
          )
          .forEach(
            (b) =>
              b.classList.remove(
                "active"
              )
          );

        button.classList.add(
          "active"
        );

        currentFormat =
          button.dataset.format;

        currentPlayerClient = null;

        if (
          currentFormat === "mp4"
        ) {

          qualityHint.textContent =
            "YouTube에서 실제 제공되는 MP4 화질";

          if (
            currentVideoInfo &&
            Array.isArray(
              currentVideoInfo.mp4_qualities
            )
          ) {

            setQualityOptions(
              currentVideoInfo
                .mp4_qualities
            );

          } else {

            qualitySelect.innerHTML =
              `<option value="">먼저 영상 정보를 확인하세요</option>`;
          }

        } else {

          qualityHint.textContent =
            currentFormat === "m4a"
              ? "M4A 음질"
              : "MP3 음질";

          renderAudioQuality();
        }
      }
    );
  });


// =========================================================
// 영상 정보
// =========================================================

async function fetchVideoInfo() {

  const url =
    urlInput.value.trim();

  if (!url) {
    throw new Error(
      "YouTube URL을 입력하세요."
    );
  }

  setStatus(
    "YouTube 영상 정보를 확인하는 중...",
    "info"
  );

  const controller =
    new AbortController();

  const timeout =
    setTimeout(
      () => controller.abort(),
      60000
    );

  try {

    const response =
      await fetch(
        `${API_BASE}/api/info?url=` +
        encodeURIComponent(url),
        {
          signal:
            controller.signal,
        }
      );

    const text =
      await response.text();

    let data = null;

    try {
      data = JSON.parse(text);
    } catch (_) {
      data = null;
    }

    if (!response.ok) {

      const detail =
        data?.detail;

      if (
        typeof detail === "object"
      ) {

        throw new Error(
          `[${detail.code || "ERROR"}] ` +
          `${detail.message || "영상 정보를 가져오지 못했습니다."}`
        );

      }

      throw new Error(
        text ||
        `서버 오류 (${response.status})`
      );
    }

    currentVideoInfo = data;

    currentPlayerClient =
      data.player_client ||
      null;

    if (videoInfoEl) {

      videoInfoEl.textContent =
        [
          data.title || "",
          currentPlayerClient
            ? `client: ${currentPlayerClient}`
            : "",
        ]
          .filter(Boolean)
          .join(" · ");
    }

    if (
      currentFormat === "mp4"
    ) {

      setQualityOptions(
        data.mp4_qualities || []
      );

    }

    setStatus(
      currentPlayerClient
        ? `영상 확인 완료 · ${currentPlayerClient}`
        : "영상 확인 완료",
      "ok"
    );

    return data;

  } catch (error) {

    if (
      error.name ===
      "AbortError"
    ) {
      throw new Error(
        "영상 정보 확인 시간이 초과되었습니다."
      );
    }

    throw error;

  } finally {

    clearTimeout(timeout);
  }
}


// =========================================================
// 다운로드
// =========================================================

downloadBtn.addEventListener(
  "click",
  startDownload
);


async function startDownload() {

  const url =
    urlInput.value.trim();

  if (!url) {

    setStatus(
      "YouTube URL을 입력하세요.",
      "warn"
    );

    urlInput.focus();

    return;
  }

  downloadBtn.disabled = true;
  cancelBtn.disabled = false;

  progressBar.style.width =
    "0%";

  try {

    // ---------------------------------------------
    // 1. 영상 정보 확인
    // ---------------------------------------------

    const info =
      await fetchVideoInfo();

    const quality =
      qualitySelect.value;

    if (
      currentFormat === "mp4" &&
      !quality
    ) {

      throw new Error(
        "사용 가능한 MP4 화질이 없습니다."
      );
    }

    // ---------------------------------------------
    // 2. 다운로드
    // ---------------------------------------------

    const params =
      new URLSearchParams({
        url,
        format:
          currentFormat,
        quality,
      });

    if (currentPlayerClient) {

      params.set(
        "player_client",
        currentPlayerClient
      );
    }

    setStatus(
      `다운로드 준비 중... ` +
      `(${currentPlayerClient || "fallback"})`,
      "info"
    );

    currentAbort =
      new AbortController();

    const response =
      await fetch(
        `${API_BASE}/api/download?${params}`,
        {
          signal:
            currentAbort.signal,
        }
      );

    if (!response.ok) {

      const text =
        await response.text();

      let message = text;

      try {

        const data =
          JSON.parse(text);

        if (
          typeof data.detail ===
          "object"
        ) {

          message =
            `[${data.detail.code || "ERROR"}] ` +
            `${data.detail.message || ""}`;
        } else if (
          data.detail
        ) {

          message =
            String(
              data.detail
            );
        }

      } catch (_) {}

      throw new Error(
        message ||
        `서버 오류 (${response.status})`
      );
    }

    // ---------------------------------------------
    // 3. 파일명
    // ---------------------------------------------

    let filename =
      currentFormat === "mp3"
        ? "audio.mp3"
        : currentFormat === "m4a"
        ? "audio.m4a"
        : "video.mp4";

    const disposition =
      response.headers.get(
        "content-disposition"
      ) || "";

    const match =
      disposition.match(
        /filename\*=UTF-8''([^;]+)/i
      );

    if (match) {

      try {

        filename =
          decodeURIComponent(
            match[1]
          );

      } catch (_) {}
    }

    // ---------------------------------------------
    // 4. 파일 수신
    // ---------------------------------------------

    const total = parseInt(
      response.headers.get(
        "content-length"
      ) || "0",
      10
    );

    const reader =
      response.body.getReader();

    const chunks = [];

    let received = 0;

    while (true) {

      const {
        done,
        value,
      } = await reader.read();

      if (done) {
        break;
      }

      chunks.push(value);

      received +=
        value.length;

      if (total) {

        const percent =
          Math.min(
            100,
            received /
              total *
              100
          );

        progressBar.style.width =
          percent.toFixed(1) +
          "%";

        setStatus(
          `다운로드 중... ${percent.toFixed(1)}%`,
          "info"
        );

      } else {

        setStatus(
          `다운로드 중... ` +
          `${(
            received /
            1024 /
            1024
          ).toFixed(1)} MB`,
          "info"
        );
      }
    }

    // ---------------------------------------------
    // 5. 저장
    // ---------------------------------------------

    const mime =
      currentFormat === "mp3"
        ? "audio/mpeg"
        : currentFormat === "m4a"
        ? "audio/mp4"
        : "video/mp4";

    const blob =
      new Blob(
        chunks,
        { type: mime }
      );

    const objectUrl =
      URL.createObjectURL(
        blob
      );

    const link =
      document.createElement(
        "a"
      );

    link.href =
      objectUrl;

    link.download =
      filename;

    document.body.appendChild(
      link
    );

    link.click();

    link.remove();

    setTimeout(
      () =>
        URL.revokeObjectURL(
          objectUrl
        ),
      30000
    );

    progressBar.style.width =
      "100%";

    setStatus(
      "다운로드 완료",
      "ok"
    );

  } catch (error) {

    if (
      error.name ===
      "AbortError"
    ) {

      setStatus(
        "다운로드가 취소되었습니다.",
        "warn"
      );

    } else {

      console.error(error);

      setStatus(
        "다운로드 실패: " +
        error.message,
        "err"
      );

      // -------------------------------------------
      // 자동 진단
      // -------------------------------------------

      await runDiagnosis(
        false
      );
    }

  } finally {

    downloadBtn.disabled =
      false;

    cancelBtn.disabled =
      true;

    currentAbort = null;
  }
}


// =========================================================
// 취소
// =========================================================

cancelBtn.addEventListener(
  "click",
  () => {

    if (currentAbort) {

      currentAbort.abort();

      setStatus(
        "취소 중...",
        "warn"
      );
    }
  }
);


// =========================================================
// 진단
// =========================================================

diagnoseButton.addEventListener(
  "click",
  () =>
    runDiagnosis(true)
);


async function runDiagnosis(
  manual = true
) {

  const url =
    urlInput.value.trim();

  if (!url) {

    if (manual) {

      setStatus(
        "진단할 YouTube URL을 입력하세요.",
        "warn"
      );
    }

    return;
  }

  diagnoseButton.disabled =
    true;

  diagnoseResult.textContent =
    "진단 중...\n";

  try {

    const controller =
      new AbortController();

    const timeout =
      setTimeout(
        () => controller.abort(),
        120000
      );

    const response =
      await fetch(
        `${API_BASE}/api/diagnose?url=` +
        encodeURIComponent(url),
        {
          signal:
            controller.signal,
        }
      );

    clearTimeout(timeout);

    const text =
      await response.text();

    let data;

    try {

      data =
        JSON.parse(text);

    } catch (_) {

      data = {
        raw: text,
      };
    }

    diagnoseResult.textContent =
      JSON.stringify(
        data,
        null,
        2
      );

    if (data?.clients) {

      const success =
        data.clients.find(
          (item) =>
            item.ok
        );

      if (success) {

        currentPlayerClient =
          success.client;

        setStatus(
          `진단 성공 client: ${success.client}`,
          "ok"
        );

      } else if (manual) {

        setStatus(
          "모든 YouTube client 진단 실패",
          "err"
        );
      }
    }

  } catch (error) {

    diagnoseResult.textContent =
      "진단 오류: " +
      error.message;

    if (manual) {

      setStatus(
        "진단 요청 실패",
        "err"
      );
    }

  } finally {

    diagnoseButton.disabled =
      false;
  }
}


// =========================================================
// URL 변경 시 client 초기화
// =========================================================

urlInput.addEventListener(
  "input",
  () => {

    currentPlayerClient = null;
    currentVideoInfo = null;

    if (videoInfoEl) {
      videoInfoEl.textContent = "";
    }
  }
);


// =========================================================
// 초기화
// =========================================================

initDeviceUI();

renderAudioQuality();

urlInput.focus();


// =========================================================
// Service Worker
// =========================================================

if (
  "serviceWorker" in navigator
) {

  navigator.serviceWorker
    .register(
      "service-worker.js"
    )
    .catch(
      () => {}
    );
}
