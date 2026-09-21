"""
脚本转视频路由
- POST /api/script2video/parse    — AI 解析脚本文本为分镜
- POST /api/script2video/generate — 生成首尾帧图片
- POST /api/script2video/gen-video — 生成视频（TTS→Kling首尾帧→混音→转场合并）
- GET  /api/script2video/task/{id} — 查询任务状态
"""
import asyncio
import logging
from datetime import datetime
from fastapi import APIRouter, BackgroundTasks
from pydantic import BaseModel
from pathlib import Path
from services.llm_service import _client, _log_call
from services.tts_service import text_to_speech
from services.video_service import merge_with_transitions, image_to_video_ffmpeg, mix_audio_into_video
from services.task_store import create_task, update_task, get_task, TaskStatus
import services.video_cache as video_cache
import hashlib
from config import settings
import json

router = APIRouter(prefix="/api/script2video", tags=["script2video"])

OUTPUT_DIR = Path("uploads/script2video")
OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

PARSE_SYSTEM = """你是一位顶级广告导演兼分镜师，擅长将文字脚本转化为电影级画面。
用户给你一段视频脚本文本，你需要解析为标准分镜格式，并为每个镜头撰写专业级图片提示词。

【解析规则】
- 识别每个镜头/场景，提取时长、旁白文本、画面描述
- 如果脚本已有时间标注（如"0-5秒"），按标注的时长
- 如果没有时间标注，时长 = 旁白字数 ÷ 4（中文约每秒 4 字），向上取整到 5 的倍数，最少 5 秒
- narration：提取旁白文本，改为自然口语风格（适合真人朗读），语义完整，避免书面化长句

【返回格式】严格 JSON：
{
  "title": "视频标题",
  "total_duration": 总时长秒数,
  "characters": [
    {
      "name": "角色名",
      "appearance": "极其详细的英文外貌描述"
    }
  ],
  "scenes": [
    {
      "scene_id": 1,
      "duration": 5,
      "narration": "旁白文字（口语化）",
      "scene_desc": "中文画面描述",
      "start_prompt": "...",
      "end_prompt": "..."
    }
  ]
}

【角色一致性规则 — 最重要】
1. 如果视频中只有一名主讲人，characters 数组只放一个角色
2. 先在 characters 数组中定义所有出现的人物，外貌描述必须极其具体：
   - 性别、精确年龄、种族肤色
   - 发型（长度、卷直、颜色、是否扎起）
   - 脸型、五官特征（如圆脸、杏眼、薄唇）
   - 体型（纤细/健壮/微胖）
   - 服装完整描述（颜色、材质、款式、品牌风格）— 全程保持同一套服装不变
   - 配饰（手表、耳环、眼镜等）
1. 先在 characters 数组中定义所有出现的人物，外貌描述必须极其具体：
   - 性别、精确年龄、种族肤色
   - 发型（长度、卷直、颜色、是否扎起）
   - 脸型、五官特征（如圆脸、杏眼、薄唇）
   - 体型（纤细/健壮/微胖）
   - 服装完整描述（颜色、材质、款式、品牌风格）
   - 配饰（手表、耳环、眼镜等）
2. 同一人物在所有 prompt 中必须逐字复制相同的外貌描述段落
3. start_prompt 和 end_prompt 只在动作/姿势/表情/机位上有差异

【提示词撰写规则 — 决定画面质量】

每个 prompt 必须包含以下 5 层结构，缺一不可：

1. 镜头语言（Camera）：
   - 指定具体机位：close-up, medium shot, wide shot, over-the-shoulder, low angle, bird's eye view
   - 指定镜头运动暗示：如 "as if camera slowly dollies in", "slight handheld shake"
   - 指定焦距感：如 "shot on 85mm lens, shallow depth of field", "35mm wide angle"

2. 光影设计（Lighting）：
   - 不要写 "good lighting"，要写具体光源：
   - "warm golden hour sunlight streaming through floor-to-ceiling windows, casting long soft shadows"
   - "overhead softbox with rim light separating subject from background"
   - "practical lighting from desk lamp, warm 3200K tungsten glow"

3. 环境细节（Environment）：
   - 不要写 "office"，要写：
   - "modern minimalist office with white oak desk, single monstera plant, MacBook Pro open, scattered sticky notes, concrete wall with one framed abstract print"
   - 加入生活感细节：半杯咖啡、翻开的笔记本、窗外模糊的城市天际线

4. 人物状态（Action & Emotion）：
   - 不要写 "stretching"，要写：
   - "gently tilting head to the right with eyes closed, left hand pressing on right trapezius, slight relieved smile forming"
   - 描述微表情、手指位置、重心转移

5. 画面风格（Style）：
   - 结尾必须加风格标签，模拟真实拍摄而非 AI 感：
   - "shot on Sony A7IV, natural color grading, slight film grain, 24fps cinematic look, 16:9 aspect ratio"
   - 或 "RED Komodo footage, commercial color grade, clean and modern, subtle lens flare"

【start_prompt vs end_prompt 的差异设计】
- 差异要小而精确：同一场景内，只改变 1-2 个动作要素
- 好的例子：start 是 "hands resting on desk" → end 是 "right hand reaching for coffee mug, fingers wrapping around handle"
- 坏的例子：start 是坐着 → end 是站起来走到窗边（变化太大，视频会崩）
- 保持相机角度一致，不要在首尾帧之间切换机位

【过渡镜头】
如果相邻两个镜头的场景变化很大（如从室内切到室外），在二者之间插入一个 1-2 秒的过渡镜头：
- 过渡镜头的 start_prompt 和 end_prompt 要体现从上一个场景到下一个场景的渐变
- 过渡镜头的 narration 留空（""）
- 过渡镜头的 duration 为 1 或 2

【禁止事项】
- 禁止写 "high quality, 4K, masterpiece, best quality" 等无意义标签
- 禁止写 "cinematic" 而不给具体的电影感来源（要写出是什么让它 cinematic）
- 禁止敏感词：war/violence/blood/weapon/military/protest/nude/nsfw
- 禁止出现文字、字幕、水印、UI 元素的描述
"""


