"""
PPT 转视频 — 步进式路由

步骤：
  1. POST /api/ppt/upload        上传 PPTX，解析幻灯片图片 + 文字
  2. POST /api/ppt/gen-scripts   AI 批量生成口播稿
  3. POST /api/ppt/gen-script-page  AI 重新生成单页口播稿
  4. POST /api/ppt/tts           批量生成 TTS 音频（逐页缓存）
  5. POST /api/ppt/tts-page      重新生成单页 TTS
  6. POST /api/ppt/animate       批量生成幻灯片动画视频（逐页缓存）
  7. POST /api/ppt/animate-page  重新生成单页动画
  8. POST /api/ppt/merge         混音 + concat 合并最终视频
  7. GET  /api/ppt/task/{id}     查询任务进度
  8. GET  /api/ppt/status/{fid}  查询 file_id 各步缓存状态
"""
import asyncio
import hashlib
import json
import logging
import shutil
import subprocess
import uuid
import zipfile
from pathlib import Path

import edge_tts
from fastapi import APIRouter, BackgroundTasks, HTTPException, UploadFile, File
from pydantic import BaseModel

from services.task_store import TaskStatus, create_task, get_task, update_task
from services.video_service import slide_to_video_static, mix_audio_into_video, merge_videos
from services.llm_service import generate_ppt_scripts, generate_ppt_script_page

router = APIRouter(prefix="/api/ppt", tags=["ppt"])

BASE_DIR   = Path("uploads/ppt")
OUTPUT_DIR = Path("uploads/ppt_output")
BASE_DIR.mkdir(parents=True, exist_ok=True)
OUTPUT_DIR.mkdir(parents=True, exist_ok=True)


# ── 目录辅助 ──────────────────────────────────────────────

def _proj(file_id: str) -> Path:
    p = BASE_DIR / file_id
    p.mkdir(parents=True, exist_ok=True)
    return p

def _slides_dir(file_id: str) -> Path:
    d = _proj(file_id) / "slides"
    d.mkdir(exist_ok=True)
    return d

def _audio_dir(file_id: str) -> Path:
    d = _proj(file_id) / "audio"
    d.mkdir(exist_ok=True)
    return d

def _anim_dir(file_id: str) -> Path:
    d = _proj(file_id) / "anim"
    d.mkdir(exist_ok=True)
    return d

def _meta_path(file_id: str) -> Path:
    return _proj(file_id) / "cache_meta.json"


# ── 缓存元数据 ────────────────────────────────────────────

def _load_meta(file_id: str) -> dict:
    p = _meta_path(file_id)
    if p.exists():
        try:
            return json.loads(p.read_text())
        except Exception:
            pass
    return {"pages": {}}

def _save_meta(file_id: str, meta: dict):
    _meta_path(file_id).write_text(json.dumps(meta, ensure_ascii=False, indent=2))

def _script_hash(script: str, voice: str) -> str:
    return hashlib.md5(f"{script}|{voice}".encode()).hexdigest()[:12]

def _slide_hash(slide_path: Path) -> str:
    return hashlib.md5(slide_path.read_bytes()).hexdigest()[:12]


# ── PPTX 解析 ─────────────────────────────────────────────

def _parse_pptx(pptx_path: Path) -> list[dict]:
    """用 python-pptx 提取每页标题 + 正文"""
    from pptx import Presentation  # noqa: PLC0415
    prs = Presentation(pptx_path)
    slides = []
    for i, slide in enumerate(prs.slides, start=1):
        title, parts = "", []
        for shape in slide.shapes:
            if not shape.has_text_frame:
                continue
            raw = shape.text_frame.text.strip()
            if not raw:
                continue
            if shape.is_placeholder and shape.placeholder_format.idx == 0:
                title = raw
            else:
                parts.append(raw)
        if slide.has_notes_slide:
            notes = slide.notes_slide.notes_text_frame.text.strip()
            if notes:
                parts.append(f"[备注] {notes}")
        slides.append({"index": i, "title": title, "text": "\n".join(parts)})
    return slides


