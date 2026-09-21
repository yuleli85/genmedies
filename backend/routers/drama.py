"""
真人剧集路由

POST /api/drama/project          创建项目
GET  /api/drama/project/{id}     读取项目
POST /api/drama/project/{id}     更新项目字段

POST /api/drama/script           生成剧本（带缓存）
POST /api/drama/shots            拆解分镜（带缓存）
POST /api/drama/keyframes        批量生成关键帧（调图片生成服务）
POST /api/drama/dub              批量配音（edge-tts，逐角色逐句）
POST /api/drama/lipsync          口型同步（SadTalker，关键帧+音频→说话视频）
POST /api/drama/videos           批量图生视频（调 Kling，3路并发）
POST /api/drama/merge            音视频合成

GET  /api/drama/task/{id}        查询任务进度
"""
import asyncio
import hashlib
import json
import logging
import uuid
from datetime import datetime
from pathlib import Path

import edge_tts
from fastapi import APIRouter, BackgroundTasks, HTTPException
from pydantic import BaseModel

from services.drama_llm_service import (
    generate_script, split_shots,
    script_cache_key, shots_cache_key,
)
from services.task_store import TaskStatus, create_task, get_task, update_task
from services.video_service import mix_audio_into_video, merge_videos, image_to_video_ffmpeg, add_silent_audio as _add_silent_audio
from services.jimeng_service import generate_image_from_text, generate_video_from_image
from services.siliconflow_service import generate_image_from_text as siliconflow_generate_image
from services.lipsync_service import generate_lipsync_video, check_lipsync_available
from services.project_store import load_project, save_project, merge_project
import services.image_cache as image_cache
import services.video_cache as video_cache

router = APIRouter(prefix="/api/drama", tags=["drama"])

BASE_DIR = Path("uploads/drama")
BASE_DIR.mkdir(parents=True, exist_ok=True)


# ── 目录辅助 ──────────────────────────────────────────────

def _proj_dir(project_id: str) -> Path:
    p = BASE_DIR / project_id
    p.mkdir(parents=True, exist_ok=True)
    return p

def _cache_dir(project_id: str) -> Path:
    d = _proj_dir(project_id) / "cache"
    d.mkdir(exist_ok=True)
    return d

def _frames_dir(project_id: str) -> Path:
    d = _proj_dir(project_id) / "keyframes"
    d.mkdir(exist_ok=True)
    return d

def _clips_dir(project_id: str) -> Path:
    d = _proj_dir(project_id) / "clips"
    d.mkdir(exist_ok=True)
    return d

def _audio_dir(project_id: str) -> Path:
    d = _proj_dir(project_id) / "audio"
    d.mkdir(exist_ok=True)
    return d

def _mixed_dir(project_id: str) -> Path:
    d = _proj_dir(project_id) / "mixed"
    d.mkdir(exist_ok=True)
    return d

def _lipsync_dir(project_id: str) -> Path:
    d = _proj_dir(project_id) / "lipsync"
    d.mkdir(exist_ok=True)
    return d


# ── 缓存辅助 ──────────────────────────────────────────────

def _read_cache(project_id: str, key: str):
    f = _cache_dir(project_id) / f"{key}.json"
    if f.exists():
        try:
            return json.loads(f.read_text(encoding="utf-8"))
        except Exception:
            pass
    return None

def _write_cache(project_id: str, key: str, data):
    f = _cache_dir(project_id) / f"{key}.json"
    f.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")

def _clear_cache(project_id: str, key: str):
    f = _cache_dir(project_id) / f"{key}.json"
    f.unlink(missing_ok=True)


# ── 项目 CRUD ─────────────────────────────────────────────

class ProjectCreateRequest(BaseModel):
    title:       str = "未命名剧集"
    genre:       str = ""
    plot_summary: str = ""
    episode_count: int = 1
    duration_per_episode: int = 120
    characters:  list[dict] = []
    style:       str = "写实电影感"

@router.post("/project")
async def create_project(req: ProjectCreateRequest):
    project_id = f"drama_{uuid.uuid4().hex[:12]}"
    data = {
        **req.model_dump(),
        "type":       "drama",
        "phase":      "script",
        "updated_at": datetime.utcnow().isoformat(),
    }
    save_project(project_id, data)
    return {"project_id": project_id, **data}

@router.get("/project/{project_id}")
async def get_drama_project(project_id: str):
    data = load_project(project_id)
    if not data:
        raise HTTPException(404, "项目不存在")
    return data

