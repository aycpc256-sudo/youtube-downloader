"use strict";

const API_BASE = "https://youtube-downloader-onww.onrender.com";

const urlInput = document.querySelector("#diag-url");
const diagnoseButton = document.querySelector("#diagnose-btn");
const healthButton = document.querySelector("#health-btn");
const statusEl = document.querySelector("#diag-status");
const summaryCard = document.querySelector("#summary-card");
const summaryEl = document.querySelector("#summary");
const clientsCard = document.querySelector("#clients-card");
const clientsEl = document.querySelector("#clients");
const rawCard = document.querySelector("#raw-card");
const rawJson = document.querySelector("#raw-json");
const copyButton = document.querySelector("#copy-btn");

function setStatus(text, type = "info") {
  statusEl.textContent = text;
  const colors = {
    info: "#4a9eff",
    ok: "#4caf50",
    warn: "#ff9800",
    err: "#e53935",
  };
  statusEl.style.color = colors[type] || "#888";
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
  if (value === null || value === undefined || value === "") return "-";
  if (typeof value === "object") return JSON.stringify(value);
  return String(value);
}

function renderSummary(data) {
  const deno = data.deno || {};
  const bgutil = data.bgutil || {};

  const items = [
    ["yt-dlp", data.yt_dlp, "ok"],
    ["Deno", deno.ok ? (deno.version || "정상") : "실패", deno.ok ? "ok" : "bad"],
    ["BgUtils", bgutil.ok ? "정상" : "실패", bgutil.ok ? "ok" : "bad"],
    ["Cookie", data.cookies ? "설정됨" : "없음", data.cookies ? "ok" : "warn"],
    ["성공 Client", (data.successful_clients || []).join(", ") || "없음",
      (data.successful_clients || []).length ? "ok" : "bad"],
    ["진단 시간", data.elapsed_seconds != null ? `${data.elapsed_seconds}초` : "-", "muted"],
  ];

  summaryEl.innerHTML = items.map(([k, v, cls]) => `
    <div class="diag-item">
      <div class="k">${escapeHtml(k)}</div>
      <div class="v ${cls}">${escapeHtml(valueText(v))}</div>
    </div>
  `).join("");

  summaryCard.classList.remove("hidden");
}

function renderClients(data) {
  const clients = Array.isArray(data.clients) ? data.clients : [];

  if (!clients.length) {
    clientsEl.innerHTML = '<div class="muted">Client 결과가 없습니다.</div>';
    clientsCard.classList.remove("hidden");
    return;
  }

  clientsEl.innerHTML = clients.map((item) => {
    const ok = item.ok;
    return `
      <div class="client">
        <div class="client-head">
          <strong>${escapeHtml(item.client)}</strong>
          <span class="${ok ? "ok" : "bad"}">${ok ? "성공" : "실패"}</span>
        </div>
        <div class="hint" style="margin-top:6px;">
          ${escapeHtml(item.seconds != null ? `${item.seconds}초` : "")}
          ${item.format_count != null ? ` · formats ${escapeHtml(item.format_count)}` : ""}
          ${item.code ? ` · ${escapeHtml(item.code)}` : ""}
        </div>
        ${item.title ? `<div style="margin-top:8px;">${escapeHtml(item.title)}</div>` : ""}
        ${item.error ? `<div class="small-note">${escapeHtml(item.error)}</div>` : ""}
      </div>
    `;
  }).join("");

  clientsCard.classList.remove("hidden");
}

function renderRaw(data) {
  rawJson.textContent = JSON.stringify(data, null, 2);
  rawCard.classList.remove("hidden");
}

function extractError(data) {
  if (!data) return "서버 오류";
  if (typeof data.detail === "string") return data.detail;
  if (data.detail && typeof data.detail === "object") {
    return data.detail.message || data.detail.summary || JSON.stringify(data.detail);
  }
  return data.message || JSON.stringify(data);
}

async function requestJson(path, timeoutMs = 120000) {
  const controller = new AbortController();
  const timer = setTimeout(() => controller.abort(), timeoutMs);

  try {
    const response = await fetch(`${API_BASE}${path}`, {
      signal: controller.signal,
    });

    const text = await response.text();
    let data = {};
    try {
      data = text ? JSON.parse(text) : {};
    } catch {
      data = { message: text };
    }

    if (!response.ok) {
      throw new Error(extractError(data) || `HTTP ${response.status}`);
    }

    return data;
  } finally {
    clearTimeout(timer);
  }
}

healthButton.addEventListener("click", async () => {
  healthButton.disabled = true;
  setStatus("서버 상태 확인 중...", "info");

  try {
    const data = await requestJson("/api/health", 30000);
    renderSummary(data);
    renderRaw(data);
    clientsCard.classList.add("hidden");
    setStatus("서버 상태 확인 완료", "ok");
  } catch (error) {
    setStatus(`서버 상태 확인 실패: ${error.message}`, "err");
  } finally {
    healthButton.disabled = false;
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
  setStatus("YouTube 접근 진단 중입니다. 잠시 기다려 주세요...", "info");
  summaryCard.classList.add("hidden");
  clientsCard.classList.add("hidden");
  rawCard.classList.add("hidden");

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
    rawJson.textContent = `진단 실패\n\n${error.message}`;
    rawCard.classList.remove("hidden");
    setStatus(`진단 실패: ${error.message}`, "err");
  } finally {
    diagnoseButton.disabled = false;
    healthButton.disabled = false;
  }
});

copyButton.addEventListener("click", async () => {
  try {
    await navigator.clipboard.writeText(rawJson.textContent);
    copyButton.textContent = "복사 완료";
    setTimeout(() => {
      copyButton.textContent = "복사";
    }, 1500);
  } catch {
    setStatus("JSON 복사에 실패했습니다.", "warn");
  }
});

urlInput.addEventListener("keydown", (event) => {
  if (event.key === "Enter") diagnoseButton.click();
});
