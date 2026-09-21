"""
视频生成 & 合并路由
- POST /api/videos/generate  — 为每个分镜生成小视频（Kling 图生视频）
- POST /api/videos/merge     — 合并所有小视频为完整视频（可选带旁白 TTS）
- GET  /api/videos/task/{id} — 查询任务状态
"""
import asyncio
import logging
import shutil
from datetime import datetime
from fastapi import APIRouter, HTTPException, BackgroundTasks
from pydantic import BaseModel
from pathlib import Path
from services.kling_service import generate_video_from_image
from services.video_service import merge_videos, image_to_video_ffmpeg, mix_audio_into_video
from services.tts_service import text_to_speech
from services.task_store import create_task, update_task, get_task, TaskStatus
import services.video_cache as video_cache

router = APIRouter(prefix="/api/videos", tags=["videos"])

VIDEO_DIR = Path("uploads/videos")
VIDEO_DIR.mkdir(parents=True, exist_ok=True)


class GenerateVideosRequest(BaseModel):
    project_id: str
    scenes: list[dict]
    use_kling: bool = True
    existing_videos: list[dict] = []
    total_scenes: int = 0
    portrait_path: str = ""  # 人物形象图路径，用于画中画叠加
    force: bool = False       # True 时跳过缓存强制重新生成


class MergeRequest(BaseModel):
    project_id: str
    video_paths: list[str]
    narrations: list[str] = []   # 每个分镜对应的旁白文本
    intro_images: list[str] = []


@router.post("/generate")
async def generate_videos(req: GenerateVideosRequest, bg: BackgroundTasks):
    task = create_task()

    async def _run():
        results = []
        try:
            # total 用传入的总数（含已完成），没传则用 scenes 数量
            total = req.total_scenes if req.total_scenes > 0 else len(req.scenes)
            project_dir = VIDEO_DIR / req.project_id
            project_dir.mkdir(parents=True, exist_ok=True)

            # 已成功的分镜直接复用，按 scene_id 索引
            existing_map = {v["scene_id"]: v for v in req.existing_videos}
            results = list(req.existing_videos)  # 先把已有的放进去
            for idx, scene in enumerate(req.scenes):
                scene_id = scene["scene_id"]

                # 跳过已有视频
                if scene_id in existing_map and Path(existing_map[scene_id]["video_path"]).exists():
                    logging.warning(f"[video] scene {scene_id} already exists, skipping")
                    continue

                duration = scene.get("duration", 5)
                image_path = Path(scene["image_path"])
                prompt = scene.get("image_prompt", "")
                timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
                out_path = project_dir / f"{timestamp}_scene_{scene_id:03d}.mp4"

                update_task(
                    task.task_id,
                    status=TaskStatus.RUNNING,
                    progress=int(len(results) / total * 100),
                    message=f"生成第 {scene_id}/{total} 镜视频...",
                )

                # 查缓存（force=True 时跳过）
                cached = None if req.force else video_cache.get(image_path, prompt, duration)
                if cached:
                    logging.warning(f"[video] scene {scene_id} cache hit, copying {cached}")
                    shutil.copy2(cached, out_path)
                    results.append({
                        "scene_id": scene_id,
                        "video_path": str(out_path),
                        "video_url": f"/uploads/videos/{req.project_id}/{out_path.name}",
                        "duration": duration,
                        "from_cache": True,
                    })
                    update_task(
                        task.task_id,
                        status=TaskStatus.RUNNING,
                        progress=int(len(results) / total * 100),
                        message=f"已完成 {len(results)}/{total} 镜（命中缓存）...",
                        result={"videos": sorted(results, key=lambda x: x["scene_id"])},
                    )
                    continue

                # 单镜最多重试 2 次，全部失败则降级为 FFmpeg 静态图
                success = False
                if req.use_kling and image_path.exists():
                    for attempt in range(2):
                        try:
                            logging.warning(f"[video] kling attempt {attempt+1}: scene={scene_id}")
                            await generate_video_from_image(image_path, prompt, out_path, duration)
                            success = True
                            break
                        except Exception as e:
                            logging.error(f"[video] kling scene {scene_id} attempt {attempt+1} failed: {e}")
                            if attempt < 1:
                                await asyncio.sleep(10)

                if not success:
                    logging.warning(f"[video] scene {scene_id} fallback to ffmpeg")
                    portrait_path = Path(req.portrait_path) if req.portrait_path else None
                    await image_to_video_ffmpeg(image_path, out_path, duration, portrait_path)

                # 写入缓存
                try:
                    video_cache.put(image_path, prompt, duration, out_path)
                except Exception as ce:
                    logging.warning(f"[video] cache write failed for scene {scene_id}: {ce}")

                results.append({
                    "scene_id": scene_id,
                    "video_path": str(out_path),
                    "video_url": f"/uploads/videos/{req.project_id}/{out_path.name}",
                    "duration": duration,
                })

                # 每完成一个镜头立即更新部分结果（方便前端在失败时恢复）
                update_task(
                    task.task_id,
                    status=TaskStatus.RUNNING,
                    progress=int(len(results) / total * 100),
                    message=f"已完成 {len(results)}/{total} 镜...",
                    result={"videos": sorted(results, key=lambda x: x["scene_id"])},
                )

                if idx < total - 1:
                    await asyncio.sleep(2)

            update_task(
                task.task_id,
                status=TaskStatus.DONE,
                progress=100,
                message="所有分镜视频生成完毕",
                result={"videos": sorted(results, key=lambda x: x["scene_id"])},
            )
        except Exception as e:
            # 失败时保留已成功的部分结果，前端可据此继续
            update_task(task.task_id, status=TaskStatus.ERROR, message=str(e),
                        result={"videos": sorted(results, key=lambda x: x["scene_id"])} if results else None)

    bg.add_task(_run)
    return {"task_id": task.task_id}