@router.post("/project/{project_id}")
async def update_drama_project(project_id: str, body: dict):
    body["updated_at"] = datetime.utcnow().isoformat()
    return merge_project(project_id, body)


@router.post("/project/{project_id}/copy")
async def copy_drama_project(project_id: str):
    """复制项目基本信息，不复制生成的内容"""
    data = load_project(project_id)
    if not data:
        raise HTTPException(404, "项目不存在")

    new_project_id = f"drama_{uuid.uuid4().hex[:12]}"
    new_data = {
        "title":       data.get("title", "未命名剧集") + " (副本)",
        "genre":       data.get("genre", ""),
        "plot_summary": data.get("plot_summary", ""),
        "episode_count": data.get("episode_count", 1),
        "duration_per_episode": data.get("duration_per_episode", 120),
        "characters":  data.get("characters", []),
        "style":       data.get("style", "写实电影感"),
        "type":        "drama",
        "phase":       "script",
        "updated_at":  datetime.utcnow().isoformat(),
    }
    save_project(new_project_id, new_data)
    return {"project_id": new_project_id, **new_data}


# ── 1. 剧本生成 ───────────────────────────────────────────

class ScriptRequest(BaseModel):
    project_id:  str
    episode:     int = 1
    force:       bool = False   # True = 忽略缓存强制重新生成

@router.post("/script")
async def gen_script(req: ScriptRequest, bg: BackgroundTasks):
    proj = load_project(req.project_id)
    if not proj:
        raise HTTPException(404, "项目不存在")

    ckey = script_cache_key(
        proj.get("genre", ""),
        proj.get("plot_summary", ""),
        proj.get("style", ""),
        req.episode,
    )

    if not req.force:
        cached = _read_cache(req.project_id, f"script_ep{req.episode}_{ckey}")
        if cached:
            return {"from_cache": True, "script": cached}

    task = create_task()

    async def _run():
        try:
            script = await generate_script(
                genre=proj.get("genre", ""),
                plot_summary=proj.get("plot_summary", ""),
                episode=req.episode,
                characters=proj.get("characters", []),
                style=proj.get("style", "写实电影感"),
            )
            _write_cache(req.project_id, f"script_ep{req.episode}_{ckey}", script)
            merge_project(req.project_id, {"phase": "shots", "updated_at": datetime.utcnow().isoformat()})
            update_task(task.task_id, status=TaskStatus.DONE, progress=100,
                        message="剧本生成完成", result={"script": script})
        except Exception as e:
            update_task(task.task_id, status=TaskStatus.ERROR, progress=100,
                        message=f"剧本生成失败: {e}", result={})

    bg.add_task(_run)
    return {"task_id": task.task_id}


# ── 2. 分镜拆解 ───────────────────────────────────────────

class ShotsRequest(BaseModel):
    project_id: str
    episode:    int = 1
    scenes:     list[dict]
    force:      bool = False

@router.post("/shots")
async def gen_shots(req: ShotsRequest, bg: BackgroundTasks):
    proj = load_project(req.project_id)
    if not proj:
        raise HTTPException(404, "项目不存在")

    scenes_json = json.dumps(req.scenes, ensure_ascii=False, sort_keys=True)
    ckey = shots_cache_key(scenes_json, proj.get("style", ""))

    if not req.force:
        cached = _read_cache(req.project_id, f"shots_ep{req.episode}_{ckey}")
        if cached:
            return {"from_cache": True, "shots": cached}

    task = create_task()

    async def _run():
        try:
            shots = await split_shots(
                scenes=req.scenes,
                characters=proj.get("characters", []),
                style=proj.get("style", "写实电影感"),
            )
            _write_cache(req.project_id, f"shots_ep{req.episode}_{ckey}", shots)
            merge_project(req.project_id, {"phase": "keyframes", "updated_at": datetime.utcnow().isoformat()})
            update_task(task.task_id, status=TaskStatus.DONE, progress=100,
                        message="分镜拆解完成", result={"shots": shots})
        except Exception as e:
            update_task(task.task_id, status=TaskStatus.ERROR, progress=100,
                        message=f"分镜拆解失败: {e}", result={})

    bg.add_task(_run)
    return {"task_id": task.task_id}


# ── 3. 关键帧生成 ─────────────────────────────────────────

