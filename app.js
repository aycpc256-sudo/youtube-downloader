// ======================================================
// Render 백엔드 주소
// ======================================================

const API_BASE =
  "https://youtube-downloader-onww.onrender.com";


// ======================================================
// DOM
// ======================================================

const $ = (s) => document.querySelector(s);

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

const diagnosticCard =
  $("#diagnostic-card");

const diagnoseBtn =
  $("#diagnose-btn");

const diagnosticResult =
  $("#diagnostic-result");


// ======================================================
// 상태
// ======================================================

let currentFormat = "mp3";

let currentAbort = null;

let currentInfo = null;

let mp4Qualities = [
  "최고 화질"
];


// ======================================================
// 기기
// ======================================================

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


// ======================================================
// 품질
// ======================================================

const MP3_QUALITY = [
  "320 kbps",
  "256 kbps",
  "192 kbps",
  "128 kbps",
  "96 kbps"
];

const M4A_QUALITY = [
  "기본"
];


// ======================================================
// 상태 표시
// ======================================================

function setStatus(
  msg,
  kind = "info"
) {

  if (!statusEl) {
    return;
  }

  statusEl.textContent =
    msg;

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
// HTML escape
// ======================================================

function escapeHtml(value) {

  if (
    value === null ||
    value === undefined
  ) {
    return "";
  }

  if (
    typeof value === "object"
  ) {
    try {

      return escapeHtml(
        JSON.stringify(
          value,
          null,
          2
        )
      );

    } catch (_) {

      return escapeHtml(
        String(value)
      );
    }
  }

  return String(value)
    .replaceAll(
      "&",
      "&amp;"
    )
    .replaceAll(
      "<",
      "&lt;"
    )
    .replaceAll(
      ">",
      "&gt;"
    )
    .replaceAll(
      '"',
      "&quot;"
    )
    .replaceAll(
      "'",
      "&#039;"
    );
}


// ======================================================
// 객체 → 사람이 읽는 문자열
// ======================================================

function displayValue(value) {

  if (
    value === null ||
    value === undefined
  ) {
    return "-";
  }

  if (
    typeof value === "object"
  ) {

    try {

      return JSON.stringify(
        value,
        null,
        2
      );

    } catch (_) {

      return String(value);
    }
  }

  return String(value);
}


// ======================================================
// MP4 화질 만들기
// ======================================================

function buildMp4Qualities(
  formats
) {

  if (
    !Array.isArray(formats)
  ) {

    return [
      "최고 화질"
    ];
  }

  const heights = [
    ...new Set(
      formats
        .filter((f) => {

          if (!f) {
            return false;
          }

          const height =
            Number(f.height);

          if (
            !height ||
            height <= 0
          ) {
            return false;
          }

          const ext =
            String(
              f.ext || ""
            ).toLowerCase();

          const videoExt =
            String(
              f.video_ext || ""
            ).toLowerCase();

          return (
            ext === "mp4" ||
            videoExt === "mp4"
          );
        })
        .map(
          (f) =>
            Number(f.height)
        )
    )
  ];

  heights.sort(
    (a, b) => b - a
  );

  if (!heights.length) {

    return [
      "최고 화질"
    ];
  }

  return heights.map(
    (height, index) => {

      if (index === 0) {
        return `${height}p (기본)`;
      }

      return `${height}p`;
    }
  );
}


// ======================================================
// 품질 UI
// ======================================================

function renderQuality() {

  if (!qualitySel) {
    return;
  }

  let options = [];

  if (
    currentFormat === "mp3"
  ) {

    options =
      MP3_QUALITY;

    qualityHint.textContent =
      "MP3 음질";
  }

  else if (
    currentFormat === "m4a"
  ) {

    options =
      M4A_QUALITY;

    qualityHint.textContent =
      "YouTube 기본 오디오";
  }

  else {

    options =
      mp4Qualities;

    qualityHint.textContent =
      "YouTube 제공 화질";
  }


  qualitySel.innerHTML =
    options
      .map(
        (value) =>
          `<option value="${escapeHtml(value)}">${escapeHtml(value)}</option>`
      )
      .join("");


  if (
    currentFormat === "mp3"
  ) {

    qualitySel.value =
      "192 kbps";

  } else {

    qualitySel.value =
      options[0] || "";
  }
}


// ======================================================
// 영상 정보
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


  const text =
    await response.text();


  let data;

  try {

    data =
      JSON.parse(text);

  } catch (_) {

    throw new Error(
      text ||
      `영상 정보 오류 (${response.status})`
    );
  }


  if (!response.ok) {

    throw new Error(
      data.detail ||
      data.error ||
      text ||
      `영상 정보 오류 (${response.status})`
    );
  }


  currentInfo =
    data;


  mp4Qualities =
    buildMp4Qualities(
      data.formats
    );


  if (
    currentFormat === "mp4"
  ) {

    renderQuality();
  }


  return data;
}


// ======================================================
// URL 변경
// ======================================================

