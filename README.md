# YouTube Downloader — GitHub Pages + Render

개인용 MP3/MP4 다운로드 웹앱입니다.

## 구성
- `frontend/` → GitHub Pages
- `backend/` → Render Docker Web Service
- backend → yt-dlp + FFmpeg + Deno

## 설정
1. GitHub 저장소에 프로젝트 업로드.
2. Render에서 `render.yaml` 또는 Docker Web Service로 backend 배포.
3. Render 주소를 `frontend/app.js`의 `API_BASE`에 입력.
4. `backend/server.py`의 `YOUR-GITHUB-ID.github.io`를 실제 Pages 주소로 변경.
5. GitHub Settings → Pages → Deploy from branch → `main` / `/frontend`.

GitHub Pages는 정적 사이트만 실행하므로 Python/yt-dlp/FFmpeg는 Render에서 실행합니다.

## 품질
MP3: 320/256/192/128/96 kbps
MP4: 최고 화질/2160p/1440p/1080p/720p/480p/360p

## 참고
Render Free Web Service는 유휴 15분 후 sleep될 수 있으며 무료 자원/대역폭 제한이 있습니다.
YouTube 정책 및 저작권을 준수하고 다운로드 권한이 있는 콘텐츠만 사용하세요.