class KeyframesRequest(BaseModel):
    project_id: str
    episode:    int = 1
    shots:      list[dict]
    force_ids:  list[int] = []   # 指定强制重新生成的 shot_id，空=全部走缓存
    provider:   str = "siliconflow"   # "jimeng" (即梦 Seedream) | "siliconflow" (SiliconFlow Kolors)

@router.post("/keyframes")
async def gen_keyframes(req: KeyframesRequest, bg: BackgroundTasks):
    task = create_task()
    proj = load_project(req.project_id)
    characters = {c.get("name"): c for c in proj.get("characters", []) if c.get("name")}

    async def _run():
        total   = len(req.shots)
        results = []
        failed  = []
        sem     = asyncio.Semaphore(1)  # Kling 文生图限流严，串行避免 429

        async def _one(shot: dict):
            sid    = shot["shot_id"]
            prompt = shot.get("image_prompt", "")
            ckey   = f"kf_ep{req.episode}_shot{sid}_{hashlib.md5(prompt.encode()).hexdigest()[:8]}"
            frame_path = _frames_dir(req.project_id) / f"ep{req.episode}_shot{sid:03d}.png"
            force = sid in req.force_ids

            # 查找该镜头角色的参考图
            ref_image_path = None
            shot_chars = shot.get("characters", [])
            for char_name in shot_chars:
                char_info = characters.get(char_name, {})
                ref_url = char_info.get("ref_url", "")
                if ref_url:
                    ref_image_path = Path(__file__).parent.parent / ref_url.lstrip("/")
                    if ref_image_path.exists():
                        break
                    ref_image_path = None

            if not force:
                # 0) 文件已存在 → 直接返回（最快路径）
                if frame_path.exists():
                    image_url = f"/uploads/drama/{req.project_id}/keyframes/ep{req.episode}_shot{sid:03d}.png"
                    if prompt:
                        try:
                            image_cache.put(prompt, frame_path)
                        except Exception:
                            pass
                    return {"shot_id": sid, "image_url": image_url, "from_cache": True}

                # 1) Prompt 级 Redis 缓存:同 prompt 命中直接复用(跨镜头共享)
                hit = image_cache.get(prompt) if prompt else None
                if hit:
                    try:
                        import shutil as _sh
                        _sh.copy2(hit, frame_path)
                        image_url = f"/uploads/drama/{req.project_id}/keyframes/ep{req.episode}_shot{sid:03d}.png"
                        _write_cache(req.project_id, ckey, {"image_url": image_url})
                        logging.info(f"[drama/kf] shot {sid} Redis 缓存命中")
                        return {"shot_id": sid, "image_url": image_url, "from_cache": True}
                    except Exception as e:
                        logging.warning(f"[drama/kf] shot {sid} 复用缓存文件失败: {e}")

            async with sem:
                for attempt in range(3):
                    try:
                        if req.provider == "siliconflow":
                            await siliconflow_generate_image(prompt, frame_path)
                        else:
                            await generate_image_from_text(prompt, frame_path, ref_image_path)
                        image_url = f"/uploads/drama/{req.project_id}/keyframes/ep{req.episode}_shot{sid:03d}.png"
                        _write_cache(req.project_id, ckey, {"image_url": image_url})
                        if prompt:
                            try:
                                image_cache.put(prompt, frame_path)
                            except Exception as ce:
                                logging.warning(f"[drama/kf] shot {sid} Redis 写缓存失败: {ce}")
                        return {"shot_id": sid, "image_url": image_url, "from_cache": False}
                    except Exception as e:
                        if "429" in str(e) and attempt < 2:
                            await asyncio.sleep(10 * (attempt + 1))  # 429 退避
                            continue
                        logging.error(f"[drama/kf] shot {sid} 失败: {e}")
                        return {"shot_id": sid, "error": str(e)}

        tasks = [_one(s) for s in req.shots]
        done  = 0
        for coro in asyncio.as_completed(tasks):
            r = await coro
            done += 1
            if "error" in r:
                failed.append(r)
            results.append(r)
            update_task(task.task_id, status=TaskStatus.RUNNING,
                        progress=int(done / total * 95),
                        message=f"已生成 {done}/{total} 张关键帧",
                        result={"frames": results, "failed": failed})

        if failed:
            sids = ", ".join(str(f["shot_id"]) for f in failed)
            update_task(task.task_id, status=TaskStatus.ERROR, progress=100,
                        message=f"镜头 {sids} 关键帧生成失败",
                        result={"frames": results, "failed": failed})
        else:
            merge_project(req.project_id, {"phase": "dub", "updated_at": datetime.utcnow().isoformat()})
            update_task(task.task_id, status=TaskStatus.DONE, progress=100,
                        message="关键帧全部完成", result={"frames": results, "failed": []})

    bg.add_task(_run)
    return {"task_id": task.task_id}


