"""
腾讯混元图像 3.0 服务 — 通过 Token Hub HTTP API 调用
submit: POST https://tokenhub.tencentmaas.com/v1/api/image/submit
query:  POST https://tokenhub.tencentmaas.com/v1/api/image/query  (body: {"id": "..."})
Auth:   Bearer {TENCENT_SECRET_KEY}
"""
import asyncio
import io
import re
import logging
import httpx
from pathlib import Path
from PIL import Image
from config import settings

_BASE = "https://tokenhub.tencentmaas.com/v1/api/image"

# 混元中文内容审核常见触发词 → 替换为中性词
_SENSITIVE = [
    (r'战争|军事|武器|爆炸|炸弹|枪支|导弹|士兵|军队|暴力|血腥|尸体|杀戮', '紧张场面'),
    (r'赌博|博彩|彩票|下注', '活动'),
    (r'股票涨停|跌停|炒股|割韭菜|庄家|内幕', '股价波动'),
    (r'裸|色情|性感|情色', '艺术'),
    (r'抗议|示威|革命|暴动|政治', '人群'),
]


def _sanitize(prompt: str) -> str:
    result = prompt
    for pattern, replacement in _SENSITIVE:
        result = re.sub(pattern, replacement, result)
    return result


def _headers() -> dict:
    return {
        "Authorization": f"Bearer {settings.tencent_secret_key}",
        "Content-Type": "application/json",
    }


async def _submit(prompt: str, seed: int = None) -> str:
    """提交生成任务，返回 job_id。内容审核/限流时自动重试。"""
    max_retries = 6
    for attempt in range(max_retries):
        async with httpx.AsyncClient(timeout=60) as client:
            submit_url = f"{_BASE}/submit"
            logging.warning(f"[AI-CALL][hunyuan:submit] POST {submit_url} (attempt {attempt+1})")
            body = {"model": "hy-image-v3.0", "prompt": prompt}
            if seed is not None:
                body["seed"] = seed
            resp = await client.post(
                submit_url,
                headers=_headers(),
                json=body,
            )
            resp.raise_for_status()
            data = resp.json()

        if data.get("status") == "failed":
            err = data.get("error", {})
            code = err.get("code", "")
            msg = err.get("message", "")
            is_rate_limit = "LimitExceed" in code or "JobNumExceed" in code or "稍后重试" in msg
            is_sensitive = "TextIllegalDetected" in code or "敏感" in msg
            if is_rate_limit and attempt < max_retries - 1:
                wait = 10 * (attempt + 1)
                logging.warning(f"[hunyuan] 限流，等待 {wait}s 后重试...")
                await asyncio.sleep(wait)
                continue
            exc = RuntimeError(f"混元图像提交失败: {msg} (code={code})")
            exc.is_sensitive = is_sensitive
            raise exc

        job_id = data.get("id") or data.get("request_id")
        if not job_id:
            raise RuntimeError(f"混元图像提交未返回 id: {data}")
        return job_id
    raise RuntimeError("混元图像提交失败: 重试次数耗尽")


async def generate_image_from_text(prompt: str, output_path: Path, seed: int = None) -> str:
    """调用混元图像 3.0 生成图片，保存为 JPEG，返回路径"""
    prompts = [prompt, _sanitize(prompt), "高质量电影感图像，专业讲师在演播室讲解，16:9"]

    job_id = None
    for attempt, p in enumerate(prompts):
        try:
            job_id = await _submit(p, seed=seed)
            logging.warning(f"[hunyuan] submitted job_id={job_id} (attempt {attempt+1})")
            break
        except RuntimeError as e:
            if getattr(e, "is_sensitive", False):
                logging.warning(f"[hunyuan] 内容审核拦截，简化 prompt 重试 (attempt {attempt+1}): {p[:60]}")
                continue
            raise

    if not job_id:
        raise RuntimeError("混元图像：prompt 多次被内容审核拦截，请修改分镜提示词")

    img_url = await _poll_job(job_id)

    async with httpx.AsyncClient(timeout=120) as client:
        for attempt in range(3):
            try:
                logging.warning(f"[AI-CALL][hunyuan:download] GET {img_url} (attempt {attempt+1})")
                img_resp = await client.get(img_url)
                img_resp.raise_for_status()
                break
            except Exception as e:
                if attempt == 2:
                    raise
                logging.warning(f"[hunyuan] download retry {attempt+1}: {e}")
                await asyncio.sleep(2)

    img = Image.open(io.BytesIO(img_resp.content)).convert("RGB")
    quality = 85
    while True:
        buf = io.BytesIO()
        img.save(buf, format="JPEG", quality=quality)
        if buf.tell() <= 2 * 1024 * 1024 or quality <= 40:
            break
        quality -= 10
    output_path.write_bytes(buf.getvalue())
    logging.warning(f"[hunyuan] saved {output_path} ({buf.tell()//1024}KB)")
    return str(output_path)


async def _poll_job(job_id: str, max_wait: int = 300) -> str:
    async with httpx.AsyncClient(timeout=30) as client:
        for i in range(max_wait // 5):
            await asyncio.sleep(5)
            query_url = f"{_BASE}/query"
            logging.warning(f"[AI-CALL][hunyuan:poll] POST {query_url} id={job_id}")
            resp = await client.post(
                query_url,
                headers=_headers(),
                json={"model": "hy-image-v3.0", "id": job_id},
            )
            if not resp.is_success:
                logging.warning(f"[hunyuan] poll HTTP {resp.status_code}: {resp.text[:200]}")
                continue
            data = resp.json()
            status = data.get("status", "unknown")
            logging.warning(f"[hunyuan] poll #{i+1} job={job_id} status={status}")

            if status in ("succeeded", "completed"):
                images = data.get("data") or data.get("images") or data.get("result")
                if isinstance(images, list) and images:
                    item = images[0]
                    return item.get("url") if isinstance(item, dict) else item
                url = data.get("url") or data.get("image_url")
                if url:
                    return url
                raise RuntimeError(f"混元图像完成但无图片URL: {data}")

            if status == "failed":
                err = data.get("error", {})
                raise RuntimeError(f"混元图像任务失败: {err.get('message')} (code={err.get('code')})")

    raise TimeoutError("混元图像生成超时")