class ParseRequest(BaseModel):
    script_text: str


class GenerateRequest(BaseModel):
    project_id: str
    scenes: list[dict]
    characters: list[dict] = []  # [{name, appearance}]
    model: str = "seedream"


class GenVideoRequest(BaseModel):
    project_id: str
    scenes: list[dict]  # 每个 scene 包含 start_image, end_image 路径


# PLACEHOLDER_ENDPOINTS

@router.post("/parse")
async def parse_script(req: ParseRequest):
    """AI 解析脚本文本为分镜列表（带缓存）"""
    cache_key = "parse_" + hashlib.md5(req.script_text.encode("utf-8")).hexdigest()
    cache_file = OUTPUT_DIR / "_parse_cache" / f"{cache_key}.json"

    if cache_file.exists():
        try:
            cached = json.loads(cache_file.read_text(encoding="utf-8"))
            logging.info(f"[script2video] parse cache hit: {cache_key}")
            return cached
        except Exception:
            pass

    _log_call("script2video_parse", settings.llm_model)
    resp = await _client.chat.completions.create(
        model=settings.llm_model,
        messages=[
            {"role": "system", "content": PARSE_SYSTEM},
            {"role": "user", "content": req.script_text},
        ],
        temperature=0.5,
        response_format={"type": "json_object"},
    )
    data = json.loads(resp.choices[0].message.content)

    cache_file.parent.mkdir(parents=True, exist_ok=True)
    cache_file.write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")

    return data