urlInput.addEventListener(
  "change",
  async () => {

    try {

      await loadVideoInfo();

      setStatus(
        "영상 정보를 확인했습니다.",
        "ok"
      );

    } catch (err) {

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


  if (deviceLabel) {

    deviceLabel.textContent =
      `감지된 기기: ${label}`;
  }


  if (
    HAS_FS_API
  ) {

    folderHint.textContent =
      "PC · 저장 시 파일 위치 선택 가능";

    askFolder.checked =
      true;

    askFolder.disabled =
      false;

    pickFolder.textContent =
      "폴더 열기";

    pickFolder.disabled =
      false;

    folderName.textContent =
      "저장할 때 선택";

  } else {

    askFolder.checked =
      false;

    askFolder.disabled =
      true;

    pickFolder.disabled =
      true;


    if (
      DEVICE === "ios"
    ) {

      folderHint.textContent =
        "Safari 다운로드 위치에 저장";

      folderName.textContent =
        "파일 앱";

    }

    else if (
      DEVICE === "android"
    ) {

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
  .forEach(
    (btn) => {

      btn.addEventListener(
        "click",
        async () => {

          document
            .querySelectorAll(".chip")
            .forEach(
              (b) =>
                b.classList.remove(
                  "active"
                )
            );


          btn.classList.add(
            "active"
          );


          currentFormat =
            btn.dataset.format;


          if (
            currentFormat === "mp4" &&
            urlInput.value.trim()
          ) {

            try {

              await loadVideoInfo();

            } catch (err) {

              console.error(err);

              setStatus(
                "MP4 화질 조회 실패: " +
                err.message,
                "warn"
              );
            }
          }


          renderQuality();
        }
      );
    }
  );


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


  // MP4는 실제 화질을 먼저 조회
  if (
    currentFormat === "mp4"
  ) {

    try {

      await loadVideoInfo();

    } catch (err) {

      console.error(err);

      setStatus(
        "영상 정보 조회 실패: " +
        err.message,
        "warn"
      );

      return;
    }
  }


  const quality =
    qualitySel.value;


  const params =
    new URLSearchParams({
      url,
      format:
        currentFormat,
      quality
    });


  downloadBtn.disabled =
    true;

  cancelBtn.disabled =
    false;


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
          .catch(
            () => ""
          );


      let message =
        text ||
        `서버 오류 (${response.status})`;


      try {

        const data =
          JSON.parse(text);

        message =
          data.detail ||
          data.error ||
          message;

      } catch (_) {}


      throw new Error(
        message
      );
    }


    // ----------------------------------------------------
    // 파일명
    // ----------------------------------------------------

    let filename =
      currentFormat === "mp3"
        ? "audio.mp3"
        : currentFormat === "m4a"
          ? "audio.m4a"
          : "video.mp4";


    const cd =
      response.headers.get(
        "content-disposition"
      ) || "";


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

      } catch (_) {}
    }


    // ----------------------------------------------------
    // 파일 다운로드
    // ----------------------------------------------------

    if (!response.body) {

      throw new Error(
        "서버가 파일 스트림을 반환하지 않았습니다."
      );
    }


    const total =
      parseInt(
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

        const pct =
          Math.min(
            100,
            (received / total) * 100
          );


        progressBar.style.width =
          pct.toFixed(1) +
          "%";


        setStatus(
          `다운로드 중... ${pct.toFixed(1)}%`,
          "info"
        );

      } else {

        setStatus(
          `다운로드 중... ${(received / 1024 / 1024).toFixed(1)} MB`,
          "info"
        );
      }
    }


    // ----------------------------------------------------
    // MIME
    // ----------------------------------------------------

    const mime =
      currentFormat === "mp3"
        ? "audio/mpeg"
        : currentFormat === "m4a"
          ? "audio/mp4"
          : "video/mp4";


    const blob =
      new Blob(
        chunks,
        {
          type: mime
        }
      );


    // ----------------------------------------------------
    // PC 저장 위치 선택
    // ----------------------------------------------------

    if (
      HAS_FS_API &&
      askFolder.checked
    ) {

      try {

        const handle =
          await window.showSaveFilePicker({
            suggestedName:
              filename
          });


        const writable =
          await handle.createWritable();


        await writable.write(
          blob
        );


        await writable.close();


        folderName.textContent =
          handle.name;


        setStatus(
          "저장 완료!",
          "ok"
        );


      } catch (err) {

        if (
          err.name ===
          "AbortError"
        ) {

          setStatus(
            "저장이 취소되었습니다.",
            "warn"
          );

        } else {

          throw err;
        }
      }


    } else {

      // --------------------------------------------------
      // 모바일 / 기본 다운로드
      // --------------------------------------------------

      const objectUrl =
        URL.createObjectURL(
          blob
        );


      const a =
        document.createElement(
          "a"
        );


      a.href =
        objectUrl;

      a.download =
        filename;


      document.body.appendChild(
        a
      );


      a.click();


      a.remove();


      setTimeout(
        () =>
          URL.revokeObjectURL(
            objectUrl
          ),
        30000
      );


      setStatus(
        "다운로드 완료!",
        "ok"
      );
    }


  } catch (err) {

    if (
      err.name ===
      "AbortError"
    ) {

      setStatus(
        "취소되었습니다.",
        "warn"
      );

    } else {

      console.error(err);


      setStatus(
        "다운로드 실패: " +
        err.message,
        "err"
      );


      // 실패 시 자동 진단
      if (
        diagnosticCard
      ) {

        diagnosticCard.hidden =
          false;
      }


      diagnoseVideo();
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


    } catch (err) {

      if (
        err.name !==
        "AbortError"
      ) {

        console.error(err);
      }
    }
  }
);