# ── 4. 图生视频 ───────────────────────────────────────────

class VideosRequest(BaseModel):
    project_id: str
    episode:    int = 1
    shots:      list[dict]   # 含 shot_id / action / duration / image_url
    force_ids:  list[int] = []
    provider:   str = "local"   # "local" (FFmpeg 本地图转视频) | "jimeng" (Seedance 图生视频)

@router.post("/videos")
async def gen_videos(req: VideosRequest, bg: BackgroundTasks):
    task = create_task()

    async def _run():
        total   = len(req.shots)
        results = []
        failed  = []
        sem     = asyncio.Semaphore(3)

        async def _one(shot: dict):
            sid       = shot["shot_id"]
            image_url = shot.get("image_url", "").strip()
            action    = shot.get("action", "")
            duration  = int(shot.get("duration", 5) or 5)
            ckey      = f"vid_ep{req.episode}_shot{sid}_{req.provider}_{hashlib.md5((image_url+action).encode()).hexdigest()[:8]}"
            clip_path = _clips_dir(req.project_id) / f"ep{req.episode}_shot{sid:03d}.mp4"
            force = sid in req.force_ids

            if not image_url:
                return {"shot_id": sid, "error": "缺少关键帧图片,请先完成关键帧生成", "status": "manual_required"}

            frame_path = Path(__file__).parent.parent / image_url.lstrip("/")
            if not frame_path.exists():
                return {"shot_id": sid, "error": f"关键帧文件不存在: {frame_path}", "status": "manual_required"}

            if not force:
                # 1) Prompt 级 Redis 缓存:同(图片字节+prompt+duration+provider)命中直接复用
                hit = video_cache.get(frame_path, action, duration, req.provider)
                if hit:
                    try:
                        import shutil as _sh
                        _sh.copy2(hit, clip_path)
                        video_url = f"/uploads/drama/{req.project_id}/clips/ep{req.episode}_shot{sid:03d}.mp4"
                        _write_cache(req.project_id, ckey, {"video_url": video_url})
                        logging.info(f"[drama/vid] shot {sid} Redis 缓存命中")
                        return {"shot_id": sid, "video_url": video_url, "from_cache": True}
                    except Exception as e:
                        logging.warning(f"[drama/vid] shot {sid} 复用缓存文件失败: {e}")

                # 2) 镜头级落盘缓存回落(同项目同 shot_id 才命中)
                if clip_path.exists():
                    cached = _read_cache(req.project_id, ckey)
                    if cached:
                        try:
                            video_cache.put(frame_path, action, duration, clip_path, req.provider)
                        except Exception:
                            pass
                        return {"shot_id": sid, "video_url": cached["video_url"], "from_cache": True}

            async with sem:
                for attempt in range(3):
                    try:
                        if req.provider == "jimeng":
                            await generate_video_from_image(
                                image_path=frame_path,
                                prompt=action,
                                duration=duration,
                                output_path=clip_path,
                            )
                        else:
                            await image_to_video_ffmpeg(
                                image_path=frame_path,
                                output_path=clip_path,
                                duration=duration,
                            )
                        video_url = f"/uploads/drama/{req.project_id}/clips/ep{req.episode}_shot{sid:03d}.mp4"
                        _write_cache(req.project_id, ckey, {"video_url": video_url})
                        try:
                            video_cache.put(frame_path, action, duration, clip_path, req.provider)
                        except Exception as ce:
                            logging.warning(f"[drama/vid] shot {sid} Redis 写缓存失败: {ce}")
                        return {"shot_id": sid, "video_url": video_url, "from_cache": False}
                    except Exception as e:
                        if attempt == 2:
                            logging.error(f"[drama/vid] shot {sid} 失败: {e}")
                            return {"shot_id": sid, "error": str(e), "status": "manual_required"}
                        await asyncio.sleep(2)

        tasks = [_one(s) for s in req.shots]
        done  = 0
        for coro in asyncio.as_completed(tasks):
            r = await coro
            done += 1
            if "error" in r:
                failed.append(r)
            results.append(r)
            update_task(task.task_id, status=TaskStatus.RUNNING,
                        progress=int(done / total * 95),
                        message=f"已生成 {done}/{total} 个视频片段",
                        result={"clips": results, "failed": failed})

        if failed:
            sids = ", ".join(str(f["shot_id"]) for f in failed)
            update_task(task.task_id, status=TaskStatus.ERROR, progress=100,
                        message=f"镜头 {sids} 视频生成失败，需人工替换",
                        result={"clips": results, "failed": failed})
        else:
            merge_project(req.project_id, {"phase": "merge", "updated_at": datetime.utcnow().isoformat()})
            update_task(task.task_id, status=TaskStatus.DONE, progress=100,
                        message="视频片段全部完成", result={"clips": results, "failed": []})

    bg.add_task(_run)
    return {"task_id": task.task_id}


