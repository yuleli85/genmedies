"""
分镜路由 — 调用 LLM 将文章拆分为分镜列表
"""
import asyncio
import aiofiles
from fastapi import APIRouter, HTTPException, BackgroundTasks
from pydantic import BaseModel
from pathlib import Path
from services.llm_service import split_article_to_scenes
from services.task_store import create_task, update_task, get_task, TaskStatus
import services.scenes_cache as scenes_cache

router = APIRouter(prefix="/api/scenes", tags=["scenes"])


class SplitRequest(BaseModel):
    article_file_id: str
    portrait_hint: str = ""
    force: bool = False


@router.post("/split")
async def split_to_scenes(req: SplitRequest, bg: BackgroundTasks):
    article_path = _find_article(req.article_file_id)
    if not article_path:
        raise HTTPException(404, "文章文件不存在")

    task = create_task()

    async def _run():
        try:
            update_task(task.task_id, status=TaskStatus.RUNNING, message="正在读取文章...")
            async with aiofiles.open(article_path, "r", encoding="utf-8") as f:
                text = await f.read()

            if not req.force:
                cached = scenes_cache.get(text)
                if cached:
                    update_task(
                        task.task_id,
                        status=TaskStatus.DONE,
                        progress=100,
                        message="命中缓存，直接返回",
                        result=cached,
                    )
                    return

            update_task(task.task_id, progress=20, message="正在调用 AI 拆分分镜...")
            scenes_data = await split_article_to_scenes(text, req.portrait_hint)
            scenes_cache.set(text, scenes_data)

            update_task(
                task.task_id,
                status=TaskStatus.DONE,
                progress=100,
                message="分镜拆分完成",
                result=scenes_data,
            )
        except Exception as e:
            update_task(task.task_id, status=TaskStatus.ERROR, message=str(e))

    bg.add_task(_run)
    return {"task_id": task.task_id}


@router.get("/task/{task_id}")
async def get_scene_task(task_id: str):
    t = get_task(task_id)
    if not t:
        raise HTTPException(404, "任务不存在")
    return t


def _find_article(file_id: str) -> Path | None:
    article_dir = Path("uploads/articles")
    for p in article_dir.iterdir():
        if p.stem == file_id:
            return p
    return None