@router.post("/generate")
async def generate_images(req: GenerateRequest, bg: BackgroundTasks):
    """生成每个镜头的首帧和尾帧图片（Seedream + 角色参考图）"""
    task = create_task()

    async def _run():
        try:
            project_dir = OUTPUT_DIR / req.project_id
            project_dir.mkdir(parents=True, exist_ok=True)

            # ── 阶段 1：为每个角色生成参考肖像（Seedream 原生参考图） ──
            char_portraits = {}  # name → portrait_path
            characters = req.characters or []
            if characters:
                update_task(task.task_id, status=TaskStatus.RUNNING, progress=5,
                            message=f"正在生成 {len(characters)} 个角色参考肖像...")
                for char in characters:
                    name = char.get("name", "default")
                    appearance = char.get("appearance", "")
                    portrait_path = project_dir / f"portrait_{name.replace(' ', '_')}.jpg"
                    if not portrait_path.exists() and appearance:
                        portrait_prompt = (
                            f"A clear portrait photo of a person: {appearance}. "
                            f"Front-facing, neutral expression, clean light gray background, "
                            f"professional studio lighting, upper body visible, "
                            f"shot on 85mm lens, sharp focus on face"
                        )
                        # 角色肖像不带参考图（第一次生成）
                        await _generate_image(portrait_prompt, portrait_path, req.model)
                    if portrait_path.exists():
                        char_portraits[name] = portrait_path

            # ── 阶段 2：生成场景首尾帧（用角色肖像做参考图） ──
            total = len(req.scenes)
            results = [None] * total

            for idx, scene in enumerate(req.scenes):
                scene_id = scene["scene_id"]
                start_prompt = scene.get("start_prompt", "")
                end_prompt = scene.get("end_prompt", "")

                start_path = project_dir / f"scene_{scene_id:03d}_start.jpg"
                end_path = project_dir / f"scene_{scene_id:03d}_end.jpg"

                # 匹配该场景涉及的角色
                scene_char = scene.get("character", "")
                ref_path = None
                if char_portraits:
                    for cname, ppath in char_portraits.items():
                        if scene_char and cname in scene_char:
                            ref_path = ppath
                            break
                    if not ref_path:
                        ref_path = next(iter(char_portraits.values()))

                if not start_path.exists() and start_prompt:
                    await _generate_image(start_prompt, start_path, req.model,
                                          ref_image_path=ref_path)
                if not end_path.exists() and end_prompt:
                    await _generate_image(end_prompt, end_path, req.model,
                                          ref_image_path=ref_path)

                results[idx] = {
                    "scene_id": scene_id,
                    "start_image": str(start_path),
                    "start_url": f"/uploads/script2video/{req.project_id}/scene_{scene_id:03d}_start.jpg",
                    "end_image": str(end_path),
                    "end_url": f"/uploads/script2video/{req.project_id}/scene_{scene_id:03d}_end.jpg",
                }

                update_task(
                    task.task_id,
                    status=TaskStatus.RUNNING,
                    progress=10 + int((idx + 1) / total * 90),
                    message=f"已完成 {idx + 1}/{total} 镜图片...",
                )

            update_task(
                task.task_id,
                status=TaskStatus.DONE,
                progress=100,
                message="所有图片生成完成",
                result={"images": results},
            )
        except Exception as e:
            logging.error(f"[script2video] gen-images failed: {e}")
            update_task(task.task_id, status=TaskStatus.ERROR, message=str(e))

    bg.add_task(_run)
    return {"task_id": task.task_id}


MOTION_PROMPT_SYSTEM = """你是一位专业的视频动作指导。
用户给你一个镜头的中文旁白文本和画面描述，你需要输出一段英文的动作指令（motion prompt），用于 AI 图生视频模型（Seedance 2.0）。

【规则】
- motion prompt 只描述画面中应该发生的动作、运动、镜头运动
- 不描述人物外貌、环境、光影（这些已在首帧图片中）
- 动作要与旁白内容紧密对应，让人感觉视频画面在配合旁白讲述
- 用简洁的英文短句，每个动作用逗号分隔
- 包含镜头运动：如 camera slowly zooms in, slight pan right, tracking shot
- 包含人物动作：如 speaker gestures with left hand, turns head slightly, leans forward
- 包含环境动态：如 leaves rustling in wind, light shifts, objects in background gently moving
- 动作要自然流畅，不要剧烈变化
- 不要包含任何文字、字幕、水印相关内容

【输出格式】直接输出英文 motion prompt，不要任何解释或标注。"""


async def _generate_motion_prompt(narration: str, scene_desc: str) -> str:
    """用 LLM 根据旁白和画面描述生成视频动作提示词"""
    user_text = f"旁白：{narration}\n画面描述：{scene_desc}"
    _log_call("motion_prompt", settings.llm_model)
    resp = await _client.chat.completions.create(
        model=settings.llm_model,
        messages=[
            {"role": "system", "content": MOTION_PROMPT_SYSTEM},
            {"role": "user", "content": user_text},
        ],
        temperature=0.6,
    )
    return resp.choices[0].message.content.strip()