def _fix_pptx_zip_paths(pptx_path: Path) -> Path:
    """修复 PPTX 内 ZIP 条目中的反斜杠路径，LibreOffice 无法识别反斜杠"""
    needs_fix = False
    with zipfile.ZipFile(pptx_path, 'r') as zin:
        for info in zin.infolist():
            if '\\' in info.filename:
                needs_fix = True
                break
    if not needs_fix:
        return pptx_path

    fixed_path = pptx_path.with_suffix('.fixed.pptx')
    with zipfile.ZipFile(pptx_path, 'r') as zin, \
         zipfile.ZipFile(fixed_path, 'w', zipfile.ZIP_DEFLATED) as zout:
        for info in zin.infolist():
            data = zin.read(info.filename)
            info.filename = info.filename.replace('\\', '/')
            zout.writestr(info, data)
    return fixed_path


def _export_slides(pptx_path: Path, slides_dir: Path, expected: int = 0) -> list[Path]:
    """PPTX → PDF (LibreOffice) → PNG per page (pdftoppm)；失败则生成占位图"""
    soffice   = shutil.which("soffice")   or "soffice"
    pdftoppm  = shutil.which("pdftoppm")  or "pdftoppm"
    pdf_dir   = slides_dir.parent / "pdf"
    pdf_dir.mkdir(exist_ok=True)
    pdf_path  = pdf_dir / f"{pptx_path.stem}.pdf"

    actual_pptx = pptx_path
    try:
        actual_pptx = _fix_pptx_zip_paths(pptx_path)
        r1 = subprocess.run(
            [soffice, "--headless", "--convert-to", "pdf",
             "--outdir", str(pdf_dir), str(actual_pptx.resolve())],
            capture_output=True, text=True, timeout=120,
        )
        if actual_pptx != pptx_path:
            pdf_path = pdf_dir / f"{actual_pptx.stem}.pdf"
        if r1.returncode != 0 or not pdf_path.exists():
            raise RuntimeError(f"soffice PDF 失败: {r1.stderr.strip()}")

        r2 = subprocess.run(
            [pdftoppm, "-r", "150", "-png", str(pdf_path),
             str(slides_dir / "slide")],
            capture_output=True, text=True, timeout=120,
        )
        if r2.returncode != 0:
            raise RuntimeError(f"pdftoppm 失败: {r2.stderr.strip()}")

        # pdftoppm 输出 slide-01.png … slide-NN.png，重命名为 slide_001.png …
        raw = sorted(slides_dir.glob("slide-*.png"))
        renamed = []
        for idx, src in enumerate(raw, start=1):
            dst = slides_dir / f"slide_{idx:03d}.png"
            src.rename(dst)
            renamed.append(dst)

        if renamed and (expected == 0 or len(renamed) == expected):
            return renamed
        logging.warning(f"[ppt] 导出 {len(renamed)} 页，预期 {expected} 页，回退占位图")
    except Exception as e:
        logging.warning(f"[ppt] 导出失败: {e}")
    finally:
        if actual_pptx != pptx_path:
            actual_pptx.unlink(missing_ok=True)

    return _fallback_slides(pptx_path, slides_dir)


def _fallback_slides(pptx_path: Path, slides_dir: Path) -> list[Path]:
    from pptx import Presentation  # noqa: PLC0415
    from PIL import Image, ImageDraw  # noqa: PLC0415
    prs = Presentation(pptx_path)
    paths = []
    for i, slide in enumerate(prs.slides, start=1):
        title = ""
        for shape in slide.shapes:
            if shape.has_text_frame and shape.is_placeholder and shape.placeholder_format.idx == 0:
                title = shape.text_frame.text.strip()
                break
        img = Image.new("RGB", (1920, 1080), (240, 240, 245))
        draw = ImageDraw.Draw(img)
        draw.text((960, 540), title or f"Slide {i}", fill=(50, 50, 50), anchor="mm")
        out = slides_dir / f"slide_{i:03d}.png"
        img.save(out)
        paths.append(out)
    return paths


