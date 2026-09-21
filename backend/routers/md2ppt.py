"""
Markdown 转 PPTX 路由

POST /api/md2ppt/upload     上传 .md 文件
POST /api/md2ppt/split      LLM 智能拆分为幻灯片结构
POST /api/md2ppt/generate   生成 .pptx 文件
GET  /api/md2ppt/task/{id}  查询任务状态
"""
import uuid
from pathlib import Path

from fastapi import APIRouter, BackgroundTasks, File, HTTPException, UploadFile
from pydantic import BaseModel

from services.llm_service import split_markdown_to_slides
from services.pptx_builder import build_pptx
from services.task_store import TaskStatus, create_task, get_task, update_task

router = APIRouter(prefix="/api/md2ppt", tags=["md2ppt"])

MD_DIR = Path("uploads/md2ppt")
MD_DIR.mkdir(parents=True, exist_ok=True)
OUTPUT_DIR = Path("uploads/md2ppt_output")
OUTPUT_DIR.mkdir(parents=True, exist_ok=True)


@router.post("/upload")
async def upload_markdown(file: UploadFile = File(...)):
    if not file.filename.endswith(".md"):
        raise HTTPException(400, "仅支持 .md 文件")

    file_id = f"md_{uuid.uuid4().hex[:12]}"
    save_path = MD_DIR / f"{file_id}.md"
    content = await file.read()
    save_path.write_bytes(content)

    text = content.decode("utf-8", errors="replace")
    return {
        "file_id": file_id,
        "filename": file.filename,
        "content": text,
    }


class SplitRequest(BaseModel):
    file_id: str
    content: str


@router.post("/split")
async def split_markdown(req: SplitRequest, bg: BackgroundTasks):
    task = create_task()

    async def _run():
        try:
            result = await split_markdown_to_slides(req.content)
            slides = result.get("slides", [])
            for i, s in enumerate(slides):
                s["slide_id"] = i + 1
            update_task(task.task_id, status=TaskStatus.DONE, progress=100,
                        message="拆分完成", result={"slides": slides})
        except Exception as e:
            update_task(task.task_id, status=TaskStatus.ERROR, progress=100,
                        message=f"拆分失败: {e}", result={})

    bg.add_task(_run)
    return {"task_id": task.task_id}


class GenerateRequest(BaseModel):
    file_id: str
    slides: list[dict]
    original_filename: str = ""


@router.post("/generate")
async def generate_pptx(req: GenerateRequest):
    output_path = OUTPUT_DIR / f"{req.file_id}.pptx"
    try:
        build_pptx(req.slides, output_path)
    except Exception as e:
        raise HTTPException(500, f"PPTX 生成失败: {e}")

    if req.original_filename:
        stem = Path(req.original_filename).stem
        output_filename = f"{stem}.pptx"
    else:
        output_filename = f"{req.file_id}.pptx"

    return {
        "download_url": f"/uploads/md2ppt_output/{req.file_id}.pptx",
        "output_filename": output_filename,
    }


@router.get("/task/{task_id}")
async def get_md2ppt_task(task_id: str):
    t = get_task(task_id)
    if not t:
        raise HTTPException(404, "任务不存在")
    return t
