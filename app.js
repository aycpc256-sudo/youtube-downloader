// ======================================================
// Render 백엔드 주소
// ======================================================

const API_BASE =
  "https://youtube-downloader-onww.onrender.com";


// ======================================================
// DOM
// ======================================================

const $ = (s) => document.querySelector(s);

const urlInput       = $("#url");
const qualitySel     = $("#quality");
const qualityHint    = $("#quality-hint");

const downloadBtn    = $("#download-btn");
const cancelBtn      = $("#cancel-btn");

const progressBar    = $("#progress-bar");
const statusEl       = $("#status");

const deviceLabel    = $("#device-label");

const folderHint     = $("#folder-hint");
const folderName     = $("#folder-name");
const pickFolder     = $("#pick-folder-btn");
const askFolder      = $("#ask-folder");

const diagnosticCard  = $("#diagnostic-card");
const diagnoseBtn     = $("#diagnose-btn");
const diagnosticResult = $("#diagnostic-result");


// ======================================================
// 상태
// ======================================================

let currentFormat = "mp3";

let currentAbort = null;

let currentInfo = null;


// ======================================================
// 기기
// ======================================================

function detectDevice() {

  const ua = navigator.userAgent;

  if (/iPhone|iPad|iPod/i.test(ua)) {
    return "ios";
  }

  if (/Android/i.test(ua)) {
    return "android";
  }

  return "pc";
}

const DEVICE = detectDevice();

const HAS_FS_API =
  "showSaveFilePicker" in window;


// ======================================================
// MP3 기본 음질
// ======================================================

const MP3_QUALITY = [
  "320 kbps",
  "256 kbps",
  "192 kbps",
  "128 kbps",
  "96 kbps"
];


// ======================================================
// M4A
// ======================================================

const M4A_QUALITY = [
  "기본"
];


// ======================================================
// 실제 MP4 화질
// ======================================================

let mp4Qualities = [
  "1080p (기본)"
];


// ======================================================
// 상태
// ======================================================

function setStatus(msg, kind = "info") {

  statusEl.textContent = msg;

  const colors = {
    info: "#4a9eff",
    ok: "#4caf50",
    warn: "#ff9800",
    err: "#e53935"
  };

  statusEl.style.color =
    colors[kind] || "#888";
}


// ======================================================
// MP4 실제 화질 정리
// ======================================================

function buildMp4Qualities(formats) {

  if (!Array.isArray(formats)) {
    return [
      "1080p (기본)"
    ];
  }

  const heights = [
    ...new Set(
      formats
        .filter((f) => {

          return (
            f &&
            f.height &&
            Number(f.height) > 0 &&
            (
              f.ext === "mp4" ||
              f.video_ext === "mp4"
            )
          );

        })
        .map((f) => Number(f.height))
    )
  ];

  heights.sort((a, b) => b - a);

  if (!heights.length) {

    return [
      "1080p (기본)"
    ];

  }

  return heights.map((h, index) => {

    if (index === 0) {
      return `${h}p (기본)`;
    }

    return `${h}p`;
  });
}


// ======================================================
// 품질 UI
// ======================================================

function renderQuality() {

  let options = [];

  if (currentFormat === "mp3") {

    options = MP3_QUALITY;

    qualityHint.textContent =
      "MP3 음질";

  }

  else if (currentFormat === "m4a") {

    options = M4A_QUALITY;

    qualityHint.textContent =
      "YouTube 기본 오디오";

  }

  else if (currentFormat === "mp4") {

    options = mp4Qualities;

    qualityHint.textContent =
      "YouTube 제공 화질";

  }


  qualitySel.innerHTML =
    options
      .map((value) =>
        `<option value="${value}">
          ${value}
        </option>`
      )
      .join("");


  if (currentFormat === "mp3") {

    qualitySel.value =
      "192 kbps";

  }

  else {

    qualitySel.value =
      options[0];

  }
}


// ======================================================
// 영상 정보 가져오기
// ======================================================

