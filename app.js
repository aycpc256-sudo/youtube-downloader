"use strict";

const API_BASE = "https://youtube-downloader-onww.onrender.com";

// ============================================================
// DOM
// ============================================================

const $ = (selector) => document.querySelector(selector);

const urlInput = $("#url");
const qualitySelect = $("#quality");
const qualityHint = $("#quality-hint");
const downloadButton = $("#download-btn");
const cancelButton = $("#cancel-btn");
const diagnoseButton = $("#diagnose-btn");
const diagnoseResult = $("#diagnose-result");
const progressBar = $("#progress-bar");
const statusElement = $("#status");
const deviceLabel = $("#device-label");
const videoInfo = $("#video-info");
const videoTitle = $("#video-title");
const videoMeta = $("#video-meta");

// ============================================================
// State
// ============================================================

let currentFormat = "mp3";
let currentAbortController = null;
let currentVideoInfo = null;

// ============================================================
// Device
// ============================================================

function detectDevice() {
  const ua = navigator.userAgent;
  if (/iPhone|iPad|iPod/i.test(ua)) return "iOS";
  if (/Android/i.test(ua)) return "Android";
  return "PC";
}

deviceLabel.textContent = `기기: ${detectDevice()}`;

// ============================================================
// Status
// ============================================================

function setStatus(message, type = "info") {
  statusElement.textContent = message;
  const colors = {
    info: "#4a9eff",
    ok: "#4caf50",
    warn: "#ff9800",
    err: "#e53935",
  };
  statusElement.style.color = colors[type] || "#888";
}

// ============================================================
// Quality rendering
// ============================================================

function renderAudioQuality() {
  qualitySelect.innerHTML = "";
  ["320 kbps", "256 kbps", "192 kbps", "128 kbps", "96 kbps"]
    .forEach((value) => {
      const option = document.createElement("option");
      option.value = value;
      option.textContent = value;
      if (value === "192 kbps") option.selected = true;
      qualitySelect.appendChild(option);
    });
}

function renderM4aQuality(qualities) {
  // YouTube가 실제로 제공하는 audio-only m4a 트랙 목록
  qualitySelect.innerHTML = "";

  if (!Array.isArray(qualities) || qualities.length === 0) {
    const option = document.createElement("option");
    option.value = "";
    option.textContent = "사용 가능한 M4A 화질 확인 실패";
    qualitySelect.appendChild(option);
    return;
  }

  qualities.forEach((item, index) => {
    const option = document.createElement("option");
    option.value = item.format_id;
    const label = item.abr ? `${item.abr}kbps` : `트랙 ${item.format_id}`;
    option.textContent = index === 0 ? `${label} (기본, 최고음질)` : label;
    option.selected = index === 0;
    qualitySelect.appendChild(option);
  });
}

function renderMp4Quality(qualities) {
  // YouTube 기본(표준) 화질을 위에, 같은 높이의 추가 트랙/비표준 화질은 아래에 배치
  qualitySelect.innerHTML = "";

  if (!Array.isArray(qualities) || qualities.length === 0) {
    const option = document.createElement("option");
    option.value = "";
    option.textContent = "사용 가능한 MP4 화질 확인 실패";
    qualitySelect.appendChild(option);
    return;
  }

  const defaults = qualities.filter((q) => q.default);
  const extras = qualities.filter((q) => !q.default);

  let firstSet = false;

  const makeOption = (item) => {
    const option = document.createElement("option");
    option.value = item.format_id;
    const fpsLabel = item.fps && item.fps > 30 ? ` ${item.fps}fps` : "";
    option.textContent = item.default
      ? `${item.height}p (기본)${fpsLabel}`
      : `${item.height}p${fpsLabel}`;
    if (!firstSet) {
      option.selected = true;
      firstSet = true;
    }
    return option;
  };

  if (defaults.length) {
    const group = document.createElement("optgroup");
    group.label = "기본 화질";
    defaults.forEach((item) => group.appendChild(makeOption(item)));
    qualitySelect.appendChild(group);
  }

  if (extras.length) {
    const group = document.createElement("optgroup");
    group.label = "추가 화질";
    extras.forEach((item) => group.appendChild(makeOption(item)));
    qualitySelect.appendChild(group);
  }
}

