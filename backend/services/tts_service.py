"""
TTS 服务 — 调用 SiliconFlow CosyVoice2 将旁白文字转为 MP3
"""
import httpx
import logging
from pathlib import Path
from config import settings

TTS_API = "https://api.siliconflow.cn/v1/audio/speech"
TTS_MODEL = "FunAudioLLM/CosyVoice2-0.5B"
TTS_VOICE = "FunAudioLLM/CosyVoice2-0.5B:alex"


async def text_to_speech(text: str, output_path: Path) -> Path:
    """将文字转为 MP3，保存到 output_path"""
    logging.warning(f"[AI-CALL][tts:text_to_speech] POST {TTS_API} model={TTS_MODEL}")
    async with httpx.AsyncClient(timeout=300) as client:
        resp = await client.post(
            TTS_API,
            headers={
                "Authorization": f"Bearer {settings.siliconflow_api_key}",
                "Content-Type": "application/json",
            },
            json={
                "model": TTS_MODEL,
                "input": text,
                "voice": TTS_VOICE,
                "response_format": "mp3",
            },
        )
        resp.raise_for_status()
        output_path.write_bytes(resp.content)
    return output_path