async function loadVideoInfo() {

  const url =
    urlInput.value.trim();

  if (!url) {
    return null;
  }


  setStatus(
    "YouTube 영상 정보를 확인하는 중...",
    "info"
  );


  const response =
    await fetch(
      `${API_BASE}/api/info?url=${encodeURIComponent(url)}`
    );


  if (!response.ok) {

    const text =
      await response.text();

    throw new Error(
      text || `영상 정보 오류 (${response.status})`
    );
  }


  const data =
    await response.json();


  currentInfo = data;


  mp4Qualities =
    buildMp4Qualities(
      data.formats
    );


  if (currentFormat === "mp4") {
    renderQuality();
  }


  return data;
}


// ======================================================
// URL 변경 시 실제 포맷 조회
// ======================================================

let infoTimer = null;

urlInput.addEventListener(
  "change",
  async () => {

    try {

      await loadVideoInfo();

      setStatus(
        "영상 정보를 확인했습니다.",
        "ok"
      );

    }

    catch (err) {

      console.error(err);

      setStatus(
        "영상 정보 확인 실패: " +
        err.message,
        "warn"
      );

    }

  }
);


// ======================================================
// 기기 UI
// ======================================================

function initDeviceUI() {

  const label = {
    ios: "iPhone / iPad",
    android: "Android",
    pc: "PC"
  }[DEVICE];


  deviceLabel.textContent =
    `감지된 기기: ${label}`;


  if (HAS_FS_API) {

    folderHint.textContent =
      "PC · 저장 시 파일 위치 선택 가능";

    askFolder.checked = true;

    askFolder.disabled = false;

    pickFolder.textContent =
      "폴더 열기";

    pickFolder.disabled = false;

    folderName.textContent =
      "저장할 때 선택";

  }

  else {

    askFolder.checked = false;

    askFolder.disabled = true;

    pickFolder.disabled = true;

    if (DEVICE === "ios") {

      folderHint.textContent =
        "Safari 다운로드 위치에 저장";

      folderName.textContent =
        "파일 앱";

    }

    else if (DEVICE === "android") {

      folderHint.textContent =
        "기본 다운로드 폴더에 저장";

      folderName.textContent =
        "Download";

    }

    else {

      folderHint.textContent =
        "브라우저 기본 다운로드 폴더";

      folderName.textContent =
        "다운로드 폴더";

    }

  }
}


// ======================================================
// 형식 버튼
// ======================================================

document
  .querySelectorAll(".chip")
  .forEach((btn) => {

    btn.addEventListener(
      "click",
      async () => {

        document
          .querySelectorAll(".chip")
          .forEach((b) =>
            b.classList.remove("active")
          );


        btn.classList.add("active");


        currentFormat =
          btn.dataset.format;


        // MP4를 누르면 실제 화질 확인
        if (
          currentFormat === "mp4" &&
          urlInput.value.trim()
        ) {

          try {

            await loadVideoInfo();

          }

          catch (err) {

            console.error(err);

          }

        }


        renderQuality();

      }
    );

  });


