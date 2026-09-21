"""
上传路由 — 处理人像图和文章上传
"""
import uuid
import io
import aiofiles
from fastapi import APIRouter, File, Form, UploadFile, HTTPException
from pathlib import Path
from PIL import Image
from config import settings

router = APIRouter(prefix="/api/upload", tags=["upload"])

PORTRAIT_DIR = Path(settings.upload_dir) / "portraits"
ARTICLE_DIR = Path(settings.upload_dir) / "articles"
CHARACTER_REF_DIR = Path(settings.upload_dir) / "character_refs"

for d in (PORTRAIT_DIR, ARTICLE_DIR, CHARACTER_REF_DIR):
    d.mkdir(parents=True, exist_ok=True)

ALLOWED_IMAGE = {".jpg", ".jpeg", ".png", ".webp"}
ALLOWED_TEXT = {".txt", ".md"}


@router.post("/portrait")
async def upload_portrait(file: UploadFile = File(...)):
    suffix = Path(file.filename).suffix.lower()
    if suffix not in ALLOWED_IMAGE:
        raise HTTPException(400, f"不支持的图片格式: {suffix}，支持 {ALLOWED_IMAGE}")

    file_id = str(uuid.uuid4())
    save_path = PORTRAIT_DIR / f"{file_id}{suffix}"

    async with aiofiles.open(save_path, "wb") as f:
        content = await file.read()
        if len(content) > settings.max_file_size_mb * 1024 * 1024:
            raise HTTPException(400, f"文件过大，最大 {settings.max_file_size_mb}MB")
        await f.write(content)

    return {"file_id": file_id, "filename": file.filename, "path": str(save_path)}


@router.post("/article")
async def upload_article(file: UploadFile = File(...)):
    suffix = Path(file.filename).suffix.lower()
    if suffix not in ALLOWED_TEXT:
        raise HTTPException(400, f"不支持的文本格式，支持 .txt / .md")

    file_id = str(uuid.uuid4())
    save_path = ARTICLE_DIR / f"{file_id}{suffix}"

    async with aiofiles.open(save_path, "wb") as f:
        content = await file.read()
        await f.write(content)

    return {
        "file_id": file_id,
        "filename": file.filename,
        "path": str(save_path),
        "preview": content.decode("utf-8", errors="replace")[:500],
    }


@router.post("/scene-image")
async def upload_scene_image(
    project_id: str = Form(...),
    scene_id: int = Form(...),
    file: UploadFile = File(...),
):
    """替换指定分镜的图片，转为 JPEG 并压缩到 2MB 以内"""
    suffix = Path(file.filename).suffix.lower()
    if suffix not in ALLOWED_IMAGE:
        raise HTTPException(400, f"不支持的图片格式: {suffix}")

    content = await file.read()
    if len(content) > settings.max_file_size_mb * 1024 * 1024:
        raise HTTPException(400, f"文件过大，最大 {settings.max_file_size_mb}MB")

    project_dir = Path(settings.upload_dir) / "images" / project_id
    project_dir.mkdir(parents=True, exist_ok=True)
    out_path = project_dir / f"scene_{scene_id:03d}.jpg"

    img = Image.open(io.BytesIO(content)).convert("RGB")
    quality = 85
    while True:
        buf = io.BytesIO()
        img.save(buf, format="JPEG", quality=quality)
        if buf.tell() <= 2 * 1024 * 1024 or quality <= 40:
            break
        quality -= 10
    out_path.write_bytes(buf.getvalue())

    return {
        "scene_id": scene_id,
        "image_path": str(out_path),
        "image_url": f"/uploads/images/{project_id}/scene_{scene_id:03d}.jpg",
    }


