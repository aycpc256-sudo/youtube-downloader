import re,shutil,tempfile
from pathlib import Path
from urllib.parse import urlparse
import yt_dlp
from fastapi import FastAPI,HTTPException,Query
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from starlette.background import BackgroundTask
app=FastAPI(title="Personal YouTube Downloader API")
ALLOWED_ORIGINS=["https://YOUR-GITHUB-ID.github.io","http://localhost:8000","http://127.0.0.1:8000"]
app.add_middleware(CORSMiddleware,allow_origins=ALLOWED_ORIGINS,allow_methods=["GET","OPTIONS"],allow_headers=["*"])
HOSTS={"youtube.com","www.youtube.com","m.youtube.com","youtu.be"}
def validate(u):
 p=urlparse(u)
 if p.scheme not in {"http","https"} or (p.hostname or "").lower() not in HOSTS: raise HTTPException(400,"YouTube 주소만 사용할 수 있습니다.")
 return u
def safe(n): return (re.sub(r'[<>:"/\\|?*\x00-\x1f]','_',n).strip(" .") or "download")[:180]
@app.get("/api/health")
def health(): return {"ok":True,"service":"youtube-downloader"}
@app.get("/api/download")
def download(url:str=Query(...,min_length=10),format:str=Query("mp3",pattern="^(mp3|mp4)$"),quality:str=Query("192")):
 validate(url); tmp=tempfile.mkdtemp(prefix="ytdl_")
 try:
  base={"outtmpl":str(Path(tmp)/"%(title)s.%(ext)s"),"noplaylist":True,"quiet":True,"no_warnings":True,"retries":3,"fragment_retries":3,"continuedl":True}
  if format=="mp3":
   q=re.sub(r"\D","",quality) or "192";q=q if q in {"320","256","192","128","96"} else "192";opts={**base,"format":"bestaudio/best","postprocessors":[{"key":"FFmpegExtractAudio","preferredcodec":"mp3","preferredquality":q}]};media="audio/mpeg";exts=(".mp3",)
  else:
   if quality=="best": fmt="bestvideo+bestaudio/best"
   else:
    h=re.sub(r"\D","",quality) or "1080";fmt=f"bestvideo[height<={h}][ext=mp4]+bestaudio[ext=m4a]/best[height<={h}][ext=mp4]/best[height<={h}]/best"
   opts={**base,"format":fmt,"merge_output_format":"mp4"};media="video/mp4";exts=(".mp4",)
  with yt_dlp.YoutubeDL(opts) as y: y.download([url])
  fs=[p for p in Path(tmp).iterdir() if p.is_file() and p.stat().st_size>0 and p.suffix.lower() in exts]
  if not fs: raise HTTPException(500,"다운로드된 파일을 찾지 못했습니다.")
  p=max(fs,key=lambda x:x.stat().st_size)
  return FileResponse(p,media_type=media,filename=safe(p.name),background=BackgroundTask(shutil.rmtree,tmp,ignore_errors=True))
 except HTTPException: shutil.rmtree(tmp,ignore_errors=True);raise
 except Exception as e: shutil.rmtree(tmp,ignore_errors=True);raise HTTPException(500,f"다운로드 실패: {e}")