# ── Step 1: 上传 & 解析 ───────────────────────────────────

@router.post("/upload")
async def upload_pptx(file: UploadFile = File(...)):
    if not file.filename.lower().endswith((".pptx", ".ppt")):
        raise HTTPException(400, "仅支持 .pptx / .ppt 文件")

    file_id   = str(uuid.uuid4())
    pptx_path = BASE_DIR / f"{file_id}.pptx"
    with pptx_path.open("wb") as f:
        shutil.copyfileobj(file.file, f)

    slides_dir = _slides_dir(file_id)

    # 解析文字
    try:
        slides_text = _parse_pptx(pptx_path)
    except Exception as e:
        raise HTTPException(500, f"PPTX 解析失败: {e}")

    # 导出图片（已有则跳过）
    expected = len(slides_text)
    existing = sorted(slides_dir.glob("slide_*.png"))
    if len(existing) != expected:
        _export_slides(pptx_path, slides_dir, expected=expected)

    # 补全仍缺失的页（LibreOffice 部分导出时兜底）
    for s in slides_text:
        png = slides_dir / f"slide_{s['index']:03d}.png"
        if not png.exists():
            logging.warning(f"[ppt] slide_{s['index']:03d}.png 缺失，生成占位图")
            try:
                from PIL import Image, ImageDraw  # noqa: PLC0415
                img = Image.new("RGB", (1920, 1080), (240, 240, 245))
                draw = ImageDraw.Draw(img)
                draw.text((960, 540), s.get("title") or f"Slide {s['index']}",
                          fill=(50, 50, 50), anchor="mm")
                png.parent.mkdir(parents=True, exist_ok=True)
                img.save(png)
            except Exception as e:
                logging.error(f"[ppt] 占位图生成失败: {e}")

    slide_images = sorted(slides_dir.glob("slide_*.png"))
    slides_out = []
    for s in slides_text:
        img_url = f"/uploads/ppt/{file_id}/slides/slide_{s['index']:03d}.png"
        slides_out.append({**s, "image_url": img_url})

    return {
        "file_id":     file_id,
        "filename":    file.filename,
        "slide_count": len(slides_out),
        "slides":      slides_out,
    }


# ── Step 2: AI 生成口播稿 ─────────────────────────────────

class GenScriptsRequest(BaseModel):
    file_id: str
    slides:  list[dict]   # [{index, title, text}]

@router.post("/gen-scripts")
async def gen_scripts(req: GenScriptsRequest):
    try:
        scripts = await generate_ppt_scripts(req.slides)
    except Exception as e:
        raise HTTPException(500, f"口播稿生成失败: {e}")
    return {"scripts": scripts}


class GenScriptPageRequest(BaseModel):
    file_id: str
    slide:   dict   # {index, title, text}

@router.post("/gen-script-page")
async def gen_script_page(req: GenScriptPageRequest):
    try:
        script = await generate_ppt_script_page(req.slide)
    except Exception as e:
        raise HTTPException(500, f"口播稿生成失败: {e}")
    return {"page": req.slide.get("index"), "script": script}


# ── Step 3: 批量 TTS ──────────────────────────────────────

class TTSRequest(BaseModel):
    file_id: str
    pages:   list[dict]   # [{page, script}]
    voice:   str = "zh-CN-XiaoxiaoNeural"

