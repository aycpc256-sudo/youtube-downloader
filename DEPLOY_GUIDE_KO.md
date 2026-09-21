# YouTube Downloader — GitHub Pages + Render 배포 가이드

## 프로젝트 구조

GitHub Pages를 `main` 브랜치의 `/(root)`로 설정할 수 있도록 웹 화면 파일을 저장소 최상위에 배치했습니다.

```text
youtube-downloader/
├─ index.html
├─ styles.css
├─ app.js
├─ manifest.json
├─ service-worker.js
├─ .nojekyll
├─ backend/
│  ├─ server.py
│  ├─ requirements.txt
│  └─ Dockerfile
├─ render.yaml
├─ .gitignore
└─ README.md
```

## 1. GitHub에 올리기

1. GitHub 로그인
2. `New repository`
3. Repository name: `youtube-downloader`
4. `Public` 선택
5. `Create repository`
6. ZIP의 **내용물 전체**를 저장소 최상위에 업로드
7. `Commit changes`

## 2. Render 연결

1. Render 로그인
2. `New` → `Web Service`
3. GitHub 연결
4. `youtube-downloader` 저장소 선택
5. 다음 값 확인
   - Branch: `main`
   - Language: `Docker`
   - Dockerfile Path: `./backend/Dockerfile`
   - Docker Context: `./backend`
   - Plan: `Free`
6. `Create Web Service`

배포가 끝나면 Render가 `https://...onrender.com` 주소를 제공합니다.

## 3. Render 주소 입력

GitHub 저장소의 `app.js`에서:

```js
const API_BASE = "https://YOUR-BACKEND.onrender.com";
```

를 실제 Render 주소로 바꾸고 `Commit changes` 합니다.

## 4. GitHub Pages 주소를 backend에 허용

`backend/server.py`에서:

```python
ALLOWED_ORIGINS = [
    "https://YOUR-GITHUB-ID.github.io",
    ...
]
```

를 실제 GitHub 사용자 주소로 바꿉니다. 예:

```python
ALLOWED_ORIGINS = [
    "https://abc123.github.io",
    "http://localhost:8000",
    "http://127.0.0.1:8000",
]
```

저장 후 `Commit changes` 합니다.

## 5. GitHub Pages 켜기

1. 저장소 → `Settings`
2. 왼쪽 `Pages`
3. `Build and deployment`
4. `Source`: `Deploy from a branch`
5. `Branch`: `main`
6. 폴더: `/(root)`
7. `Save`

프로젝트 이름이 `youtube-downloader`라면 주소는:

```text
https://GITHUB-ID.github.io/youtube-downloader/
```

입니다.

## 6. 테스트

1. GitHub Pages 주소 접속
2. YouTube URL 입력
3. MP4 선택
4. 720p 또는 1080p 선택
5. `Download`
6. 다운로드 확인

먼저 backend가 살아 있는지 확인하려면:

```text
https://YOUR-BACKEND.onrender.com/api/health
```

에 접속합니다.

## 주의

- GitHub Pages는 정적 파일을 제공하고 Python 서버는 실행하지 않습니다.
- 실제 다운로드 처리는 Render의 FastAPI 서버가 담당합니다.
- Render Free 서비스는 유휴 상태에서 절전될 수 있어 첫 요청이 느릴 수 있습니다.
- YouTube 다운로드는 본인이 소유하거나 다운로드 권한이 있는 콘텐츠에 사용하세요.
