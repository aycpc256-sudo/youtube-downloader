"use strict";

/*
 * Current backend/server.py and app.js use this Render API.
 * Keep this value in sync with app.js.
 */
const API_BASE = "https://youtube-downloader-onww.onrender.com";

const $ = (selector) => document.querySelector(selector);

const urlInput = $("#diagnostic-url");
const healthButton = $("#health-btn");
const diagnoseButton = $("#diagnose-btn");
const statusElement = $("#diag-status");

const summaryCard = $("#summary-card");
const summaryElement = $("#summary");

const clientsCard = $("#clients-card");
const clientsElement = $("#clients");

const rawCard = $("#raw-card");
const rawElement = $("#raw-json");
const copyButton = $("#copy-btn");

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

function escapeHtml(value) {
  return String(value ?? "")
    .replaceAll("&", "&amp;")
    .replaceAll("<", "&lt;")
    .replaceAll(">", "&gt;")
    .replaceAll('"', "&quot;")
    .replaceAll("'", "&#039;");
}

function valueText(value) {
  if (value === null || value === undefined || value === "") {
    return "-";
  }

  if (typeof value === "object") {
    return JSON.stringify(value);
  }

  return String(value);
}

function extractServerError(data) {
  if (!data) return "서버 오류";

  if (typeof data.detail === "string") {
    return data.detail;
  }

  if (data.detail && typeof data.detail === "object") {
    if (data.detail.summary) return data.detail.summary;
    if (data.detail.message) return data.detail.message;
  }

  if (data.message) return data.message;

  return JSON.stringify(data);
}

async function requestJson(path, timeoutMs = 120000) {
  const controller = new AbortController();
  const timer = setTimeout(() => controller.abort(), timeoutMs);

  try {
    const response = await fetch(`${API_BASE}${path}`, {
      method: "GET",
      headers: {
        Accept: "application/json",
      },
      signal: controller.signal,
    });

    const text = await response.text();

    let data = {};
    try {
      data = text ? JSON.parse(text) : {};
    } catch (_) {
      data = { message: text };
    }

    if (!response.ok) {
      throw new Error(
        extractServerError(data) || `HTTP ${response.status}`
      );
    }

    return data;
  } finally {
    clearTimeout(timer);
  }
}

function renderSummary(data) {
  const deno = data.deno || {};
  const bgutil = data.bgutil || {};

  const successfulClients = Array.isArray(data.successful_clients)
    ? data.successful_clients
    : [];

  const items = [
    ["yt-dlp", data.yt_dlp, data.yt_dlp ? "ok" : "bad"],
    [
      "Deno",
      deno.ok ? (deno.version || "정상") : "실패",
      deno.ok ? "ok" : "bad",
    ],
    [
      "BgUtils",
      bgutil.ok ? "정상" : "실패",
      bgutil.ok ? "ok" : "bad",
    ],
    [
      "Cookie",
      data.cookies ? "설정됨" : "없음",
      data.cookies ? "ok" : "warn",
    ],
    [
      "성공 Client",
      successfulClients.length
        ? successfulClients.join(", ")
        : "없음",
      successfulClients.length ? "ok" : "bad",
    ],
    [
      "진단 시간",
      data.elapsed_seconds != null
        ? `${data.elapsed_seconds}초`
        : "-",
      "muted",
    ],
  ];

  summaryElement.innerHTML = items
    .map(
      ([key, value, cls]) => `
        <div class="diag-item">
          <div class="k">${escapeHtml(key)}</div>
          <div class="v ${cls}">${escapeHtml(valueText(value))}</div>
        </div>
      `
    )
    .join("");

  summaryCard.classList.remove("hidden");
}