# ── 5. 多角色配音 ─────────────────────────────────────────

VOICE_MAP = {
    "male":   "zh-CN-YunxiNeural",
    "female": "zh-CN-XiaoxiaoNeural",
}

class DubRequest(BaseModel):
    project_id: str
    episode:    int = 1
    shots:      list[dict]   # 含 shot_id / dialogue / character
    voice_settings: dict = {}  # {角色名: voice_id}
    force_ids:  list[int] = []

@router.post("/dub")
async def gen_dub(req: DubRequest, bg: BackgroundTasks):
    task = create_task()

    async def _run():
        proj       = load_project(req.project_id)
        characters = {c["name"]: c for c in proj.get("characters", [])}

        # 优先使用请求中的 shots，如果为空或缺少 dialogue 则从项目文件读取
        shots_to_use = req.shots
        if not shots_to_use or not any(s.get("dialogue") for s in shots_to_use):
            saved_shots = proj.get("shots", [])
            if saved_shots:
                # 如果请求指定了 shot_id 范围，只取对应的
                if shots_to_use:
                    req_ids = {s["shot_id"] for s in shots_to_use}
                    shots_to_use = [s for s in saved_shots if s["shot_id"] in req_ids]
                else:
                    shots_to_use = saved_shots
                logging.info(f"[drama/dub] 使用项目保存的 shots 数据，共 {len(shots_to_use)} 个")

        total      = len([s for s in shots_to_use if s.get("dialogue")])
        done       = 0
        results    = []
        failed     = []

        for shot in shots_to_use:
            sid      = shot["shot_id"]
            dialogue = shot.get("dialogue", "").strip()
            if not dialogue:
                results.append({"shot_id": sid, "skipped": True})
                continue

            char   = shot.get("character", "")
            voice  = req.voice_settings.get(char)
            if not voice:
                gender = characters.get(char, {}).get("gender", "male")
                voice  = VOICE_MAP.get(gender, VOICE_MAP["male"])

            ckey      = f"dub_ep{req.episode}_shot{sid}_{hashlib.md5((dialogue+voice).encode()).hexdigest()[:8]}"
            audio_out = _audio_dir(req.project_id) / f"ep{req.episode}_shot{sid:03d}.mp3"

            if sid not in req.force_ids and audio_out.exists():
                cached = _read_cache(req.project_id, ckey)
                if cached:
                    results.append({"shot_id": sid, "audio_url": cached["audio_url"], "from_cache": True})
                    done += 1
                    continue

            update_task(task.task_id, status=TaskStatus.RUNNING,
                        progress=int(done / max(total, 1) * 90),
                        message=f"配音第 {sid} 镜头...")
            try:
                comm = edge_tts.Communicate(text=dialogue, voice=voice)
                await comm.save(str(audio_out))
                audio_url = f"/uploads/drama/{req.project_id}/audio/ep{req.episode}_shot{sid:03d}.mp3"
                _write_cache(req.project_id, ckey, {"audio_url": audio_url})
                results.append({"shot_id": sid, "audio_url": audio_url, "from_cache": False})
            except Exception as e:
                logging.error(f"[drama/dub] shot {sid} 失败: {e}")
                failed.append({"shot_id": sid, "error": str(e)})
                results.append({"shot_id": sid, "error": str(e)})

            done += 1
            update_task(task.task_id, status=TaskStatus.RUNNING,
                        progress=int(done / max(total, 1) * 95),
                        message=f"已完成 {done}/{total} 条配音",
                        result={"audio": results, "failed": failed})

        if failed:
            sids = ", ".join(str(f["shot_id"]) for f in failed)
            update_task(task.task_id, status=TaskStatus.ERROR, progress=100,
                        message=f"镜头 {sids} 配音失败",
                        result={"audio": results, "failed": failed})
        else:
            merge_project(req.project_id, {"phase": "lipsync", "updated_at": datetime.utcnow().isoformat()})
            update_task(task.task_id, status=TaskStatus.DONE, progress=100,
                        message="配音全部完成", result={"audio": results, "failed": []})

    bg.add_task(_run)
    return {"task_id": task.task_id}


