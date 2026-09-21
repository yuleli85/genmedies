"""
火山引擎 即梦 (Jimeng) 服务
  - generate_image_from_text : 文生图 (Seedream)，保存到本地，返回本地路径
  - generate_video_from_image: 图生视频 (Seedance)，上传关键帧到 TOS，返回本地路径
"""
import asyncio
import logging
from pathlib import Path

import httpx
import tos

from config import settings

ARK_BASE   = settings.jimeng_api_base
IMG_MODEL  = settings.jimeng_image_model
VID_MODEL  = settings.jimeng_video_model
API_KEY    = settings.jimeng_api_key
VID_API_KEY = settings.jimeng_video_api_key or API_KEY

TOS_AK       = settings.tos_access_key
TOS_SK       = settings.tos_secret_key
TOS_BUCKET   = settings.tos_bucket
TOS_REGION   = settings.tos_region
TOS_ENDPOINT = settings.tos_endpoint


def _headers() -> dict:
    return {
        "Authorization": f"Bearer {API_KEY}",
        "Content-Type":  "application/json",
    }


# ── TOS 上传 ──────────────────────────────────────────────

async def _upload_to_tos(image_path: Path) -> str:
    """上传图片到 TOS，返回公网 URL"""
    key = f"drama_keyframes/{image_path.name}"

    def _do_upload():
        client = tos.TosClientV2(
            ak=TOS_AK,
            sk=TOS_SK,
            endpoint=TOS_ENDPOINT,
            region=TOS_REGION,
        )
        with open(image_path, "rb") as f:
            client.put_object(bucket=TOS_BUCKET, key=key, content=f)

    loop = asyncio.get_event_loop()
    await loop.run_in_executor(None, _do_upload)

    return f"https://{TOS_BUCKET}.{TOS_ENDPOINT.replace('https://', '')}/{key}"


# ── 文生图 ────────────────────────────────────────────────

async def generate_image_from_text(prompt: str, output_path: Path, ref_image_path: Path = None) -> Path:
    """调用 Seedream 文生图，支持角色参考图，下载图片保存到 output_path，返回路径"""
    output_path = Path(output_path)
    output_path.parent.mkdir(parents=True, exist_ok=True)

    async with httpx.AsyncClient(timeout=120) as client:
        img_gen_url = f"{ARK_BASE}/images/generations"

        payload = {
            "model":     IMG_MODEL,
            "prompt":    prompt,
            "size":      "2k",
            "n":         1,
            "watermark": False,
        }

        # 如果有参考图，上传到 TOS 并添加到请求
        if ref_image_path and Path(ref_image_path).exists():
            ref_url = await _upload_to_tos(Path(ref_image_path))
            payload["image_url"] = ref_url
            logging.info(f"[jimeng/img] using reference image: {ref_url}")

        logging.warning(f"[AI-CALL][jimeng:text2image] POST {img_gen_url} model={IMG_MODEL}")
        resp = await client.post(
            img_gen_url,
            headers=_headers(),
            json=payload,
        )
        if not resp.is_success:
            logging.error(f"[jimeng/img] error: {resp.text[:500]}")
        resp.raise_for_status()
        data = resp.json()

        img_url = data["data"][0]["url"]
        logging.warning(f"[AI-CALL][jimeng:text2image:download] GET {img_url}")
        img_resp = await client.get(img_url, timeout=60)
        img_resp.raise_for_status()
        output_path.write_bytes(img_resp.content)

    return output_path


# ── 图生视频 ──────────────────────────────────────────────

async def generate_video_from_image(
    image_path: Path,
    prompt: str,
    output_path: Path,
    duration: int = 5,
) -> Path:
    """上传关键帧到 TOS，调用 Seedance 图生视频，下载视频保存到 output_path"""
    image_path  = Path(image_path)
    output_path = Path(output_path)
    output_path.parent.mkdir(parents=True, exist_ok=True)

    try:
        public_url = await _upload_to_tos(image_path)
        logging.warning(f"[jimeng/vid] uploaded to TOS: {public_url}")
    except Exception as e:
        logging.error(f"[jimeng/vid] TOS upload failed: {type(e).__name__}: {e}")
        raise

    try:
        async with httpx.AsyncClient(timeout=60) as client:
            vid_submit_url = f"{ARK_BASE}/contents/generations/tasks"
            logging.warning(f"[AI-CALL][jimeng:image2video:submit] POST {vid_submit_url} model={VID_MODEL}")
            resp = await client.post(
                vid_submit_url,
                headers={
                    "Authorization": f"Bearer {VID_API_KEY}",
                    "Content-Type": "application/json",
                },
                json={
                    "model": VID_MODEL,
                    "content": [
                        {"type": "image_url", "image_url": {"url": public_url}},
                        {"type": "text",      "text": prompt or "cinematic motion"},
                    ],
                },
            )
            if not resp.is_success:
                logging.error(f"[jimeng/vid] submit error: {resp.text[:1000]}")
            resp.raise_for_status()
            task_id = resp.json()["id"]
    except Exception as e:
        logging.error(f"[jimeng/vid] submit failed: {type(e).__name__}: {e}")
        raise

    video_url = await _poll_video(task_id)

    async with httpx.AsyncClient(timeout=120) as client:
        logging.warning(f"[AI-CALL][jimeng:image2video:download] GET {video_url}")
        vid_resp = await client.get(video_url)
        vid_resp.raise_for_status()
        output_path.write_bytes(vid_resp.content)

    return output_path


async def _poll_video(task_id: str, max_wait: int = 600) -> str:
    for _ in range(max_wait // 5):
        await asyncio.sleep(5)
        async with httpx.AsyncClient(timeout=30) as client:
            poll_url = f"{ARK_BASE}/contents/generations/tasks/{task_id}"
            logging.warning(f"[AI-CALL][jimeng:image2video:poll] GET {poll_url}")
            resp = await client.get(
                poll_url,
                headers={
                    "Authorization": f"Bearer {VID_API_KEY}",
                    "Content-Type": "application/json",
                },
            )
            resp.raise_for_status()
            data = resp.json()

        status = data.get("status")
        if status == "succeeded":
            for item in data.get("content", []):
                if item.get("type") == "video_url":
                    return item["video_url"]["url"]
            raise RuntimeError(f"Seedance task succeeded but no video_url: {data}")
        if status == "failed":
            raise RuntimeError(f"Seedance task failed: {data}")

        logging.info(f"[jimeng/vid] task {task_id} status={status}")

    raise TimeoutError(f"Seedance task {task_id} timed out after {max_wait}s")
