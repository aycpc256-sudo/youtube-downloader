// ============================================================
// Render Backend
// ============================================================

const API_BASE =
  "https://youtube-downloader-onww.onrender.com";


// ============================================================
// DOM
// ============================================================

const $ = (selector) =>
  document.querySelector(selector);


const urlInput =
  $("#url");

const qualitySel =
  $("#quality");

const qualityHint =
  $("#quality-hint");

const downloadBtn =
  $("#download-btn");

const cancelBtn =
  $("#cancel-btn");

const progressBar =
  $("#progress-bar");

const statusEl =
  $("#status");

const deviceLabel =
  $("#device-label");

const folderHint =
  $("#folder-hint");

const folderName =
  $("#folder-name");

const pickFolder =
  $("#pick-folder-btn");

const askFolder =
  $("#ask-folder");

const diagnoseBtn =
  $("#diagnose-btn");

const diagnosticResult =
  $("#diagnostic-result");

const diagnosticSummary =
  $("#diagnostic-summary");

const diagnosticItems =
  $("#diagnostic-items");

const diagnosticLog =
  $("#diagnostic-log");


// ============================================================
// 상태
// ============================================================

let currentFormat =
  "mp3";

let currentAbort =
  null;

let diagnosisRunning =
  false;


// ============================================================
// 기기 감지
// ============================================================

function detectDevice() {

  const ua =
    navigator.userAgent;

  if (
    /iPhone|iPad|iPod/i.test(ua)
  ) {
    return "ios";
  }

  if (
    /Android/i.test(ua)
  ) {
    return "android";
  }

  return "pc";
}


const DEVICE =
  detectDevice();


const HAS_FS_API =
  "showSaveFilePicker" in window;


// ============================================================
// 품질
// ============================================================

const QUALITY = {

  mp3: [
    "320 kbps",
    "256 kbps",
    "192 kbps",
    "128 kbps",
    "96 kbps",
  ],

  m4a: [
    "320 kbps",
    "256 kbps",
    "192 kbps",
    "128 kbps",
    "96 kbps",
  ],

  mp4: [
    "최고 화질",
    "2160p (4K)",
    "1440p",
    "1080p",
    "720p",
    "480p",
    "360p",
  ],
};


function renderQuality() {

  const options =
    QUALITY[currentFormat];

  qualitySel.innerHTML =
    options
      .map(
        (value) =>
          `<option>${value}</option>`
      )
      .join("");


  if (
    currentFormat === "mp4"
  ) {

    qualitySel.value =
      "최고 화질";

    qualityHint.textContent =
      "MP4 영상 화질";

  } else {

    qualitySel.value =
      "192 kbps";

    qualityHint.textContent =
      currentFormat === "m4a"
        ? "M4A 음질"
        : "MP3 음질";
  }
}


// ============================================================
// 기기 UI
// ============================================================

function initDeviceUI() {

  const label = {

    ios:
      "iPhone / iPad",

    android:
      "Android",

    pc:
      "PC",

  }[DEVICE];


  deviceLabel.textContent =
    `감지된 기기: ${label}`;


  if (HAS_FS_API) {

    folderHint.textContent =
      "PC · 저장 시 폴더 선택 가능";

    askFolder.checked =
      true;

    askFolder.disabled =
      false;

    pickFolder.textContent =
      "폴더 열기";

    pickFolder.disabled =
      true;

    folderName.textContent =
      "저장할 때 선택";

  } else {

    askFolder.checked =
      false;

    askFolder.disabled =
      true;

    askFolder
      .closest("label")
      .style.opacity = "0.5";

    pickFolder.disabled =
      true;


    if (
      DEVICE === "ios"
    ) {

      folderHint.textContent =
        "Safari 다운로드 위치에 저장";

      folderName.textContent =
        "파일 앱";

    } else if (
      DEVICE === "android"
    ) {

      folderHint.textContent =
        "기본 다운로드 폴더에 저장";

      folderName.textContent =
        "Download";

    } else {

      folderHint.textContent =
        "브라우저 기본 다운로드 폴더";

      folderName.textContent =
        "다운로드 폴더";
    }
  }
}


// ============================================================
// 형식 버튼
// ============================================================