function renderClients(data) {
  const clients = Array.isArray(data.clients)
    ? data.clients
    : [];

  if (!clients.length) {
    clientsElement.innerHTML =
      '<div class="hint">Client 결과가 없습니다.</div>';
    clientsCard.classList.remove("hidden");
    return;
  }

  clientsElement.innerHTML = clients
    .map((item) => {
      const ok = item.ok === true;

      return `
        <div class="diag-item" style="margin-top:8px;">
          <div class="row between">
            <strong>${escapeHtml(item.client || "unknown")}</strong>
            <span class="${ok ? "ok" : "bad"}">
              ${ok ? "성공" : "실패"}
            </span>
          </div>

          <div class="diag-note" style="margin-top:6px;">
            ${item.seconds != null ? `소요 ${escapeHtml(item.seconds)}초` : ""}
            ${item.format_count != null ? ` · formats ${escapeHtml(item.format_count)}` : ""}
            ${item.code ? ` · ${escapeHtml(item.code)}` : ""}
          </div>

          ${
            item.title
              ? `<div style="margin-top:8px;">${escapeHtml(item.title)}</div>`
              : ""
          }

          ${
            item.error
              ? `<div class="diag-note" style="margin-top:6px;">${escapeHtml(item.error)}</div>`
              : ""
          }
        </div>
      `;
    })
    .join("");

  clientsCard.classList.remove("hidden");
}

function renderRaw(data) {
  rawElement.textContent = JSON.stringify(data, null, 2);
  rawCard.classList.remove("hidden");
}

healthButton.addEventListener("click", async () => {
  healthButton.disabled = true;
  diagnoseButton.disabled = true;

  setStatus("Render 서버 상태 확인 중...", "info");

  try {
    const data = await requestJson("/api/health", 30000);

    renderSummary(data);
    renderRaw(data);

    clientsCard.classList.add("hidden");

    setStatus("서버 상태 확인 완료", "ok");
  } catch (error) {
    rawElement.textContent =
      `서버 상태 확인 실패\n\n${error.message}`;

    rawCard.classList.remove("hidden");

    setStatus(
      `서버 상태 확인 실패: ${error.message}`,
      "err"
    );
  } finally {
    healthButton.disabled = false;
    diagnoseButton.disabled = false;
  }
});

diagnoseButton.addEventListener("click", async () => {
  const url = urlInput.value.trim();

  if (!url) {
    setStatus("YouTube URL을 입력하세요.", "warn");
    urlInput.focus();
    return;
  }

  diagnoseButton.disabled = true;
  healthButton.disabled = true;

  summaryCard.classList.add("hidden");
  clientsCard.classList.add("hidden");
  rawCard.classList.add("hidden");

  setStatus(
    "YouTube 접근 진단 중입니다. Render 무료 서버가 깨어나는 데 시간이 걸릴 수 있습니다...",
    "info"
  );

  try {
    const data = await requestJson(
      "/api/diagnose?url=" + encodeURIComponent(url),
      120000
    );

    renderSummary(data);
    renderClients(data);
    renderRaw(data);

    const successful = Array.isArray(data.successful_clients)
      ? data.successful_clients
      : [];

    if (successful.length) {
      setStatus(
        `진단 완료 · 성공 client: ${successful.join(", ")}`,
        "ok"
      );
    } else {
      setStatus(
        "진단 완료 · 성공한 YouTube client가 없습니다.",
        "err"
      );
    }
  } catch (error) {
    rawElement.textContent =
      `진단 실패\n\n${error.message}`;

    rawCard.classList.remove("hidden");

    if (error.name === "AbortError") {
      setStatus(
        "진단 시간이 초과되었습니다. Render 서버 상태를 확인하세요.",
        "err"
      );
    } else {
      setStatus(
        `진단 요청 실패: ${error.message}`,
        "err"
      );
    }
  } finally {
    diagnoseButton.disabled = false;
    healthButton.disabled = false;
  }
});

copyButton.addEventListener("click", async () => {
  try {
    await navigator.clipboard.writeText(rawElement.textContent);
    copyButton.textContent = "복사 완료";

    setTimeout(() => {
      copyButton.textContent = "복사";
    }, 1500);
  } catch (_) {
    setStatus("JSON 복사에 실패했습니다.", "warn");
  }
});

urlInput.addEventListener("keydown", (event) => {
  if (event.key === "Enter") {
    diagnoseButton.click();
  }
});