@router.post("/character-ref")
async def upload_character_ref(
    project_id: str = Form(...),
    character_name: str = Form(...),
    file: UploadFile = File(...),
):
    """上传角色参考图，用于保持生成图片中人物一致性"""
    suffix = Path(file.filename).suffix.lower()
    if suffix not in ALLOWED_IMAGE:
        raise HTTPException(400, f"不支持的图片格式: {suffix}")

    content = await file.read()
    if len(content) > settings.max_file_size_mb * 1024 * 1024:
        raise HTTPException(400, f"文件过大，最大 {settings.max_file_size_mb}MB")

    ref_dir = CHARACTER_REF_DIR / project_id
    ref_dir.mkdir(parents=True, exist_ok=True)

    safe_name = character_name.replace("/", "_").replace("\\", "_")
    out_path = ref_dir / f"{safe_name}.png"

    img = Image.open(io.BytesIO(content)).convert("RGB")
    img.save(out_path, format="PNG")

    return {
        "character_name": character_name,
        "ref_path": str(out_path),
        "ref_url": f"/uploads/character_refs/{project_id}/{safe_name}.png",
    }


INTRO_DIR = Path(settings.upload_dir) / "intro"
INTRO_DIR.mkdir(parents=True, exist_ok=True)

ALLOWED_VIDEO = {".mp4", ".mov", ".avi", ".mkv", ".webm"}


@router.post("/video")
async def upload_video(
    project_id: str = Form(...),
    file: UploadFile = File(...),
):
    """上传视频文件用于合成"""
    suffix = Path(file.filename).suffix.lower()
    if suffix not in ALLOWED_VIDEO:
        raise HTTPException(400, f"不支持的视频格式: {suffix}，支持 {ALLOWED_VIDEO}")

    content = await file.read()
    if len(content) > 500 * 1024 * 1024:
        raise HTTPException(400, "文件过大，最大 500MB")

    video_dir = Path(settings.upload_dir) / "videos" / project_id
    video_dir.mkdir(parents=True, exist_ok=True)

    file_id = uuid.uuid4().hex[:8]
    out_path = video_dir / f"{file_id}{suffix}"

    async with aiofiles.open(out_path, "wb") as f:
        await f.write(content)

    return {
        "video_path": str(out_path),
        "video_url": f"/uploads/videos/{project_id}/{file_id}{suffix}",
        "filename": file.filename,
    }


@router.post("/intro-image")
async def upload_intro_image(
    project_id: str = Form(...),
    file: UploadFile = File(...),
):
    """上传片头图片"""
    suffix = Path(file.filename).suffix.lower()
    if suffix not in ALLOWED_IMAGE:
        raise HTTPException(400, f"不支持的图片格式: {suffix}")

    content = await file.read()
    if len(content) > settings.max_file_size_mb * 1024 * 1024:
        raise HTTPException(400, f"文件过大，最大 {settings.max_file_size_mb}MB")

    proj_dir = INTRO_DIR / project_id
    proj_dir.mkdir(parents=True, exist_ok=True)

    file_id = uuid.uuid4().hex[:8]
    out_path = proj_dir / f"intro_{file_id}.jpg"

    img = Image.open(io.BytesIO(content)).convert("RGB")
    img.save(out_path, format="JPEG", quality=90)

    return {
        "image_path": str(out_path),
        "image_url": f"/uploads/intro/{project_id}/intro_{file_id}.jpg",
    }


@router.post("/script-image")
async def upload_script_image(
    project_id: str = Form(...),
    scene_id: int = Form(...),
    position: str = Form(...),  # "start" or "end"
    file: UploadFile = File(...),
):
    """替换脚本转视频的首帧或尾帧图片"""
    suffix = Path(file.filename).suffix.lower()
    if suffix not in ALLOWED_IMAGE:
        raise HTTPException(400, f"不支持的图片格式: {suffix}")

    content = await file.read()
    if len(content) > settings.max_file_size_mb * 1024 * 1024:
        raise HTTPException(400, f"文件过大，最大 {settings.max_file_size_mb}MB")

    script_dir = Path(settings.upload_dir) / "script2video" / project_id
    script_dir.mkdir(parents=True, exist_ok=True)

    out_path = script_dir / f"scene_{scene_id:03d}_{position}.jpg"
    img = Image.open(io.BytesIO(content)).convert("RGB")
    img.save(out_path, format="JPEG", quality=90)

    return {
        "image_path": str(out_path),
        "image_url": f"/uploads/script2video/{project_id}/scene_{scene_id:03d}_{position}.jpg",
    }