function renderQuality() {
  if (currentFormat === "mp3") {
    renderAudioQuality();
    qualityHint.textContent = "MP3 음질";
    return;
  }

  if (currentFormat === "m4a") {
    if (currentVideoInfo) {
      renderM4aQuality(currentVideoInfo.m4a_qualities);
    } else {
      qualitySelect.innerHTML = "";
      const option = document.createElement("option");
      option.value = "";
      option.textContent = "먼저 영상 정보를 확인하세요.";
      qualitySelect.appendChild(option);
    }
    qualityHint.textContent = "YouTube가 제공하는 M4A 원본 화질";
    return;
  }

  // MP4
  if (currentVideoInfo) {
    renderMp4Quality(currentVideoInfo.mp4_qualities);
  } else {
    qualitySelect.innerHTML = "";
    const option = document.createElement("option");
    option.value = "";
    option.textContent = "먼저 영상 정보를 확인하세요.";
    qualitySelect.appendChild(option);
  }
  qualityHint.textContent = "YouTube 기본 제공 화질 우선 표시";
}

// ============================================================
// Format buttons
// ============================================================

document.querySelectorAll(".chip").forEach((button) => {
  button.addEventListener("click", async () => {
    document.querySelectorAll(".chip").forEach((b) =>
      b.classList.remove("active")
    );
    button.classList.add("active");
    currentFormat = button.dataset.format;
    renderQuality();

    if (currentFormat === "mp4" || currentFormat === "m4a") {
      await loadVideoInfo();
    }
  });
});

// ============================================================
// Load video information
// ============================================================

async function loadVideoInfo() {
  const url = urlInput.value.trim();
  if (!url) {
    setStatus("먼저 YouTube URL을 입력하세요.", "warn");
    return;
  }

  setStatus("영상 정보를 확인하는 중...", "info");

  try {
    const response = await fetch(
      `${API_BASE}/api/info?url=` + encodeURIComponent(url)
    );
    const data = await response.json();

    if (!response.ok) {
      throw new Error(extractServerError(data));
    }

    currentVideoInfo = data;
    videoInfo.classList.remove("hidden");
    videoTitle.textContent = data.title || "영상";

    const clientText = data.client ? `client: ${data.client}` : "";
    const durationText = data.duration ? formatDuration(data.duration) : "";

    videoMeta.textContent = [data.uploader || "", durationText, clientText]
      .filter(Boolean)
      .join(" · ");

    renderQuality();

    setStatus(
      data.client ? `영상 확인 완료 · ${data.client}` : "영상 확인 완료",
      "ok"
    );
  } catch (error) {
    currentVideoInfo = null;
    videoInfo.classList.add("hidden");
    renderQuality();
    setStatus("영상 정보 확인 실패: " + error.message, "err");
  }
}

// ============================================================
// Duration
// ============================================================

function formatDuration(seconds) {
  const total = Number(seconds);
  if (!Number.isFinite(total)) return "";
  const h = Math.floor(total / 3600);
  const m = Math.floor((total % 3600) / 60);
  const s = Math.floor(total % 60);
  if (h > 0) {
    return `${h}:${String(m).padStart(2, "0")}:${String(s).padStart(2, "0")}`;
  }
  return `${m}:${String(s).padStart(2, "0")}`;
}

// ============================================================
// Server error
// ============================================================

function extractServerError(data) {
  if (!data) return "서버 오류";
  if (typeof data.detail === "string") return data.detail;
  if (data.detail && typeof data.detail === "object") {
    if (data.detail.summary) return data.detail.summary;
    if (data.detail.message) return data.detail.message;
  }
  if (data.message) return data.message;
  return JSON.stringify(data);
}

// ============================================================
// Download
// ============================================================