// ======================================================
// 다운로드
// ======================================================

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


  // MP4이면 실제 영상 정보를 먼저 확인
  if (currentFormat === "mp4") {

    try {

      await loadVideoInfo();

    }

    catch (err) {

      console.error(err);

    }

  }


  const quality =
    qualitySel.value;


  const params =
    new URLSearchParams({
      url,
      format: currentFormat,
      quality
    });


  downloadBtn.disabled = true;

  cancelBtn.disabled = false;


  progressBar.style.width =
    "0%";


  setStatus(
    "서버 준비 중...",
    "info"
  );


  currentAbort =
    new AbortController();


  try {

    const response =
      await fetch(
        `${API_BASE}/api/download?${params}`,
        {
          signal:
            currentAbort.signal
        }
      );


    if (!response.ok) {

      const text =
        await response.text()
          .catch(() => "");


      throw new Error(
        text ||
        `서버 오류 (${response.status})`
      );

    }


    // 파일명
    let filename;


    if (currentFormat === "mp3") {
      filename = "audio.mp3";
    }

    else if (currentFormat === "m4a") {
      filename = "audio.m4a";
    }

    else {
      filename = "video.mp4";
    }


    const cd =
      response.headers
        .get("content-disposition") || "";


    const match =
      cd.match(
        /filename\*?=(?:UTF-8'')?"?([^";]+)"?/i
      );


    if (match) {

      try {

        filename =
          decodeURIComponent(
            match[1]
          );

      }

      catch (_) {}

    }


    // 파일 읽기
    const total =
      parseInt(
        response.headers
          .get("content-length") || "0",
        10
      );


    const reader =
      response.body.getReader();


    const chunks = [];

    let received = 0;


    while (true) {

      const {
        done,
        value
      } =
        await reader.read();


      if (done) {
        break;
      }


      chunks.push(value);

      received += value.length;


      if (total) {

        const pct =
          Math.min(
            100,
            (received / total) * 100
          );


        progressBar.style.width =
          pct.toFixed(1) + "%";


        setStatus(
          `다운로드 중... ${pct.toFixed(1)}%`,
          "info"
        );

      }

      else {

        setStatus(
          `다운로드 중... ` +
          `${(received / 1024 / 1024).toFixed(1)} MB`,
          "info"
        );

      }

    }


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


    // PC 저장 위치 선택
    if (
      HAS_FS_API &&
      askFolder.checked
    ) {

      try {

        const handle =
          await window.showSaveFilePicker({
            suggestedName: filename
          });


        const writable =
          await handle.createWritable();


        await writable.write(blob);

        await writable.close();


        folderName.textContent =
          handle.name;


        setStatus(
          "저장 완료!",
          "ok"
        );

      }

      catch (err) {

        if (
          err.name === "AbortError"
        ) {

          setStatus(
            "저장이 취소되었습니다.",
            "warn"
          );

        }

        else {

          throw err;

        }

      }

    }

    else {

      const objectUrl =
        URL.createObjectURL(blob);


      const a =
        document.createElement("a");


      a.href =
        objectUrl;

      a.download =
        filename;


      document.body.appendChild(a);

      a.click();

      a.remove();


      setTimeout(
        () =>
          URL.revokeObjectURL(objectUrl),
        30000
      );


      setStatus(
        "다운로드 완료!",
        "ok"
      );

    }

  }

  catch (err) {

    if (
      err.name === "AbortError"
    ) {

      setStatus(
        "취소되었습니다.",
        "warn"
      );

    }

    else {

      console.error(err);


      setStatus(
        "다운로드 실패: " +
        err.message,
        "err"
      );


      // 실패하면 진단창 표시
      diagnosticCard.hidden =
        false;


      diagnoseVideo();

    }

  }

  finally {

    downloadBtn.disabled =
      false;

    cancelBtn.disabled =
      true;

    currentAbort =
      null;

  }
}


// ======================================================
// 취소
// ======================================================

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


// ======================================================
// 폴더
// ======================================================

pickFolder.addEventListener(
  "click",
  async () => {

    if (!HAS_FS_API) {
      return;
    }


    try {

      const dir =
        await window.showDirectoryPicker({
          mode: "read"
        });


      folderName.textContent =
        dir.name;


      setStatus(
        "저장 위치를 선택했습니다.",
        "info"
      );

    }

    catch (err) {

      if (
        err.name !== "AbortError"
      ) {

        console.error(err);

      }

    }

  }
);


// ======================================================
// 진단
// ======================================================

diagnoseBtn.addEventListener(
  "click",
  diagnoseVideo
);


