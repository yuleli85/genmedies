"""
Stability AI 图片生成服务 — 使用 Stable Image Core (SDXL)
API 文档: https://platform.stability.ai/docs/api-reference#tag/Generate/paths/~1v2beta~1stable-image~1generate~1core/post
"""
import httpx
import logging
from pathlib import Path
from config import settings


STABILITY_API_BASE = "https://api.stability.ai"


async def generate_image_from_text(prompt: str, output_path: Path) -> str:
    """调用 Stability AI 生成图片，保存为 JPEG，返回路径"""
    url = f"{STABILITY_API_BASE}/v2beta/stable-image/generate/core"
    logging.warning(f"[AI-CALL][stability:generate_image] POST {url}")
    async with httpx.AsyncClient(timeout=60) as client:
        resp = await client.post(
            url,
            headers={
                "Authorization": f"Bearer {settings.stability_api_key}",
                "Accept": "image/*",
            },
            data={
                "prompt": prompt,
                "aspect_ratio": "16:9",
                "output_format": "jpeg",
            },
        )
        resp.raise_for_status()
        output_path.write_bytes(resp.content)
        return str(output_path)