// 서버 쪽 변환(추출+병합/인코딩) 단계는 진행률을 알 수 없으므로,
// 영상 길이(duration) 기반으로 대략적인 남은 시간을 추정한다.
// Render 무료 티어는 콜드 스타트 등으로 변동이 커서 어디까지나 "예상치"다.
const ESTIMATE_RATE = {
  mp3: { mult: 0.6, base: 5 },   // 오디오 추출 + mp3 인코딩
  m4a: { mult: 0.4, base: 4 },   // 오디오 리먹스 (재인코딩 없음, 더 빠름)
  mp4: { mult: 1.0, base: 8 },   // 비디오+오디오 다운로드 후 병합
};

let elapsedTimer = null;
let elapsedSeconds = 0;
let estimatedTotalSeconds = null;

function formatSeconds(sec) {
  sec = Math.max(0, Math.round(sec));
  const m = Math.floor(sec / 60);
  const s = sec % 60;
  return m > 0 ? `${m}분 ${s}초` : `${s}초`;
}

function estimateConversionSeconds(format, durationSeconds) {
  if (!Number.isFinite(durationSeconds) || durationSeconds <= 0) return null;
  const rate = ESTIMATE_RATE[format] || ESTIMATE_RATE.mp3;
  return durationSeconds * rate.mult + rate.base;
}

function updateElapsedStatus() {
  let text = `서버에서 변환 중... ${formatSeconds(elapsedSeconds)} 경과`;

  if (estimatedTotalSeconds) {
    const remaining = estimatedTotalSeconds - elapsedSeconds;
    text += remaining > 2
      ? ` (예상 남은 시간 약 ${formatSeconds(remaining)})`
      : ` (거의 완료됐어요...)`;
  }

  setStatus(text, "info");
}

function startElapsedTimer(estimateSeconds) {
  stopElapsedTimer();
  elapsedSeconds = 0;
  estimatedTotalSeconds = estimateSeconds || null;
  updateElapsedStatus();
  elapsedTimer = setInterval(() => {
    elapsedSeconds += 1;
    updateElapsedStatus();
  }, 1000);
}

function stopElapsedTimer() {
  if (elapsedTimer) {
    clearInterval(elapsedTimer);
    elapsedTimer = null;
  }
}

downloadButton.addEventListener("click", startDownload);

async function startDownload() {
  const url = urlInput.value.trim();
  if (!url) {
    setStatus("YouTube URL을 입력하세요.", "warn");
    urlInput.focus();
    return;
  }

  const needsQuality = currentFormat === "mp4" || currentFormat === "m4a";

  // mp3도 남은 시간 추정을 위해 영상 길이(duration)를 확인해 둔다.
  // (mp4/m4a는 화질 목록 때문에 원래도 필요했음)
  if (!currentVideoInfo) {
    await loadVideoInfo();
  }

  if (needsQuality && !currentVideoInfo) return;

  const quality = qualitySelect.value;
  if (needsQuality && !quality) {
    setStatus("사용 가능한 화질이 없습니다.", "err");
    return;
  }

  const params = new URLSearchParams({
    url,
    format: currentFormat,
    quality,
  });

  downloadButton.disabled = true;
  cancelButton.disabled = false;
  progressBar.style.width = "0%";

  const estimateSeconds = estimateConversionSeconds(
    currentFormat,
    currentVideoInfo ? currentVideoInfo.duration : null
  );
  startElapsedTimer(estimateSeconds);

  currentAbortController = new AbortController();

  try {
    const response = await fetch(`${API_BASE}/api/download?${params}`, {
      signal: currentAbortController.signal,
    });

    stopElapsedTimer();

    if (!response.ok) {
      const text = await response.text().catch(() => "");
      let message = text || `서버 오류 (${response.status})`;
      try {
        const parsed = JSON.parse(text);
        message = extractServerError(parsed);
      } catch (_) {}
      throw new Error(message);
    }

    // 파일명
    let filename =
      currentFormat === "mp3"
        ? "audio.mp3"
        : currentFormat === "m4a"
        ? "audio.m4a"
        : "video.mp4";

    const disposition = response.headers.get("content-disposition") || "";
    const match = disposition.match(
      /filename\*?=(?:UTF-8'')?["']?([^;"']+)["']?/i
    );

    if (match) {
      try {
        filename = decodeURIComponent(match[1]);
      } catch (_) {
        filename = match[1];
      }
    }

    const usedClient = response.headers.get("X-YTDLP-Client") || "";

    // Streaming
    const total = parseInt(response.headers.get("content-length") || "0", 10);
    const reader = response.body.getReader();
    const chunks = [];
    let received = 0;

    while (true) {
      const { done, value } = await reader.read();
      if (done) break;
      chunks.push(value);
      received += value.length;

      if (total > 0) {
        const percent = Math.min(100, (received / total) * 100);
        progressBar.style.width = `${percent.toFixed(1)}%`;
        setStatus(`다운로드 중... ${percent.toFixed(1)}%`, "info");
      } else {
        setStatus(
          `다운로드 중... ${(received / 1024 / 1024).toFixed(1)} MB`,
          "info"
        );
      }
    }

    const blob = new Blob(chunks, {
      type:
        currentFormat === "mp3"
          ? "audio/mpeg"
          : currentFormat === "m4a"
          ? "audio/mp4"
          : "video/mp4",
    });

    const link = document.createElement("a");
    const objectUrl = URL.createObjectURL(blob);
    link.href = objectUrl;
    link.download = filename;
    document.body.appendChild(link);
    link.click();
    link.remove();

    setTimeout(() => URL.revokeObjectURL(objectUrl), 30000);

    progressBar.style.width = "100%";

    setStatus(
      usedClient ? `다운로드 완료 · ${usedClient}` : "다운로드 완료",
      "ok"
    );
  } catch (error) {
    stopElapsedTimer();
    if (error.name === "AbortError") {
      setStatus("다운로드가 취소되었습니다.", "warn");
    } else {
      console.error(error);
      setStatus(
        "다운로드 실패: " + error.message + " · 자동 진단을 시작합니다.",
        "err"
      );
      await runDiagnosis(true);
    }
  } finally {
    stopElapsedTimer();
    downloadButton.disabled = false;
    cancelButton.disabled = true;
    currentAbortController = null;
  }
}