@router.post("/tts")
async def generate_tts(req: TTSRequest, bg: BackgroundTasks):
    task = create_task()

    async def _run():
        meta  = _load_meta(req.file_id)
        total = len(req.pages)
        done  = 0
        results = []
        failed = []

        for item in req.pages:
            page   = item["page"]
            script = item.get("script", "").strip()
            if not script:
                results.append({"page": page, "skipped": True})
                done += 1
                continue

            s_hash    = _script_hash(script, req.voice)
            audio_out = _audio_dir(req.file_id) / f"page_{page:03d}.mp3"
            cached_hash = meta.get("pages", {}).get(str(page), {}).get("tts_hash")

            if audio_out.exists() and cached_hash == s_hash:
                logging.info(f"[ppt/tts] page {page} cache hit")
                results.append({"page": page, "audio_url": f"/uploads/ppt/{req.file_id}/audio/page_{page:03d}.mp3", "from_cache": True})
            else:
                update_task(task.task_id, status=TaskStatus.RUNNING,
                            progress=int(done / total * 90),
                            message=f"生成第 {page} 页音频...")
                try:
                    comm = edge_tts.Communicate(text=script, voice=req.voice)
                    await comm.save(str(audio_out))
                    meta.setdefault("pages", {}).setdefault(str(page), {})
                    meta["pages"][str(page)]["tts_hash"]  = s_hash
                    meta["pages"][str(page)]["voice"]     = req.voice
                    meta["pages"][str(page)]["tts_done"]  = True
                    meta["pages"][str(page)].pop("mixed_done", None)
                    _save_meta(req.file_id, meta)
                    results.append({"page": page, "audio_url": f"/uploads/ppt/{req.file_id}/audio/page_{page:03d}.mp3", "from_cache": False})
                except Exception as e:
                    logging.error(f"[ppt/tts] page {page} 失败: {e}")
                    failed.append({"page": page, "error": str(e)})
                    results.append({"page": page, "error": str(e)})

            done += 1
            update_task(task.task_id, status=TaskStatus.RUNNING,
                        progress=int(done / total * 95),
                        message=f"已完成 {done}/{total} 页音频",
                        result={"pages": results, "failed": failed})

        if failed:
            pages_str = ", ".join(str(f["page"]) for f in failed)
            update_task(task.task_id, status=TaskStatus.ERROR,
                        progress=100,
                        message=f"第 {pages_str} 页音频生成失败，其余页已完成",
                        result={"pages": results, "failed": failed})
        else:
            update_task(task.task_id, status=TaskStatus.DONE, progress=100,
                        message="TTS 全部完成", result={"pages": results, "failed": []})

    bg.add_task(_run)
    return {"task_id": task.task_id}


# ── 单页重新生成 TTS ──────────────────────────────────────

class TTSPageRequest(BaseModel):
    file_id: str
    page:    int
    script:  str
    voice:   str = "zh-CN-XiaoxiaoNeural"

@router.post("/tts-page")
async def regen_tts_page(req: TTSPageRequest):
    script = req.script.strip()
    if not script:
        raise HTTPException(400, "讲稿不能为空")

    audio_out = _audio_dir(req.file_id) / f"page_{req.page:03d}.mp3"
    try:
        comm = edge_tts.Communicate(text=script, voice=req.voice)
        await comm.save(str(audio_out))
    except Exception as e:
        raise HTTPException(500, f"TTS 生成失败: {e}")

    meta = _load_meta(req.file_id)
    s_hash = _script_hash(script, req.voice)
    meta.setdefault("pages", {}).setdefault(str(req.page), {})
    meta["pages"][str(req.page)]["tts_hash"] = s_hash
    meta["pages"][str(req.page)]["voice"]    = req.voice
    meta["pages"][str(req.page)]["tts_done"] = True
    meta["pages"][str(req.page)].pop("mixed_done", None)
    _save_meta(req.file_id, meta)

    return {"page": req.page, "audio_url": f"/uploads/ppt/{req.file_id}/audio/page_{req.page:03d}.mp3"}


# ── Step 3: 批量幻灯片动画 ────────────────────────────────

class AnimateRequest(BaseModel):
    file_id:  str
    pages:    list[int]   # 页码列表
    duration: int = 8     # 每页基础时长（秒），mix_audio 会按实际音频截断