# ── 5.5 口型同步 ─────────────────────────────────────────

class LipsyncRequest(BaseModel):
    project_id: str
    episode:    int = 1
    shots:      list[dict]   # 含 shot_id，需要有对应的关键帧和音频
    force_ids:  list[int] = []

@router.post("/lipsync")
async def gen_lipsync(req: LipsyncRequest, bg: BackgroundTasks):
    available = await check_lipsync_available()
    if not available:
        raise HTTPException(400, "未配置 REPLICATE_API_TOKEN，无法使用口型同步。请在 .env 中设置")

    task = create_task()

    async def _run():
        total   = len(req.shots)
        results = []
        failed  = []
        sem     = asyncio.Semaphore(2)

        async def _one(shot: dict):
            sid = shot["shot_id"]
            frame_path = _frames_dir(req.project_id) / f"ep{req.episode}_shot{sid:03d}.png"
            audio_path = _audio_dir(req.project_id) / f"ep{req.episode}_shot{sid:03d}.mp3"
            lipsync_out = _lipsync_dir(req.project_id) / f"ep{req.episode}_shot{sid:03d}.mp4"
            force = sid in req.force_ids

            if not frame_path.exists():
                return {"shot_id": sid, "error": "缺少关键帧图片"}
            if not audio_path.exists():
                return {"shot_id": sid, "skipped": True}

            if not force and lipsync_out.exists():
                video_url = f"/uploads/drama/{req.project_id}/lipsync/ep{req.episode}_shot{sid:03d}.mp4"
                return {"shot_id": sid, "video_url": video_url, "from_cache": True}

            async with sem:
                try:
                    await generate_lipsync_video(frame_path, audio_path, lipsync_out)
                    video_url = f"/uploads/drama/{req.project_id}/lipsync/ep{req.episode}_shot{sid:03d}.mp4"
                    return {"shot_id": sid, "video_url": video_url, "from_cache": False}
                except Exception as e:
                    logging.error(f"[drama/lipsync] shot {sid} 失败: {e}")
                    return {"shot_id": sid, "error": str(e)}

        tasks = [_one(s) for s in req.shots]
        done = 0
        for coro in asyncio.as_completed(tasks):
            r = await coro
            done += 1
            if "error" in r:
                failed.append(r)
            results.append(r)
            update_task(task.task_id, status=TaskStatus.RUNNING,
                        progress=int(done / total * 95),
                        message=f"已完成 {done}/{total} 个口型同步",
                        result={"lipsync": results, "failed": failed})

        if failed:
            sids = ", ".join(str(f["shot_id"]) for f in failed)
            update_task(task.task_id, status=TaskStatus.ERROR, progress=100,
                        message=f"镜头 {sids} 口型同步失败",
                        result={"lipsync": results, "failed": failed})
        else:
            merge_project(req.project_id, {"phase": "video", "updated_at": datetime.utcnow().isoformat()})
            update_task(task.task_id, status=TaskStatus.DONE, progress=100,
                        message="口型同步全部完成", result={"lipsync": results, "failed": []})

    bg.add_task(_run)
    return {"task_id": task.task_id}


# ── 6. 音视频合成 ─────────────────────────────────────────

class MergeRequest(BaseModel):
    project_id: str
    episode:    int = 1
    shots:      list[dict]   # 含 shot_id / video_url / audio_url（可为空）

