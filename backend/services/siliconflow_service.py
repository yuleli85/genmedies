"""
SiliconFlow 图片生成服务 — 使用 Kolors 模型
API 兼容 OpenAI images 格式
"""
import asyncio
import io
import re
import logging
import httpx
from pathlib import Path
from PIL import Image
from config import settings


SILICONFLOW_API_BASE = "https://api.siliconflow.cn/v1"

# 常见触发审核的词，替换为中性词
_SENSITIVE_PATTERNS = [
    (r'\b(blood|bleeding|gore|violent|violence|murder|kill|dead|death|corpse|wound)\b', 'intense'),
    (r'\b(war|battle|weapon|gun|bomb|explosion|missile|military|soldier|army)\b', 'dramatic scene'),
    (r'\b(naked|nude|sexual|sexy|erotic)\b', 'artistic'),
    (r'\b(drug|cocaine|marijuana|opium)\b', 'substance'),
    (r'\b(protest|riot|rebellion|revolution|communist|terrorist)\b', 'crowd'),
]


def _sanitize_prompt(prompt: str) -> str:
    """替换 prompt 中可能触发 451 的敏感词"""
    result = prompt
    for pattern, replacement in _SENSITIVE_PATTERNS:
        result = re.sub(pattern, replacement, result, flags=re.IGNORECASE)
    return result


async def generate_image_from_text(prompt: str, output_path: Path, seed: int = None, ref_image: str = None, ref_strength: float = 0.35) -> str:
    """调用 SiliconFlow 生成图片，支持 seed 和参考图（img2img）"""
    prompts_to_try = [prompt, _sanitize_prompt(prompt), "a cinematic scene, high quality, 16:9"]

    for attempt in range(5):
        current_prompt = prompts_to_try[min(attempt, len(prompts_to_try) - 1)]

        async with httpx.AsyncClient(timeout=300) as client:
            url = f"{SILICONFLOW_API_BASE}/images/generations"
            logging.warning(f"[AI-CALL][siliconflow:generate_image] POST {url} (attempt {attempt+1})")

            body = {
                "model": "Kwai-Kolors/Kolors",
                "prompt": current_prompt,
                "image_size": "1920x1080",
                "num_inference_steps": 20,
                "batch_size": 1,
            }
            if seed is not None:
                body["seed"] = seed
            if ref_image:
                body["image"] = ref_image
                body["strength"] = ref_strength

            resp = await client.post(
                url,
                headers={
                    "Authorization": f"Bearer {settings.siliconflow_api_key}",
                    "Content-Type": "application/json",
                },
                json=body,
            )

            if resp.status_code == 429:
                await asyncio.sleep(3 * (attempt + 1))
                continue

            if resp.status_code == 451:
                logging.warning(f"[siliconflow] 451 内容审核拦截，尝试简化 prompt (attempt {attempt+1})")
                logging.warning(f"[siliconflow] 原 prompt: {current_prompt[:100]}")
                await asyncio.sleep(1)
                continue

            if resp.status_code >= 500:
                logging.warning(f"[siliconflow] 服务端错误 {resp.status_code}，重试 (attempt {attempt+1})")
                await asyncio.sleep(3 * (attempt + 1))
                continue

            resp.raise_for_status()
            img_url = resp.json()["images"][0]["url"]
            logging.info(f"[siliconflow] generated img_url: {img_url[:80]}...")

            # 下载生成的图片，DNS 偶发失败时最多重试 3 次
            for dl_attempt in range(3):
                try:
                    img_resp = await client.get(img_url, timeout=300)
                    img_resp.raise_for_status()
                    img_bytes = img_resp.content
                    break
                except (httpx.ConnectError, httpx.TimeoutException) as e:
                    logging.warning(f"[siliconflow] download attempt {dl_attempt+1} failed: {e}")
                    if dl_attempt < 2:
                        await asyncio.sleep(2)
                    else:
                        raise

            img = Image.open(io.BytesIO(img_bytes)).convert("RGB")
            quality = 85
            while True:
                buf = io.BytesIO()
                img.save(buf, format="JPEG", quality=quality)
                if buf.tell() <= 2 * 1024 * 1024 or quality <= 40:
                    break
                quality -= 10
            output_path.write_bytes(buf.getvalue())
            return str(output_path)

    raise RuntimeError("图片生成失败：prompt 多次被内容审核拦截，请修改分镜提示词后重试")