@router.post("/animate")
async def animate_slides(req: AnimateRequest, bg: BackgroundTasks):
    task = create_task()

    async def _run():
        meta    = _load_meta(req.file_id)
        total   = len(req.pages)
        results = [None] * total   # 按原始顺序占位
        failed  = []
        done_count = 0
        sem = asyncio.Semaphore(3)
        meta_lock = asyncio.Lock()

        async def _process(idx: int, page: int):
            nonlocal done_count

            slide_path = _slides_dir(req.file_id) / f"slide_{page:03d}.png"
            if not slide_path.exists():
                logging.error(f"[ppt/anim] page {page} 幻灯片图片不存在")
                results[idx] = {"page": page, "error": "幻灯片图片不存在"}
                failed.append({"page": page, "error": "幻灯片图片不存在"})
            else:
                s_hash      = _slide_hash(slide_path)
                anim_out    = _anim_dir(req.file_id) / f"page_{page:03d}.mp4"
                cached_hash = meta.get("pages", {}).get(str(page), {}).get("anim_hash")

                if anim_out.exists() and cached_hash == s_hash:
                    logging.info(f"[ppt/anim] page {page} cache hit")
                    results[idx] = {"page": page, "anim_url": f"/uploads/ppt/{req.file_id}/anim/page_{page:03d}.mp4", "from_cache": True}
                else:
                    async with sem:
                        try:
                            await slide_to_video_static(slide_path, anim_out, duration=req.duration)
                            async with meta_lock:
                                meta.setdefault("pages", {}).setdefault(str(page), {})
                                meta["pages"][str(page)]["anim_hash"] = s_hash
                                meta["pages"][str(page)]["anim_done"] = True
                                meta["pages"][str(page)].pop("mixed_done", None)
                                _save_meta(req.file_id, meta)
                            results[idx] = {"page": page, "anim_url": f"/uploads/ppt/{req.file_id}/anim/page_{page:03d}.mp4", "from_cache": False}
                        except Exception as e:
                            logging.error(f"[ppt/anim] page {page} 失败: {e}")
                            results[idx] = {"page": page, "error": str(e)}
                            failed.append({"page": page, "error": str(e)})

            done_count += 1
            current = [r for r in results if r is not None]
            update_task(task.task_id, status=TaskStatus.RUNNING,
                        progress=int(done_count / total * 95),
                        message=f"已完成 {done_count}/{total} 页动画",
                        result={"pages": current, "failed": failed})

        await asyncio.gather(*[_process(i, page) for i, page in enumerate(req.pages)])

        final = [r for r in results if r is not None]
        if failed:
            pages_str = ", ".join(str(f["page"]) for f in failed)
            update_task(task.task_id, status=TaskStatus.ERROR,
                        progress=100,
                        message=f"第 {pages_str} 页动画生成失败，其余页已完成",
                        result={"pages": final, "failed": failed})
        else:
            update_task(task.task_id, status=TaskStatus.DONE, progress=100,
                        message="动画全部完成", result={"pages": final, "failed": []})

    bg.add_task(_run)
    return {"task_id": task.task_id}


# ── 单页重新生成动画 ──────────────────────────────────────

class AnimatePageRequest(BaseModel):
    file_id:  str
    page:     int
    duration: int = 8

@router.post("/animate-page")
async def regen_animate_page(req: AnimatePageRequest):
    slide_path = _slides_dir(req.file_id) / f"slide_{req.page:03d}.png"
    if not slide_path.exists():
        raise HTTPException(404, "幻灯片图片不存在")

    anim_out = _anim_dir(req.file_id) / f"page_{req.page:03d}.mp4"
    try:
        await slide_to_video_static(slide_path, anim_out, duration=req.duration)
    except Exception as e:
        raise HTTPException(500, f"动画生成失败: {e}")

    meta = _load_meta(req.file_id)
    meta.setdefault("pages", {}).setdefault(str(req.page), {})
    meta["pages"][str(req.page)]["anim_hash"] = _slide_hash(slide_path)
    meta["pages"][str(req.page)]["anim_done"] = True
    meta["pages"][str(req.page)].pop("mixed_done", None)
    _save_meta(req.file_id, meta)

    return {"page": req.page, "anim_url": f"/uploads/ppt/{req.file_id}/anim/page_{req.page:03d}.mp4"}


