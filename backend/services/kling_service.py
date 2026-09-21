"""
Kling AI (可灵) 服务层
支持:
  - 图生视频 (image-to-video)
  - 文生图 (text-to-image) via Kling Image API

鉴权: JWT HS256 Bearer Token
  header: {"alg":"HS256","typ":"JWT"}
  payload: {"iss": access_key, "exp": now+1800, "nbf": now-5}
"""
import time
import asyncio
import base64
import io
import logging
import httpx
import jwt
from pathlib import Path
from PIL import Image
from config import settings


KLING_API_BASE = settings.kling_api_base


def _build_token() -> str:
    """生成 Kling JWT Bearer Token，有效期 30 分钟"""
    now = int(time.time())
    payload = {
        "iss": settings.kling_access_key,
        "exp": now + 1800,
        "nbf": now - 5,
    }
    return jwt.encode(payload, settings.kling_secret_key, algorithm="HS256")


def _auth_headers() -> dict:
    return {
        "Authorization": f"Bearer {_build_token()}",
        "Content-Type": "application/json",
    }


async def generate_image_from_text(prompt: str, output_path: Path) -> str:
    """调用 Kling 文生图接口，返回保存路径"""
    async with httpx.AsyncClient(timeout=300) as client:
        payload = {
            "model_name": "kling-v1",
            "prompt": prompt,
            "n": 1,
            "aspect_ratio": "16:9",
        }
        img_gen_url = f"{KLING_API_BASE}/v1/images/generations"
        logging.warning(f"[AI-CALL][kling:text2image:submit] POST {img_gen_url}")
        resp = await client.post(
            img_gen_url,
            headers=_auth_headers(),
            json=payload,
        )
        resp.raise_for_status()
        data = resp.json()

        task_id = data["data"]["task_id"]
        img_url = await _poll_image_task(client, task_id)

        logging.warning(f"[AI-CALL][kling:text2image:download] GET {img_url}")
        img_resp = await client.get(img_url)
        img_resp.raise_for_status()
        output_path.write_bytes(img_resp.content)
        return str(output_path)


async def _poll_image_task(client: httpx.AsyncClient, task_id: str, max_wait: int = 300) -> str:
    for _ in range(max_wait // 5):
        await asyncio.sleep(5)
        poll_url = f"{KLING_API_BASE}/v1/images/generations/{task_id}"
        logging.warning(f"[AI-CALL][kling:text2image:poll] GET {poll_url}")
        resp = await client.get(
            poll_url,
            headers=_auth_headers(),
        )
        resp.raise_for_status()
        data = resp.json()
        status = data["data"]["task_status"]
        if status == "succeed":
            return data["data"]["task_result"]["images"][0]["url"]
        if status == "failed":
            raise RuntimeError(f"Kling image task failed: {data}")
    raise TimeoutError("Kling image generation timed out")


async def generate_video_from_image(
    image_path: Path,
    prompt: str,
    output_path: Path,
    duration: int = 5,
    tail_image: Path = None,
) -> str:
    """图生视频，返回保存路径"""
    async with httpx.AsyncClient(timeout=300) as client:
        # 确保图片为真实 JPEG 且小于 2MB
        img = Image.open(image_path).convert("RGB")
        quality = 85
        while True:
            buf = io.BytesIO()
            img.save(buf, format="JPEG", quality=quality)
            if buf.tell() <= 2 * 1024 * 1024 or quality <= 40:
                break
            quality -= 10
        img_b64 = base64.b64encode(buf.getvalue()).decode()

        payload = {
            "model_name": "kling-v1",
            "image": img_b64,
            "prompt": prompt,
            "duration": "10" if duration > 7 else "5",
            "mode": "std",
            "aspect_ratio": "16:9",
        }

        # 尾帧图片（如果提供且 API 支持）
        if tail_image and tail_image.exists():
            tail_img = Image.open(tail_image).convert("RGB")
            tail_quality = 85
            while True:
                tail_buf = io.BytesIO()
                tail_img.save(tail_buf, format="JPEG", quality=tail_quality)
                if tail_buf.tell() <= 2 * 1024 * 1024 or tail_quality <= 40:
                    break
                tail_quality -= 10
            payload["image_tail"] = base64.b64encode(tail_buf.getvalue()).decode()
        vid_submit_url = f"{KLING_API_BASE}/v1/videos/image2video"
        logging.warning(f"[AI-CALL][kling:image2video:submit] POST {vid_submit_url}")
        resp = await client.post(
            vid_submit_url,
            headers=_auth_headers(),
            json=payload,
        )
        if not resp.is_success:
            logging.error(f"[kling] submit HTTP {resp.status_code}: {resp.text[:500]}")
            resp.raise_for_status()
        data = resp.json()
        logging.warning(f"[kling] submit ok: code={data.get('code')} msg={data.get('message')} task_id={data.get('data', {}).get('task_id')}")
        task_id = data["data"]["task_id"]
        video_url = await _poll_video_task(client, task_id)

        logging.warning(f"[AI-CALL][kling:image2video:download] GET {video_url}")
        video_resp = await client.get(video_url)
        video_resp.raise_for_status()
        output_path.write_bytes(video_resp.content)
        return str(output_path)


async def _poll_video_task(client: httpx.AsyncClient, task_id: str, max_wait: int = 600) -> str:
    for i in range(max_wait // 5):
        await asyncio.sleep(5)
        async with httpx.AsyncClient(timeout=30) as c:
            poll_url = f"{KLING_API_BASE}/v1/videos/image2video/{task_id}"
            logging.warning(f"[AI-CALL][kling:image2video:poll] GET {poll_url}")
            resp = await c.get(
                poll_url,
                headers=_auth_headers(),
            )
        if not resp.is_success:
            logging.error(f"[kling] poll HTTP {resp.status_code}: {resp.text[:500]}")
            resp.raise_for_status()
        data = resp.json()
        task_data = data.get("data", {})
        status = task_data.get("task_status", "unknown")
        logging.warning(f"[kling] poll #{i+1} task={task_id} status={status}")
        if status == "succeed":
            return task_data["task_result"]["videos"][0]["url"]
        if status == "failed":
            err_msg = task_data.get("task_status_msg", "") or task_data.get("message", "")
            raise RuntimeError(f"Kling video task failed: status_msg={err_msg!r} full={data}")
    raise TimeoutError("Kling video generation timed out")