@router.post("/merge")
async def merge_drama(req: MergeRequest, bg: BackgroundTasks):
    proj = load_project(req.project_id)
    saved_shots = {s["shot_id"]: s for s in proj.get("shots", [])}

    # 验证：有台词的镜头必须有音频文件
    missing_audio = []
    for shot in req.shots:
        sid = shot["shot_id"]
        saved = saved_shots.get(sid, {})
        has_dialogue = saved.get("dialogue", "").strip()
        audio_path = _audio_dir(req.project_id) / f"ep{req.episode}_shot{sid:03d}.mp3"
        if has_dialogue and not audio_path.exists():
            missing_audio.append(sid)

    if missing_audio:
        raise HTTPException(400, f"镜头 {', '.join(map(str, missing_audio))} 有台词但缺少配音，请先完成配音")

    task = create_task()

    async def _run():
        total      = len(req.shots)
        mixed_dir  = _mixed_dir(req.project_id)
        mixed_paths = []
        results    = []

        for idx, shot in enumerate(req.shots):
            sid        = shot["shot_id"]
            clip_path  = _clips_dir(req.project_id) / f"ep{req.episode}_shot{sid:03d}.mp4"
            audio_path = _audio_dir(req.project_id) / f"ep{req.episode}_shot{sid:03d}.mp3"
            lipsync_path = _lipsync_dir(req.project_id) / f"ep{req.episode}_shot{sid:03d}.mp4"
            mixed_out  = mixed_dir / f"ep{req.episode}_shot{sid:03d}.mp4"

            # 优先使用口型同步视频（已包含音频），其次用普通视频+音频混合
            if lipsync_path.exists():
                # 口型同步视频已包含音频，直接使用
                import shutil
                shutil.copy2(lipsync_path, mixed_out)
                mixed_paths.append(mixed_out)
                results.append({"shot_id": sid, "mixed": True, "source": "lipsync"})
            elif clip_path.exists():
                update_task(task.task_id, status=TaskStatus.RUNNING,
                            progress=int(idx / total * 75),
                            message=f"混音第 {sid} 镜头... ({idx+1}/{total})",
                            result={"mixed": results})
                try:
                    if audio_path.exists():
                        await mix_audio_into_video(clip_path, audio_path, mixed_out)
                    else:
                        await _add_silent_audio(clip_path, mixed_out)
                    mixed_paths.append(mixed_out)
                    results.append({"shot_id": sid, "mixed": True, "source": "video+audio"})
                except Exception as e:
                    update_task(task.task_id, status=TaskStatus.ERROR,
                                message=f"镜头 {sid} 混音失败: {e}",
                                result={"mixed": results})
                    return
            else:
                update_task(task.task_id, status=TaskStatus.ERROR,
                            message=f"镜头 {sid} 视频文件不存在",
                            result={"mixed": results})
                return

        update_task(task.task_id, status=TaskStatus.RUNNING,
                    progress=80, message="合并所有镜头...",
                    result={"mixed": results})

        output_dir = BASE_DIR / "output"
        output_dir.mkdir(exist_ok=True)
        final_out = output_dir / f"{req.project_id}_ep{req.episode}.mp4"

        try:
            await merge_videos(mixed_paths, final_out)
        except Exception as e:
            update_task(task.task_id, status=TaskStatus.ERROR,
                        message=f"合并失败: {e}", result={"mixed": results})
            return

        video_url = f"/uploads/drama/output/{req.project_id}_ep{req.episode}.mp4"
        merge_project(req.project_id, {"phase": "done", "updated_at": datetime.utcnow().isoformat()})
        update_task(task.task_id, status=TaskStatus.DONE, progress=100,
                    message="合成完毕", result={"video_url": video_url, "mixed": results})

    bg.add_task(_run)
    return {"task_id": task.task_id}


# ── 缓存管理 ──────────────────────────────────────────────

class ClearCacheRequest(BaseModel):
    project_id: str
    scope: str = "all"   # all | script | shots | keyframes | videos | dub

@router.post("/clear-cache")
async def clear_cache(req: ClearCacheRequest):
    cache_dir = _cache_dir(req.project_id)
    prefix_map = {
        "script":     "script_",
        "shots":      "shots_",
        "keyframes":  "kf_",
        "videos":     "vid_",
        "dub":        "dub_",
    }
    if req.scope == "all":
        deleted = [f.unlink() or f.name for f in cache_dir.glob("*.json")]
    else:
        prefix = prefix_map.get(req.scope, "")
        deleted = [f.unlink() or f.name for f in cache_dir.glob(f"{prefix}*.json")]
    return {"cleared": len(deleted), "scope": req.scope}


# ── 任务查询 ──────────────────────────────────────────────

@router.get("/task/{task_id}")
async def get_drama_task(task_id: str):
    t = get_task(task_id)
    if not t:
        raise HTTPException(404, "任务不存在")
    return t