# ── Step 4: 混音 + 合并 ───────────────────────────────────

class MergeRequest(BaseModel):
    file_id: str
    pages:   list[int]

@router.post("/merge")
async def merge_ppt_video(req: MergeRequest, bg: BackgroundTasks):
    task = create_task()

    async def _run():
        mixed_dir = _proj(req.file_id) / "mixed"
        mixed_dir.mkdir(exist_ok=True)
        total = len(req.pages)
        mixed_paths = []
        results = []

        for idx, page in enumerate(req.pages):
            anim_path  = _anim_dir(req.file_id) / f"page_{page:03d}.mp4"
            audio_path = _audio_dir(req.file_id) / f"page_{page:03d}.mp3"
            mixed_out  = mixed_dir / f"page_{page:03d}.mp4"

            if not anim_path.exists():
                update_task(task.task_id, status=TaskStatus.ERROR,
                            message=f"第 {page} 页动画文件不存在，请先生成动画",
                            result={"pages": results})
                return
            if not audio_path.exists():
                update_task(task.task_id, status=TaskStatus.ERROR,
                            message=f"第 {page} 页音频文件不存在，请先生成 TTS",
                            result={"pages": results})
                return

            update_task(task.task_id, status=TaskStatus.RUNNING,
                        progress=int(idx / total * 80),
                        message=f"混音第 {page} 页... ({idx + 1}/{total})",
                        result={"pages": results})
            try:
                await mix_audio_into_video(anim_path, audio_path, mixed_out)
            except Exception as e:
                update_task(task.task_id, status=TaskStatus.ERROR,
                            message=f"第 {page} 页混音失败: {e}",
                            result={"pages": results})
                return
            mixed_paths.append(mixed_out)
            results.append({"page": page, "mixed": True})
            update_task(task.task_id, status=TaskStatus.RUNNING,
                        progress=int((idx + 1) / total * 80),
                        message=f"已混音 {idx + 1}/{total} 页",
                        result={"pages": results})

        update_task(task.task_id, status=TaskStatus.RUNNING,
                    progress=85, message="合并所有页面...")
        final_out = OUTPUT_DIR / f"{req.file_id}.mp4"
        try:
            await merge_videos(mixed_paths, final_out)
        except Exception as e:
            update_task(task.task_id, status=TaskStatus.ERROR,
                        message=f"合并失败: {e}")
            return

        video_url = f"/uploads/ppt_output/{req.file_id}.mp4"
        update_task(task.task_id, status=TaskStatus.DONE, progress=100,
                    message="视频合成完毕",
                    result={"video_url": video_url})

    bg.add_task(_run)
    return {"task_id": task.task_id}


# ── 查询任务 ──────────────────────────────────────────────

@router.get("/task/{task_id}")
async def get_ppt_task(task_id: str):
    t = get_task(task_id)
    if not t:
        raise HTTPException(404, "任务不存在")
    return t


# ── 查询缓存状态 ──────────────────────────────────────────

@router.get("/status/{file_id}")
async def get_ppt_status(file_id: str):
    meta = _load_meta(file_id)
    pages_status = {}
    for page_str, info in meta.get("pages", {}).items():
        page = int(page_str)
        audio_path = _audio_dir(file_id) / f"page_{page:03d}.mp3"
        anim_path  = _anim_dir(file_id)  / f"page_{page:03d}.mp4"
        pages_status[page] = {
            "tts_done":  audio_path.exists() and info.get("tts_done", False),
            "anim_done": anim_path.exists()  and info.get("anim_done", False),
            "voice":     info.get("voice", ""),
        }
    final_path = OUTPUT_DIR / f"{file_id}.mp4"
    return {
        "file_id":    file_id,
        "pages":      pages_status,
        "final_done": final_path.exists(),
        "final_url":  f"/uploads/ppt_output/{file_id}.mp4" if final_path.exists() else None,
    }