document
  .querySelectorAll(".chip")
  .forEach((button) => {

    button.addEventListener(
      "click",
      () => {

        document
          .querySelectorAll(".chip")
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


        renderQuality();
      }
    );

  });


// ============================================================
// 상태
// ============================================================

function setStatus(
  message,
  kind = "info"
) {

  statusEl.textContent =
    message;


  const colors = {

    info:
      "#4a9eff",

    ok:
      "#4caf50",

    warn:
      "#ff9800",

    err:
      "#e53935",

  };


  statusEl.style.color =
    colors[kind] || "#888";
}


// ============================================================
// 파일명
// ============================================================

function getFilename(
  response
) {

  const fallback = {

    mp3:
      "audio.mp3",

    m4a:
      "audio.m4a",

    mp4:
      "video.mp4",

  }[currentFormat];


  const disposition =
    response.headers.get(
      "content-disposition"
    ) || "";


  const utf8Match =
    disposition.match(
      /filename\*=UTF-8''([^;]+)/i
    );


  if (utf8Match) {

    try {

      return decodeURIComponent(
        utf8Match[1]
      );

    } catch (_) {}
  }


  const normalMatch =
    disposition.match(
      /filename="?([^";]+)"?/i
    );


  if (normalMatch) {

    return normalMatch[1];
  }


  return fallback;
}


// ============================================================
// 다운로드
// ============================================================

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


  const quality =
    qualitySel.value;


  const params =
    new URLSearchParams({

      url,

      format:
        currentFormat,

      quality,

    });


  downloadBtn.disabled =
    true;

  cancelBtn.disabled =
    false;


  progressBar.style.width =
    "0%";


  setStatus(
    "서버 준비 중... 첫 요청은 시간이 걸릴 수 있습니다.",
    "info"
  );


  currentAbort =
    new AbortController();


  try {

    const response =
      await fetch(
        `${API_BASE}/api/download?${params.toString()}`,
        {
          signal:
            currentAbort.signal,
        }
      );


    if (!response.ok) {

      const text =
        await response
          .text()
          .catch(
            () => ""
          );


      throw new Error(
        text ||
        `서버 오류 (${response.status})`
      );
    }


    const filename =
      getFilename(
        response
      );


    const total =
      parseInt(
        response.headers.get(
          "content-length"
        ) || "0",
        10
      );


    const reader =
      response.body.getReader();


    const chunks =
      [];

    let received =
      0;


    while (true) {

      const {
        done,
        value
      } =
        await reader.read();


      if (done) {
        break;
      }


      chunks.push(
        value
      );


      received +=
        value.length;


      if (total) {

        const percent =
          Math.min(
            100,
            (
              received /
              total
            ) * 100
          );


        progressBar.style.width =
          `${percent.toFixed(1)}%`;


        setStatus(
          `다운로드 중... ${percent.toFixed(1)}%`,
          "info"
        );

      } else {

        setStatus(
          `다운로드 중... ${(received / 1024 / 1024).toFixed(1)} MB`,
          "info"
        );
      }
    }


    const mime = {

      mp3:
        "audio/mpeg",

      m4a:
        "audio/mp4",

      mp4:
        "video/mp4",

    }[currentFormat];


    const blob =
      new Blob(
        chunks,
        {
          type: mime
        }
      );


    // ========================================================
    // PC 저장 대화상자
    // ========================================================

    if (
      HAS_FS_API &&
      askFolder.checked
    ) {

      try {

        const handle =
          await window.showSaveFilePicker({

            suggestedName:
              filename,
          });


        const writable =
          await handle.createWritable();


        await writable.write(
          blob
        );


        await writable.close();


        folderName.textContent =
          handle.name;


        progressBar.style.width =
          "100%";


        setStatus(
          "저장 완료!",
          "ok"
        );

      } catch (error) {

        if (
          error.name ===
          "AbortError"
        ) {

          setStatus(
            "저장이 취소되었습니다.",
            "warn"
          );

        } else {

          throw error;
        }
      }

    } else {

      // ======================================================
      // 모바일 / 일반 브라우저 다운로드
      // ======================================================

      const objectUrl =
        URL.createObjectURL(
          blob
        );


      const anchor =
        document.createElement(
          "a"
        );


      anchor.href =
        objectUrl;

      anchor.download =
        filename;


      document.body.appendChild(
        anchor
      );


      anchor.click();


      anchor.remove();


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
        "다운로드 완료! 저장 위치를 확인하세요.",
        "ok"
      );
    }


  } catch (error) {

    if (
      error.name ===
      "AbortError"
    ) {

      setStatus(
        "취소되었습니다.",
        "warn"
      );

    } else {

      console.error(
        error
      );


      setStatus(
        "다운로드 실패. 자동 진단을 시작합니다.",
        "err"
      );


      // ======================================================
      // ★ 다운로드 실패 → 자동 진단
      // ======================================================

      await runDiagnosis(
        url,
        true
      );
    }


  } finally {

    downloadBtn.disabled =
      false;

    cancelBtn.disabled =
      true;

    currentAbort =
      null;
  }
}