async function diagnoseVideo() {

  const url =
    urlInput.value.trim();


  if (!url) {

    diagnosticResult.innerHTML =
      `<div class="diag-summary">
        YouTube URL을 먼저 입력하세요.
      </div>`;

    return;

  }


  diagnosticCard.hidden =
    false;


  diagnoseBtn.disabled =
    true;


  diagnosticResult.innerHTML =
    `<div class="diag-summary">
      YouTube 연결 상태를 확인하는 중...
    </div>`;


  try {

    const response =
      await fetch(
        `${API_BASE}/api/diagnose?url=${encodeURIComponent(url)}`
      );


    const data =
      await response.json();


    renderDiagnosis(data);

  }

  catch (err) {

    diagnosticResult.innerHTML =
      `<div class="diag-summary diag-error">
        진단 요청 실패
        <br>
        ${escapeHtml(err.message)}
      </div>`;

  }

  finally {

    diagnoseBtn.disabled =
      false;

  }
}


// ======================================================
// 진단 결과 표시
// ======================================================

function renderDiagnosis(data) {

  const diagnosis =
    data.diagnosis || {};


  const title =
    diagnosis.title ||
    data.message ||
    "진단 결과";


  const level =
    diagnosis.level ||
    "warn";


  const css =
    level === "ok"
      ? "diag-good"
      : level === "error"
        ? "diag-error"
        : "diag-warn";


  let html = `

    <div class="diag-summary">

      <div class="diag-title ${css}">
        ${escapeHtml(title)}
      </div>

      <div class="diag-row">
        <span class="diag-label">
          yt-dlp
        </span>

        <span class="diag-value">
          ${escapeHtml(
            data.yt_dlp || "-"
          )}
        </span>
      </div>

      <div class="diag-row">
        <span class="diag-label">
          YouTube 연결
        </span>

        <span class="diag-value">
          ${escapeHtml(
            data.youtube_http || "-"
          )}
        </span>
      </div>

      <div class="diag-row">
        <span class="diag-label">
          BgUtils / PO Token
        </span>

        <span class="diag-value">
          ${escapeHtml(
            data.bgutil || "-"
          )}
        </span>
      </div>

      <div class="diag-row">
        <span class="diag-label">
          FFmpeg
        </span>

        <span class="diag-value">
          ${escapeHtml(
            data.ffmpeg || "-"
          )}
        </span>
      </div>

    </div>
  `;


  // Client 결과
  if (
    Array.isArray(
      data.clients
    )
  ) {

    html += `
      <div class="diag-summary">

        <div class="diag-title">
          Player Client 비교
        </div>
    `;


    for (
      const client of data.clients
    ) {

      const ok =
        client.ok === true;


      html += `
        <div class="diag-row">

          <span class="diag-label">
            ${escapeHtml(
              client.client || "-"
            )}
          </span>

          <span class="diag-value ${
            ok
              ? "diag-good"
              : "diag-error"
          }">

            ${ok ? "성공" : "실패"}

          </span>

        </div>
      `;

    }


    html += `
      </div>
    `;

  }


  // 상세
  const raw =
    data.raw ||
    data.error ||
    data.details ||
    "";


  if (raw) {

    html += `
      <details class="diag-details">

        <summary>
          상세 진단 정보
        </summary>

        <pre class="diag-pre">
${escapeHtml(
  typeof raw === "string"
    ? raw
    : JSON.stringify(
        raw,
        null,
        2
      )
)}
        </pre>

      </details>
    `;

  }


  diagnosticResult.innerHTML =
    html;
}


// ======================================================
// HTML escape
// ======================================================

function escapeHtml(value) {

  return String(value ?? "")
    .replaceAll("&", "&amp;")
    .replaceAll("<", "&lt;")
    .replaceAll(">", "&gt;")
    .replaceAll('"', "&quot;")
    .replaceAll("'", "&#039;");
}


// ======================================================
// 초기화
// ======================================================

initDeviceUI();

renderQuality();

urlInput.focus();


// ======================================================
// Service Worker
// ======================================================

if (
  "serviceWorker" in navigator
) {

  navigator.serviceWorker
    .register(
      "service-worker.js"
    )
    .catch(() => {});

}