@router.post("/merge")
async def merge_all_videos(req: MergeRequest, bg: BackgroundTasks):
    task = create_task()

    async def _run():
        try:
            video_paths = [Path(p) for p in req.video_paths]
            missing = [str(p) for p in video_paths if not p.exists()]
            if missing:
                raise FileNotFoundError(f"视频文件不存在: {missing}")

            timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
            project_dir = VIDEO_DIR / req.project_id
            project_dir.mkdir(parents=True, exist_ok=True)

            # ── 片头：图片 → 一段片头视频 ──
            intro_video_path = None
            if req.intro_images:
                intro_dir = project_dir / f"{timestamp}_intro"
                intro_dir.mkdir(exist_ok=True)
                intro_clips = []

                for idx, img_url in enumerate(req.intro_images):
                    update_task(
                        task.task_id,
                        status=TaskStatus.RUNNING,
                        progress=int(idx / max(len(req.intro_images), 1) * 10),
                        message=f"正在生成片头第 {idx+1}/{len(req.intro_images)} 张...",
                    )
                    img_file = Path(img_url.lstrip("/"))
                    if not img_file.exists():
                        continue
                    clip_out = intro_dir / f"intro_{idx:03d}.mp4"
                    await image_to_video_ffmpeg(img_file, clip_out, duration=4)
                    intro_clips.append(clip_out)

                if intro_clips:
                    intro_merged = intro_dir / "intro_merged.mp4"
                    await merge_videos(intro_clips, intro_merged)
                    intro_video_path = intro_merged

            # ── 逐镜头配旁白 TTS ──
            narrated_paths = []
            tts_dir = project_dir / f"{timestamp}_tts"
            has_narrations = any(n.strip() for n in req.narrations) if req.narrations else False

            if has_narrations:
                tts_dir.mkdir(exist_ok=True)

            for idx, vp in enumerate(video_paths):
                narration = req.narrations[idx] if idx < len(req.narrations) else ""
                if has_narrations and narration.strip():
                    update_task(
                        task.task_id,
                        status=TaskStatus.RUNNING,
                        progress=int(10 + idx / len(video_paths) * 60),
                        message=f"正在为第 {idx+1}/{len(video_paths)} 镜生成配音...",
                    )
                    tts_path = tts_dir / f"tts_{idx:03d}.mp3"
                    await text_to_speech(narration, tts_path)
                    dubbed_path = tts_dir / f"dubbed_{idx:03d}.mp4"
                    await mix_audio_into_video(vp, tts_path, dubbed_path)
                    narrated_paths.append(dubbed_path)
                else:
                    narrated_paths.append(vp)

            # ── 最终合并：片头视频 + 配音后的分镜视频 ──
            update_task(task.task_id, status=TaskStatus.RUNNING, progress=80, message="正在拼接最终视频...")
            all_paths = []
            if intro_video_path:
                all_paths.append(intro_video_path)
            all_paths.extend(narrated_paths)

            out_path = project_dir / f"{timestamp}_final.mp4"
            await merge_videos(all_paths, out_path)

            update_task(
                task.task_id,
                status=TaskStatus.DONE,
                progress=100,
                message="视频合并完成",
                result={
                    "final_video_path": str(out_path),
                    "final_video_url": f"/uploads/videos/{req.project_id}/{out_path.name}",
                },
            )
        except Exception as e:
            update_task(task.task_id, status=TaskStatus.ERROR, message=str(e))

    bg.add_task(_run)
    return {"task_id": task.task_id}


@router.get("/task/{task_id}")
async def get_video_task(task_id: str):
    t = get_task(task_id)
    if not t:
        raise HTTPException(404, "任务不存在")
    return t
