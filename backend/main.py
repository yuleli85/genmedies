"""
GenVoid — AI 视频生成平台后端入口
"""
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from pathlib import Path
from routers import upload, scenes, images, videos, projects, ppt, drama, md2ppt, pdf2word, script2video

app = FastAPI(title="GenVoid API", version="1.0.0")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=False,
    allow_methods=["*"],
    allow_headers=["*"],
)

# 静态文件服务 — 前端直接访问生成的图片/视频
uploads_dir = Path("uploads")
uploads_dir.mkdir(exist_ok=True)
app.mount("/uploads", StaticFiles(directory="uploads"), name="uploads")

app.include_router(upload.router)
app.include_router(scenes.router)
app.include_router(images.router)
app.include_router(videos.router)
app.include_router(projects.router)
app.include_router(ppt.router)
app.include_router(drama.router)
app.include_router(md2ppt.router)
app.include_router(pdf2word.router)
app.include_router(script2video.router)


@app.get("/api/health")
async def health():
    return {"status": "ok", "service": "GenVoid"}
