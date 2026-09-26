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

function renderM4aQuality() {
  // M4A는 원본 음질 그대로 → 선택 옵션 1개
  qualitySelect.innerHTML = "";
  const option = document.createElement("option");
  option.value = "best";
  option.textContent = "원본 음질 (재인코딩 없음)";
  option.selected = true;
  qualitySelect.appendChild(option);
}

function renderMp4Quality(heights) {
  qualitySelect.innerHTML = "";

  if (!Array.isArray(heights) || heights.length === 0) {
    const option = document.createElement("option");
    option.value = "";
    option.textContent = "사용 가능한 MP4 화질 확인 실패";
    qualitySelect.appendChild(option);
    return;
  }

  const uniqueHeights = [...new Set(heights.map(Number).filter(Number.isFinite))]
    .sort((a, b) => b - a);

  uniqueHeights.forEach((height, index) => {
    const option = document.createElement("option");
    option.value = `${height}p`;
    option.textContent = index === 0 ? `${height}p (기본)` : `${height}p`;
    option.selected = index === 0;
    qualitySelect.appendChild(option);
  });
}

function renderQuality() {
  if (currentFormat === "mp3") {
    renderAudioQuality();
    qualityHint.textContent = "MP3 음질";
    return;
  }

  if (currentFormat === "m4a") {
    renderM4aQuality();
    qualityHint.textContent = "원본 음질";
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
  qualityHint.textContent = "YouTube에서 확인된 MP4 화질";
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

    if (currentFormat === "mp4") {
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

downloadButton.addEventListener("click", startDownload);

async function startDownload() {
  const url = urlInput.value.trim();
  if (!url) {
    setStatus("YouTube URL을 입력하세요.", "warn");
    urlInput.focus();
    return;
  }

  if (currentFormat === "mp4" && !currentVideoInfo) {
    await loadVideoInfo();
    if (!currentVideoInfo) return;
  }

  const quality = qualitySelect.value;
  if (currentFormat === "mp4" && !quality) {
    setStatus("사용 가능한 MP4 화질이 없습니다.", "err");
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

  setStatus("서버에서 다운로드를 준비하는 중...", "info");

  currentAbortController = new AbortController();

  try {
    const response = await fetch(`${API_BASE}/api/download?${params}`, {
      signal: currentAbortController.signal,
    });

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
  if (currentFormat === "mp4") renderQuality();
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
