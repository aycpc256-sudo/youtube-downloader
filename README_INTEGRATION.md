# YouTube Downloader - Diagnostic Page Integration

현재 Repository의 백엔드에는 이미 `/api/diagnose`와 `/api/health`가 구현되어 있습니다.

## 추가 파일

- `diagnostic.html` — 별도 서버 진단 페이지
- `diagnostic.js` — 진단 페이지 전용 JavaScript

## 수정 파일

- `index.html` — 상단에 `Downloader / 서버 진단` 두 페이지 메뉴 추가

## 기존 파일

- `app.js` — 수정하지 않음
- `backend/server.py` — 수정하지 않음

## 설치

이 ZIP의 파일을 GitHub Repository 루트에 복사/업로드합니다.

```text
youtube-downloader/
├── backend/
├── app.js
├── index.html          ← 교체
├── diagnostic.html     ← 추가
├── diagnostic.js       ← 추가
├── styles.css
└── ...
```

## 동작

- `index.html` → 기존 Downloader
- `diagnostic.html` → Render / YouTube 진단
- 진단 API → 기존 `/api/diagnose`
- 서버 상태 → 기존 `/api/health`

API 주소는 현재 Repository의 `app.js`와 동일하게:

`https://youtube-downloader-onww.onrender.com`

으로 설정되어 있습니다.

Render 주소가 변경되면 `diagnostic.js`의 `API_BASE`도 변경해야 합니다.
