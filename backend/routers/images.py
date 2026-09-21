"""
图片生成路由 — 为每个分镜调用图片生成服务
"""
import asyncio
import shutil
import logging
from fastapi import APIRouter, HTTPException, BackgroundTasks
from pydantic import BaseModel
from pathlib import Path
from services.llm_service import translate_to_english, translate_to_chinese
from services.task_store import create_task, update_task, get_task, TaskStatus
import services.image_cache as image_cache

router = APIRouter(prefix="/api/images", tags=["images"])

IMAGE_DIR = Path("uploads/images")
IMAGE_DIR.mkdir(parents=True, exist_ok=True)

# 可用模型列表，供前端展示
IMAGE_MODELS = [
    {"id": "kolors",  "name": "Kolors（硅基流动）",  "provider": "siliconflow"},
    {"id": "hunyuan", "name": "混元图像 3.0（腾讯）", "provider": "hunyuan"},
]
DEFAULT_MODEL = "hunyuan"


async def _generate(prompt: str, out_path: Path, model_id: str) -> None:
    if model_id == "hunyuan":
        from services.hunyuan_service import generate_image_from_text
    else:
        from services.siliconflow_service import generate_image_from_text
    await generate_image_from_text(prompt, out_path)


class GenerateImagesRequest(BaseModel):
    project_id: str
    scenes: list[dict]
    portrait_description: str = ""
    force: bool = False
    model: str = DEFAULT_MODEL
    prompt_lang: str = "zh"   # "en" 或 "zh"


class RegenerateImageRequest(BaseModel):
    project_id: str
    scene_id: int
    image_prompt: str
    portrait_description: str = ""
    model: str = DEFAULT_MODEL
    prompt_lang: str = "en"


def _inject_portrait(prompt: str, portrait_en: str) -> str:
    if not portrait_en:
        return prompt
    return f"{prompt}, with a presenter {portrait_en} explaining and demonstrating"


def _inject_portrait_zh(prompt: str, portrait_zh: str) -> str:
    if not portrait_zh:
        return prompt
    return f"{prompt}，画面中有{portrait_zh}正在讲解演示"


_portrait_en_cache: dict[str, str] = {}
_portrait_zh_cache: dict[str, str] = {}


async def _get_portrait_en(description: str) -> str:
    if not description:
        return ""
    if description not in _portrait_en_cache:
        if any('一' <= c <= '鿿' for c in description):
            _portrait_en_cache[description] = await translate_to_english(description)
        else:
            _portrait_en_cache[description] = description
    return _portrait_en_cache[description]


async def _get_portrait_zh(description: str) -> str:
    if not description:
        return ""
    if description not in _portrait_zh_cache:
        if any('一' <= c <= '鿿' for c in description):
            _portrait_zh_cache[description] = description
        else:
            _portrait_zh_cache[description] = await translate_to_chinese(description)
    return _portrait_zh_cache[description]


async def _build_prompt(base_prompt_en: str, portrait_description: str, prompt_lang: str) -> str:
    """根据语言设置构建最终 prompt"""
    if prompt_lang == "zh":
        base = await translate_to_chinese(base_prompt_en)
        portrait = await _get_portrait_zh(portrait_description)
        return _inject_portrait_zh(base, portrait)
    else:
        portrait = await _get_portrait_en(portrait_description)
        return _inject_portrait(base_prompt_en, portrait)


@router.get("/models")
async def list_models():
    return IMAGE_MODELS


@router.post("/generate")
async def generate_images(req: GenerateImagesRequest, bg: BackgroundTasks):
    task = create_task()

    async def _run():
        try:
            total = len(req.scenes)
            results = []
            project_dir = IMAGE_DIR / req.project_id
            project_dir.mkdir(parents=True, exist_ok=True)

            for idx, scene in enumerate(req.scenes):
                scene_id = scene["scene_id"]
                prompt = await _build_prompt(scene["image_prompt"], req.portrait_description, req.prompt_lang)
                out_path = project_dir / f"scene_{scene_id:03d}.jpg"
                update_task(
                    task.task_id,
                    status=TaskStatus.RUNNING,
                    progress=int(idx / total * 100),
                    message=f"生成第 {scene_id}/{total} 镜图片...",
                )

                cache_key = f"{req.model}:{req.prompt_lang}:{prompt}"
                # 文件已存在且非强制 → 直接返回
                if not req.force and out_path.exists():
                    logging.info(f"[image] scene {scene_id} 文件已存在，跳过生成")
                    results.append({
                        "scene_id": scene_id,
                        "image_path": str(out_path),
                        "image_url": f"/uploads/images/{req.project_id}/scene_{scene_id:03d}.jpg",
                        "from_cache": True,
                    })
                    continue

                cached = image_cache.get(cache_key)
                if cached:
                    shutil.copy2(cached, out_path)
                    logging.warning(f"[image] scene {scene_id} cache hit (model={req.model})")
                else:
                    await _generate(prompt, out_path, req.model)
                    try:
                        image_cache.put(cache_key, out_path)
                    except Exception as ce:
                        logging.warning(f"[image] cache write failed scene {scene_id}: {ce}")
                    if idx < total - 1:
                        await asyncio.sleep(1)

                results.append({
                    "scene_id": scene_id,
                    "image_path": str(out_path),
                    "image_url": f"/uploads/images/{req.project_id}/scene_{scene_id:03d}.jpg",
                    "from_cache": cached is not None,
                })

            update_task(
                task.task_id,
                status=TaskStatus.DONE,
                progress=100,
                message="所有图片生成完毕",
                result={"images": results},
            )
        except Exception as e:
            update_task(task.task_id, status=TaskStatus.ERROR, message=str(e))

    bg.add_task(_run)
    return {"task_id": task.task_id}


@router.post("/regenerate")
async def regenerate_image(req: RegenerateImageRequest, bg: BackgroundTasks):
    task = create_task()

    async def _run():
        try:
            update_task(task.task_id, status=TaskStatus.RUNNING, message="正在重新生成图片...")
            project_dir = IMAGE_DIR / req.project_id
            project_dir.mkdir(parents=True, exist_ok=True)
            out_path = project_dir / f"scene_{req.scene_id:03d}.jpg"
            prompt = await _build_prompt(req.image_prompt, req.portrait_description, req.prompt_lang)
            await _generate(prompt, out_path, req.model)
            try:
                image_cache.put(f"{req.model}:{req.prompt_lang}:{prompt}", out_path)
            except Exception as ce:
                logging.warning(f"[image] cache write failed regen: {ce}")
            update_task(
                task.task_id,
                status=TaskStatus.DONE,
                progress=100,
                message="图片生成完毕",
                result={
                    "scene_id": req.scene_id,
                    "image_path": str(out_path),
                    "image_url": f"/uploads/images/{req.project_id}/scene_{req.scene_id:03d}.jpg",
                },
            )
        except Exception as e:
            update_task(task.task_id, status=TaskStatus.ERROR, message=str(e))

    bg.add_task(_run)
    return {"task_id": task.task_id}


@router.get("/task/{task_id}")
async def get_image_task(task_id: str):
    t = get_task(task_id)
    if not t:
        raise HTTPException(404, "任务不存在")
    return t

