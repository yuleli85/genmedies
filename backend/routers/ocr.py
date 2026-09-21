import uuid
from pathlib import Path

from fastapi import APIRouter, BackgroundTasks, File, HTTPException, UploadFile
from pydantic import BaseModel

from config import settings
from routers.upload import ALLOWED_IMAGE
from services.llm_service import extract_text_from_image
from services.task_store import TaskStatus, create_task, get_task, update_task

router = APIRouter(prefix="/api/ocr", tags=["ocr"])

OCR_DIR = Path(settings.upload_dir) / "ocr"
OCR_DIR.mkdir(parents=True, exist_ok=True)


@router.post("/upload")
async def upload_ocr_image(file: UploadFile = File(...)):
    filename = file.filename or ""
    suffix = Path(filename).suffix.lower()
    if suffix not in ALLOWED_IMAGE:
        raise HTTPException(400, f"不支持的图片格式: {suffix}，支持 {ALLOWED_IMAGE}")

    content = await file.read()
    if not content:
        raise HTTPException(400, "图片文件为空")
    if len(content) > settings.max_file_size_mb * 1024 * 1024:
        raise HTTPException(400, f"文件过大，最大 {settings.max_file_size_mb}MB")

    file_id = f"ocr_{uuid.uuid4().hex[:12]}"
    save_path = OCR_DIR / f"{file_id}{suffix}"
    save_path.write_bytes(content)

    return {
        "file_id": file_id,
        "filename": filename,
        "image_url": f"/uploads/ocr/{file_id}{suffix}",
    }


class ExtractRequest(BaseModel):
    file_id: str


@router.post("/extract")
async def extract_ocr_text(req: ExtractRequest, bg: BackgroundTasks):
    matches = list(OCR_DIR.glob(f"{req.file_id}.*"))
    if not matches:
        raise HTTPException(404, "图片文件不存在")

    image_path = matches[0]
    task = create_task()

    async def _run():
        try:
            update_task(task.task_id, status=TaskStatus.RUNNING, progress=10, message="已接收图片")
            update_task(task.task_id, progress=30, message="正在调用识别模型")
            text = await extract_text_from_image(str(image_path))
            update_task(task.task_id, progress=90, message="正在整理识别结果")

            message = "识别完成" if text else "未识别到可读文字"
            update_task(
                task.task_id,
                status=TaskStatus.DONE,
                progress=100,
                message=message,
                result={
                    "file_id": req.file_id,
                    "filename": image_path.name,
                    "image_url": f"/uploads/ocr/{image_path.name}",
                    "text": text,
                    "text_length": len(text),
                },
            )
        except Exception as e:
            update_task(
                task.task_id,
                status=TaskStatus.ERROR,
                progress=100,
                message=f"识别失败: {e}",
                result={},
            )

    bg.add_task(_run)
    return {"task_id": task.task_id}


@router.get("/task/{task_id}")
async def get_ocr_task(task_id: str):
    task = get_task(task_id)
    if not task:
        raise HTTPException(404, "任务不存在")
    return task