// ============================================================
// 취소
// ============================================================

cancelBtn.addEventListener(
  "click",
  () => {

    if (
      currentAbort
    ) {

      currentAbort.abort();

      setStatus(
        "취소 중...",
        "warn"
      );
    }
  }
);


// ============================================================
// 폴더 열기
// ============================================================

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
        "저장 시 이 폴더를 지정할 수 있습니다.",
        "info"
      );

    } catch (error) {

      if (
        error.name !==
        "AbortError"
      ) {

        console.error(
          error
        );
      }
    }
  }
);


// ============================================================
// 진단 버튼
// ============================================================

diagnoseBtn.addEventListener(
  "click",
  () => {

    const url =
      urlInput.value.trim();


    if (!url) {

      setStatus(
        "먼저 YouTube URL을 입력하세요.",
        "warn"
      );

      urlInput.focus();

      return;
    }


    runDiagnosis(
      url,
      false
    );
  }
);


// ============================================================
// 진단 실행
// ============================================================

async function runDiagnosis(
  url,
  automatic
) {

  if (
    diagnosisRunning
  ) {
    return;
  }


  diagnosisRunning =
    true;


  diagnoseBtn.disabled =
    true;


  diagnosticResult.classList.remove(
    "hidden"
  );


  diagnosticSummary.innerHTML =
    `<div class="diagnostic-loading">
      서버 진단 중입니다...
    </div>`;


  diagnosticItems.innerHTML =
    "";


  diagnosticLog.textContent =
    "";


  if (automatic) {

    setStatus(
      "다운로드 실패 → YouTube 연결 진단 중...",
      "warn"
    );

  } else {

    setStatus(
      "YouTube 연결 진단 중...",
      "info"
    );
  }


  try {

    const response =
      await fetch(
        `${API_BASE}/api/diagnose?url=${encodeURIComponent(url)}`,
        {
          cache:
            "no-store",
        }
      );


    const data =
      await response.json();


    if (!response.ok) {

      throw new Error(
        data.detail ||
        `진단 서버 오류 (${response.status})`
      );
    }


    renderDiagnosis(
      data
    );


    setStatus(
      "진단 완료",
      "ok"
    );

  } catch (error) {

    console.error(
      error
    );


    diagnosticSummary.innerHTML =
      `
      <div class="diagnostic-error">
        진단 서버에 연결하지 못했습니다.
      </div>
      `;


    diagnosticLog.textContent =
      error.message;


    setStatus(
      "진단 실패: " +
      error.message,
      "err"
    );

  } finally {

    diagnosisRunning =
      false;

    diagnoseBtn.disabled =
      false;
  }
}


// ============================================================
// 진단 결과 표시
// ============================================================

