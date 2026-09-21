"""
口型同步服务 — 使用 Replicate SadTalker API
将静态人脸图片 + 音频 → 生成带口型动画的视频
"""
import asyncio
import base64
import logging
from pathlib import Path

import httpx

from config import settings

REPLICATE_API = "https://api.replicate.com/v1/predictions"
SADTALKER_MODEL = "cjwbw/sadtalker:a519cc0cfebaaeade068b23899165a11ec76aaa1d2b313d40d214f204ec957a3"


def _headers() -> dict:
    return {
        "Authorization": f"Bearer {settings.replicate_api_token}",
        "Content-Type": "application/json",
    }


def _file_to_data_uri(file_path: Path, mime_type: str) -> str:
    """将本地文件转为 data URI"""
    data = file_path.read_bytes()
    b64 = base64.b64encode(data).decode()
    return f"data:{mime_type};base64,{b64}"


async def generate_lipsync_video(
    image_path: Path,
    audio_path: Path,
    output_path: Path,
) -> Path:
    """
    调用 SadTalker 生成口型同步视频

    Args:
        image_path: 人脸图片路径 (PNG/JPG)
        audio_path: 音频文件路径 (MP3/WAV)
        output_path: 输出视频路径

    Returns:
        输出视频路径
    """
    if not settings.replicate_api_token:
        raise RuntimeError("未配置 REPLICATE_API_TOKEN，无法使用口型同步功能")

    image_path = Path(image_path)
    audio_path = Path(audio_path)
    output_path = Path(output_path)
    output_path.parent.mkdir(parents=True, exist_ok=True)

    # 转换为 data URI
    img_ext = image_path.suffix.lower()
    img_mime = "image/png" if img_ext == ".png" else "image/jpeg"
    audio_ext = audio_path.suffix.lower()
    audio_mime = "audio/mpeg" if audio_ext == ".mp3" else "audio/wav"

    source_image = _file_to_data_uri(image_path, img_mime)
    driven_audio = _file_to_data_uri(audio_path, audio_mime)

    payload = {
        "version": SADTALKER_MODEL.split(":")[1],
        "input": {
            "source_image": source_image,
            "driven_audio": driven_audio,
            "preprocess": "crop",  # crop | resize | full
            "still_mode": False,
            "use_enhancer": True,
            "facerender": "facevid2vid",
        }
    }

    async with httpx.AsyncClient(timeout=30) as client:
        logging.warning(f"[AI-CALL][replicate:sadtalker:submit] POST {REPLICATE_API}")
        resp = await client.post(REPLICATE_API, headers=_headers(), json=payload)
        if not resp.is_success:
            logging.error(f"[lipsync] submit error: {resp.text[:500]}")
        resp.raise_for_status()
        prediction = resp.json()
        prediction_id = prediction["id"]
        poll_url = prediction["urls"]["get"]

    # 轮询等待完成
    video_url = await _poll_prediction(poll_url)

    # 下载视频
    async with httpx.AsyncClient(timeout=120) as client:
        logging.warning(f"[AI-CALL][replicate:sadtalker:download] GET {video_url}")
        vid_resp = await client.get(video_url)
        vid_resp.raise_for_status()
        output_path.write_bytes(vid_resp.content)

    return output_path


async def _poll_prediction(poll_url: str, max_wait: int = 600) -> str:
    """轮询 Replicate 预测结果"""
    for _ in range(max_wait // 5):
        await asyncio.sleep(5)
        async with httpx.AsyncClient(timeout=30) as client:
            logging.info(f"[lipsync] polling {poll_url}")
            resp = await client.get(poll_url, headers=_headers())
            resp.raise_for_status()
            data = resp.json()

        status = data.get("status")
        if status == "succeeded":
            output = data.get("output")
            if output:
                return output
            raise RuntimeError(f"SadTalker succeeded but no output: {data}")
        if status == "failed":
            error = data.get("error", "unknown error")
            raise RuntimeError(f"SadTalker failed: {error}")
        if status == "canceled":
            raise RuntimeError("SadTalker task was canceled")

        logging.info(f"[lipsync] status={status}")

    raise TimeoutError(f"SadTalker timed out after {max_wait}s")


async def check_lipsync_available() -> bool:
    """检查口型同步服务是否可用"""
    return bool(settings.replicate_api_token)