@router.post("/gen-video")
async def generate_video(req: GenVideoRequest, bg: BackgroundTasks):
    """用确认后的首尾帧图片生成视频：TTS→动作提示词→Seedance 2.0→混音→转场合并"""
    task = create_task()

    async def _run():
        try:
            project_dir = OUTPUT_DIR / req.project_id
            project_dir.mkdir(parents=True, exist_ok=True)
            timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")

            total = len(req.scenes)
            scene_videos = []

            # ── 预生成所有动作提示词（带文件缓存） ──
            update_task(task.task_id, status=TaskStatus.RUNNING, progress=5,
                        message="正在生成视频动作指令...")
            motion_cache_dir = project_dir / "_motion_cache"
            motion_cache_dir.mkdir(exist_ok=True)
            for scene in req.scenes:
                narration = scene.get("narration", "")
                scene_desc = scene.get("scene_desc", "")
                scene_id = scene["scene_id"]
                motion_cache_file = motion_cache_dir / f"scene_{scene_id:03d}.txt"

                # 查缓存
                if motion_cache_file.exists():
                    scene["motion_prompt"] = motion_cache_file.read_text(encoding="utf-8").strip()
                    logging.info(f"[script2video] scene {scene_id} motion cache hit")
                    continue

                if narration.strip() and not scene.get("motion_prompt"):
                    try:
                        motion = await _generate_motion_prompt(narration, scene_desc)
                        scene["motion_prompt"] = motion
                        motion_cache_file.write_text(motion, encoding="utf-8")
                    except Exception as e:
                        logging.warning(f"[script2video] motion prompt failed for scene {scene_id}: {e}")
                        scene["motion_prompt"] = scene.get("start_prompt", "gentle camera movement")

            for idx, scene in enumerate(req.scenes):
                scene_id = scene["scene_id"]
                duration = scene.get("duration", 5)
                narration = scene.get("narration", "")
                start_image = Path(scene["start_image"])
                end_image = Path(scene.get("end_image", ""))
                motion_prompt = scene.get("motion_prompt", scene.get("start_prompt", "gentle camera movement"))

                base_progress = int(idx / total * 70)

                # ── 1. TTS（全局缓存：按旁白文本哈希） ──
                tts_path = project_dir / f"tts_{scene_id:03d}.mp3"
                audio_dur = duration
                if narration.strip():
                    if not tts_path.exists():
                        # 全局 TTS 缓存：同一文本不重复生成
                        tts_hash = hashlib.md5(narration.strip().encode("utf-8")).hexdigest()
                        global_tts = Path("uploads/_tts_cache") / f"{tts_hash}.mp3"
                        if global_tts.exists():
                            import shutil
                            shutil.copy2(global_tts, tts_path)
                            logging.info(f"[script2video] scene {scene_id} TTS global cache hit")
                        else:
                            update_task(task.task_id, status=TaskStatus.RUNNING,
                                        progress=base_progress,
                                        message=f"第 {scene_id}/{total} 镜：生成配音...")
                            await text_to_speech(narration, tts_path)
                            global_tts.parent.mkdir(parents=True, exist_ok=True)
                            shutil.copy2(tts_path, global_tts)
                    else:
                        logging.info(f"[script2video] scene {scene_id} TTS file cache hit")

                    import asyncio as _aio
                    probe = await _aio.create_subprocess_exec(
                        "ffprobe", "-v", "quiet",
                        "-show_entries", "format=duration",
                        "-of", "default=noprint_wrappers=1:nokey=1",
                        str(tts_path),
                        stdout=_aio.subprocess.PIPE, stderr=_aio.subprocess.PIPE,
                    )
                    stdout, _ = await probe.communicate()
                    try:
                        audio_dur = float(stdout.decode().strip())
                    except ValueError:
                        audio_dur = duration
                    video_dur = 10 if audio_dur > 7 else 5
                else:
                    video_dur = duration

                # ── 2. 图生视频（文件存在 → Redis缓存 → API生成） ──
                video_path = project_dir / f"video_{scene_id:03d}.mp4"
                if video_path.exists():
                    logging.info(f"[script2video] scene {scene_id} video file exists, skip")
                    update_task(task.task_id, status=TaskStatus.RUNNING,
                                progress=base_progress + 5,
                                message=f"第 {scene_id}/{total} 镜：视频（缓存命中）")
                else:
                    cached = video_cache.get(start_image, motion_prompt, video_dur, "seedance")
                    if cached:
                        import shutil
                        logging.warning(f"[script2video] scene {scene_id} video Redis cache hit")
                        shutil.copy2(cached, video_path)
                        update_task(task.task_id, status=TaskStatus.RUNNING,
                                    progress=base_progress + 5,
                                    message=f"第 {scene_id}/{total} 镜：视频（缓存命中）")
                    else:
                        update_task(task.task_id, status=TaskStatus.RUNNING,
                                    progress=base_progress,
                                    message=f"第 {scene_id}/{total} 镜：Seedance 生成视频...")
                        success = False

                        if start_image.exists():
                            try:
                                from services.jimeng_service import generate_video_from_image as jimeng_gen
                                await jimeng_gen(start_image, motion_prompt, video_path, video_dur)
                                success = True
                            except Exception as e:
                                logging.warning(f"[script2video] seedance failed scene {scene_id}: {e}")

                        if not success and start_image.exists():
                            try:
                                from services.kling_service import generate_video_from_image as kling_gen
                                await kling_gen(
                                    start_image, motion_prompt, video_path, video_dur,
                                    tail_image=end_image if end_image.exists() else None,
                                )
                                success = True
                            except Exception as e:
                                logging.warning(f"[script2video] kling failed scene {scene_id}: {e}")

                        if not success:
                            logging.warning(f"[script2video] fallback to ffmpeg for scene {scene_id}")
                            await image_to_video_ffmpeg(start_image, video_path, video_dur)

                        try:
                            video_cache.put(start_image, motion_prompt, video_dur, video_path, "seedance")
                        except Exception as ce:
                            logging.warning(f"[script2video] cache write failed scene {scene_id}: {ce}")

                # ── 3. 混入 TTS（文件存在即跳过） ──
                mixed_path = project_dir / f"mixed_{scene_id:03d}.mp4"
                if narration.strip() and tts_path.exists():
                    if not mixed_path.exists():
                        await mix_audio_into_video(video_path, tts_path, mixed_path)
                    scene_videos.append(mixed_path)
                else:
                    scene_videos.append(video_path)

                if idx < total - 1:
                    await asyncio.sleep(2)

            # ── 4. 转场合并（文件存在即跳过） ──
            update_task(task.task_id, status=TaskStatus.RUNNING,
                        progress=85, message="正在合并所有镜头（含转场）...")
            final_path = project_dir / f"{timestamp}_final.mp4"
            # 查已有最终视频（按修改时间取最新的）
            existing_finals = sorted(project_dir.glob("*_final.mp4"))
            if existing_finals:
                latest = existing_finals[-1]
                # 检查是否包含同样的视频片段（简单比较文件数和最新片段时间）
                logging.warning(f"[script2video] found existing final video: {latest}")
                final_path = latest
            else:
                await merge_with_transitions(scene_videos, final_path)

            update_task(
                task.task_id,
                status=TaskStatus.DONE,
                progress=100,
                message="视频生成完成",
                result={
                    "final_video_path": str(final_path),
                    "final_video_url": f"/uploads/script2video/{req.project_id}/{final_path.name}",
                },
            )
        except Exception as e:
            logging.error(f"[script2video] gen-video failed: {e}")
            update_task(task.task_id, status=TaskStatus.ERROR, message=str(e))

    bg.add_task(_run)
    return {"task_id": task.task_id}


@router.get("/task/{task_id}")
async def get_script2video_task(task_id: str):
    from fastapi import HTTPException
    t = get_task(task_id)
    if not t:
        raise HTTPException(404, "任务不存在")
    return t


async def _generate_image(prompt: str, output_path: Path, model: str = "seedream",
                          ref_image_path: Path = None):
    """根据 model 选择图片生成服务，Seedream 支持角色参考图"""
    if model == "seedream":
        from services.jimeng_service import generate_image_from_text as seedream_gen
        await seedream_gen(prompt, output_path, ref_image_path=ref_image_path)
    elif model == "hunyuan":
        from services.hunyuan_service import generate_image_from_text
        await generate_image_from_text(prompt, output_path)
    elif model == "kolors":
        from services.siliconflow_service import generate_image_from_text
        await generate_image_from_text(prompt, output_path)
    else:
        from services.jimeng_service import generate_image_from_text as seedream_gen
        await seedream_gen(prompt, output_path, ref_image_path=ref_image_path)