// ============================================================
// Cancel
// ============================================================

cancelButton.addEventListener("click", () => {
  if (currentAbortController) {
    currentAbortController.abort();
    setStatus("취소 중...", "warn");
  }
});

// ============================================================
// Diagnosis
// ============================================================

diagnoseButton.addEventListener("click", () => runDiagnosis(false));

async function runDiagnosis(automatic) {
  const url = urlInput.value.trim();
  if (!url) {
    if (!automatic) setStatus("진단하려면 YouTube URL을 입력하세요.", "warn");
    return;
  }

  diagnoseButton.disabled = true;
  diagnoseResult.textContent = "진단 중...\n\n";

  try {
    const controller = new AbortController();
    const timer = setTimeout(() => controller.abort(), 90000);

    const response = await fetch(
      `${API_BASE}/api/diagnose?url=` + encodeURIComponent(url),
      { signal: controller.signal }
    );
    clearTimeout(timer);

    const data = await response.json();

    if (!response.ok) {
      throw new Error(extractServerError(data));
    }

    diagnoseResult.textContent = JSON.stringify(data, null, 2);

    if (
      Array.isArray(data.successful_clients) &&
      data.successful_clients.length
    ) {
      setStatus(
        `${automatic ? "자동 진단" : "진단"} 완료 · 성공 client: ${
          data.successful_clients[0]
        }`,
        "ok"
      );
    } else {
      setStatus("진단 완료 · 성공한 client가 없습니다.", "err");
    }
  } catch (error) {
    diagnoseResult.textContent = "진단 실패\n\n" + error.message;
    setStatus("진단 요청 자체가 실패했습니다.", "err");
  } finally {
    diagnoseButton.disabled = false;
  }
}

// ============================================================
// URL 변경 시 초기화
// ============================================================

urlInput.addEventListener("change", () => {
  currentVideoInfo = null;
  videoInfo.classList.add("hidden");
  if (currentFormat === "mp4" || currentFormat === "m4a") renderQuality();
});

// ============================================================
// 초기화
// ============================================================

renderQuality();
urlInput.focus();

// ============================================================
// Service Worker
// ============================================================

if ("serviceWorker" in navigator) {
  window.addEventListener("load", () => {
    navigator.serviceWorker.register("./service-worker.js").catch(() => {});
  });
}