// ======================================================
// 진단 버튼
// ======================================================

diagnoseBtn.addEventListener(
  "click",
  diagnoseVideo
);


// ======================================================
// YouTube 진단
// ======================================================

async function diagnoseVideo() {

  const url =
    urlInput.value.trim();


  if (!url) {

    diagnosticResult.innerHTML =
      `
      <div class="diag-summary">
        YouTube URL을 먼저 입력하세요.
      </div>
      `;

    return;
  }


  diagnosticCard.hidden =
    false;


  diagnoseBtn.disabled =
    true;


  diagnosticResult.innerHTML =
    `
    <div class="diag-summary">
      YouTube 연결 상태를 확인하는 중...
    </div>
    `;


  try {

    const response =
      await fetch(
        `${API_BASE}/api/diagnose?url=${encodeURIComponent(url)}`
      );


    const text =
      await response.text();


    let data;

    try {

      data =
        JSON.parse(text);

    } catch (_) {

      throw new Error(
        text ||
        `진단 서버 오류 (${response.status})`
      );
    }


    if (!response.ok) {

      throw new Error(
        data.detail ||
        data.error ||
        `진단 서버 오류 (${response.status})`
      );
    }


    renderDiagnosis(
      data
    );


  } catch (err) {

    diagnosticResult.innerHTML =
      `
      <div class="diag-summary diag-error">
        진단 요청 실패
        <br>
        ${escapeHtml(
          err.message
        )}
      </div>
      `;

  } finally {

    diagnoseBtn.disabled =
      false;
  }
}


// ======================================================
// 진단 결과 표시
// ======================================================

function renderDiagnosis(
  data
) {

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


  const yt =
    data.yt_dlp || {};


  const youtube =
    data.youtube_http || {};


  const bgutil =
    data.bgutil || {};


  const ffmpeg =
    data.ffmpeg || {};


  let html =
    `
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
            displayValue(
              yt
            )
          )}
        </span>
      </div>


      <div class="diag-row">
        <span class="diag-label">
          YouTube 연결
        </span>

        <span class="diag-value">
          ${escapeHtml(
            displayValue(
              youtube
            )
          )}
        </span>
      </div>


      <div class="diag-row">
        <span class="diag-label">
          BgUtils / PO Token
        </span>

        <span class="diag-value">
          ${escapeHtml(
            displayValue(
              bgutil
            )
          )}
        </span>
      </div>


      <div class="diag-row">
        <span class="diag-label">
          FFmpeg
        </span>

        <span class="diag-value">
          ${escapeHtml(
            displayValue(
              ffmpeg
            )
          )}
        </span>
      </div>


      <div class="diag-row">
        <span class="diag-label">
          Cookies
        </span>

        <span class="diag-value">
          ${escapeHtml(
            displayValue(
              data.cookies
            )
          )}
        </span>
      </div>

    </div>
    `;


  // ====================================================
  // Player Client
  // ====================================================

  if (
    Array.isArray(
      data.clients
    )
  ) {

    html +=
      `
      <div class="diag-summary">

        <div class="diag-title">
          Player Client 비교
        </div>
      `;


    for (
      const client
      of data.clients
    ) {

      const ok =
        client.success === true ||
        client.ok === true;


      const error =
        client.error || "";


      html +=
        `
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

            ${
              ok
                ? "성공"
                : "실패"
            }

          </span>

        </div>
        `;


      if (
        !ok &&
        error
      ) {

        html +=
          `
          <div
            class="diag-row"
            style="
              display:block;
              padding-top:0;
            "
          >

            <span
              class="diag-value diag-error"
              style="
                display:block;
                font-size:12px;
                white-space:pre-wrap;
                word-break:break-word;
              "
            >
              ${escapeHtml(error)}
            </span>

          </div>
          `;
      }
    }


    html +=
      `
      </div>
      `;
  }


  // ====================================================
  // 상세 정보
  // ====================================================

  const raw =
    data.raw ||
    data.error ||
    data.details ||
    data.logs ||
    "";


  if (raw) {

    const rawText =
      typeof raw === "string"
        ? raw
        : JSON.stringify(
            raw,
            null,
            2
          );


    html +=
      `
      <details class="diag-details">

        <summary>
          상세 진단 정보
        </summary>

        <pre class="diag-pre">${escapeHtml(
          rawText
        )}</pre>

      </details>
      `;
  }


  diagnosticResult.innerHTML =
    html;
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
    .catch(
      () => {}
    );
}