function renderDiagnosis(
  data
) {

  const diagnosis =
    data.diagnosis || {};


  const code =
    diagnosis.code ||
    "UNKNOWN";


  const message =
    diagnosis.message ||
    "진단 결과가 없습니다.";


  const isGood =
    data.player_response &&
    data.player_response.success;


  let summaryClass =
    "diagnostic-summary";


  if (
    code === "YOUTUBE_429" ||
    code === "YOUTUBE_BOT_CHECK"
  ) {

    summaryClass +=
      " warning";

  } else if (
    code === "UNKNOWN"
  ) {

    summaryClass +=
      " warning";

  } else if (
    isGood
  ) {

    summaryClass +=
      " success";

  } else {

    summaryClass +=
      " danger";
  }


  diagnosticSummary.className =
    summaryClass;


  diagnosticSummary.innerHTML =

    `<strong>${escapeHtml(message)}</strong>
     <span class="diagnostic-code">
       ${escapeHtml(code)}
     </span>`;


  const items =
    [];


  const environment =
    data.environment || {};


  // yt-dlp

  items.push(
    diagnosticItem(
      "yt-dlp",
      environment.yt_dlp ||
        "확인 실패",
      Boolean(
        environment.yt_dlp
      )
    )
  );


  // Deno

  items.push(
    diagnosticItem(
      "JS Runtime",
      environment.deno?.available
        ? (
            environment.deno.version ||
            "Deno"
          )
        : "없음",
      Boolean(
        environment.deno?.available
      )
    )
  );


  // FFmpeg

  items.push(
    diagnosticItem(
      "FFmpeg",
      environment.ffmpeg?.available
        ? (
            environment.ffmpeg.version ||
            "정상"
          )
        : "없음",
      Boolean(
        environment.ffmpeg?.available
      )
    )
  );


  // Cookie

  const cookies =
    environment.cookies ||
    {};


  items.push(
    diagnosticItem(
      "Cookie",
      !cookies.configured
        ? "미설정"
        : cookies.valid_structure
          ? `정상 구조 (${cookies.cookie_count}개)`
          : "형식 확인 필요",
      Boolean(
        cookies.configured &&
        cookies.valid_structure
      )
    )
  );


  // BgUtils

  const bgutil =
    environment.bgutil ||
    {};


  items.push(
    diagnosticItem(
      "BgUtils / PO Token",
      bgutil.tcp
        ? "연결 정상"
        : "연결 실패",
      Boolean(
        bgutil.tcp
      )
    )
  );


  // YouTube HTTP

  const http =
    data.youtube_http ||
    {};


  let httpText =
    "확인 실패";


  if (
    http.status
  ) {

    httpText =
      `HTTP ${http.status}`;
  }


  items.push(
    diagnosticItem(
      "YouTube 연결",
      httpText,
      http.status === 200
    )
  );


  // Player Response

  const player =
    data.player_response ||
    {};


  items.push(
    diagnosticItem(
      "Player Response",
      player.success
        ? `성공 (${player.format_count || 0} formats)`
        : "실패",
      Boolean(
        player.success
      )
    )
  );


  // Client 결과

  const clients =
    data.clients || [];


  if (
    clients.length
  ) {

    clients.forEach(
      (client) => {

        items.push(
          diagnosticItem(
            client.client,
            client.success
              ? "성공"
              : "실패",
            Boolean(
              client.success
            )
          )
        );
      }
    );
  }


  diagnosticItems.innerHTML =
    items.join("");


  // 상세 로그

  const logObject = {

    diagnosis:
      data.diagnosis,

    environment:
      data.environment,

    youtube_http:
      data.youtube_http,

    player_response:
      data.player_response,

    clients:
      data.clients,

  };


  diagnosticLog.textContent =
    JSON.stringify(
      logObject,
      null,
      2
    );
}


// ============================================================
// 진단 한 줄
// ============================================================

function diagnosticItem(
  name,
  value,
  success
) {

  const className =
    success
      ? "diagnostic-ok"
      : "diagnostic-fail";


  const symbol =
    success
      ? "✓"
      : "⚠";


  return `

    <div class="diagnostic-item">

      <span class="diagnostic-item-name">
        ${escapeHtml(name)}
      </span>

      <span class="${className}">

        <b>${symbol}</b>

        ${escapeHtml(
          String(value)
        )}

      </span>

    </div>

  `;
}


// ============================================================
// HTML escape
// ============================================================

function escapeHtml(
  value
) {

  return String(
    value
  )

    .replace(
      /&/g,
      "&amp;"
    )

    .replace(
      /</g,
      "&lt;"
    )

    .replace(
      />/g,
      "&gt;"
    )

    .replace(
      /"/g,
      "&quot;"
    )

    .replace(
      /'/g,
      "&#039;"
    );
}


// ============================================================
// 초기화
// ============================================================

initDeviceUI();

renderQuality();


// URL이 있으면 자동 진단 가능하도록 유지
urlInput.focus();


// ============================================================
// Service Worker
// ============================================================

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
