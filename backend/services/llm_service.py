"""
LLM 服务 — 将文章拆分为分镜列表
每个分镜包含: 序号、时长、画面描述(中文)、Kling图片提示词(英文)
"""
import asyncio
import base64
import json
import logging
import mimetypes
import re
import shutil
import subprocess
from pathlib import Path
from openai import AsyncOpenAI
from config import settings

_client = AsyncOpenAI(
    api_key=settings.openai_api_key,
    base_url=settings.openai_base_url,
    timeout=300.0,
)

_CHAT_URL = f"{settings.openai_base_url.rstrip('/')}/chat/completions"


def _log_call(tag: str, model: str, url: str = _CHAT_URL):
    logging.warning(f"[AI-CALL][llm:{tag}] POST {url} model={model}")

SPLIT_SYSTEM = """你是一位专业的短视频讲师脚本创作者。
用户给你一篇文章，你要把它改写成适合真人讲解的视频分镜脚本。

【分镜结构要求】
- 每个大章（如"一、树立正确理念"）出 1 个引言镜头，说明这章要讲什么
- 同一大章下的小节，每 2-3 个相近的点合并成 1 个镜头，不要每个点单独一个镜头
- 最后出 1 个总结镜头，完整收尾整篇文章
- 禁止跳过任何大章

【narration 是最重要的部分，必须语义完整】
每条 narration 必须是一段完整的表达，有头有尾：
- 开头：引出这段要讲的内容（"这章我们讲…"、"接下来说…"）
- 中间：把核心要点讲清楚，口语化，自然流畅
- 结尾：有明确的收束感，不能话说一半就停（禁止以"、"","这类标点结尾，禁止以列举方式结尾）
- 字数：80-150 字，一段完整的话
- 衔接：切换大章时加过渡句，例如"第一章到这里讲完了，接下来我们进入第二章"

【反例（禁止出现）】
❌ "短线交易有四大原则：敬畏市场、聚焦核心、纪律至上、积小胜为大胜。"  ← 列举没收尾
❌ "止损方法有三种，分别是固定点位、关键价位、信号止损，"  ← 逗号结尾
✅ "短线交易的核心是四大原则：敬畏市场、聚焦核心、纪律至上、积小胜为大胜。做到这四点，才能在市场中长期存活。"  ← 完整收尾

每个分镜包含：
- scene_id: 序号，从1开始
- duration: 时长（秒，范围5-8）
- narration: 完整的讲师口述段落，语义完整，有收尾
- scene_desc: 中文画面描述
- image_prompt: 英文图片生成提示词

返回严格的JSON格式，不要有任何额外文字：
{
  "title": "视频标题",
  "total_duration": 总时长秒数,
  "scenes": [
    {
      "scene_id": 1,
      "duration": 6,
      "narration": "旁白文字",
      "scene_desc": "中文画面描述",
      "image_prompt": "English image generation prompt"
    }
  ]
}

image_prompt 生成规则：
1. 直接描述 narration 内容对应的具体视觉场景
2. 具象可视化，画面里能实际看到的东西，避免抽象描述
3. 结尾加风格词：cinematic, professional, 16:9, high quality
4. 禁止使用敏感词：war/violence/blood/weapon/military/protest/nude
"""


async def generate_ppt_scripts(slides: list[dict]) -> list[dict]:
    """根据 PPT 每页内容生成口播稿，返回 [{page, script}]"""
    slides_text = "\n\n".join(
        f"第{s['index']}页\n标题：{s.get('title','')}\n内容：{s.get('text','')}"
        for s in slides
    )
    _log_call("generate_ppt_scripts", settings.llm_model)
    resp = await _client.chat.completions.create(
        model=settings.llm_model,
        messages=[
            {
                "role": "system",
                "content": (
                    "你是一位专业的 PPT 演讲稿撰写人。"
                    "用户给你 PPT 每页的标题和内容，你为每页生成一段自然流畅的口播稿。\n"
                    "要求：\n"
                    "- 口语化，适合真人朗读，不要照抄原文\n"
                    "- 每页 60-120 字，语义完整，有开头有收尾\n"
                    "- 禁止以顿号、逗号、列举方式结尾\n"
                    "- 返回严格 JSON，格式：{\"scripts\": [{\"page\": 1, \"script\": \"...\"}, ...]}"
                ),
            },
            {"role": "user", "content": slides_text},
        ],
        temperature=0.7,
        response_format={"type": "json_object"},
    )
    data = json.loads(resp.choices[0].message.content)
    return data["scripts"]


async def generate_ppt_script_page(slide: dict) -> str:
    """为单页 PPT 重新生成口播稿"""
    content = f"标题：{slide.get('title','')}\n内容：{slide.get('text','')}"
    _log_call("generate_ppt_script_page", settings.llm_model)
    resp = await _client.chat.completions.create(
        model=settings.llm_model,
        messages=[
            {
                "role": "system",
                "content": (
                    "你是一位专业的 PPT 演讲稿撰写人。"
                    "为给定的 PPT 页面生成一段自然流畅的口播稿。"
                    "口语化，60-120 字，语义完整，有开头有收尾，禁止以标点或列举结尾。"
                    "只返回口播稿文本，不要任何解释。"
                ),
            },
            {"role": "user", "content": content},
        ],
        temperature=0.7,
    )
    return resp.choices[0].message.content.strip()


async def split_article_to_scenes(article_text: str, portrait_hint: str = "") -> dict:
    """将文章拆分为分镜JSON"""
    user_msg = f"请将以下文章改写成视频讲师脚本，拆分为分镜：\n\n{article_text}"
    if portrait_hint:
        user_msg += f"\n\n注意：主角形象提示 — {portrait_hint}"
    user_msg += "\n\n最重要：每条 narration 必须语义完整，有开头、内容、收尾，不能话说一半就截断。禁止以顿号、逗号、列举结尾。每段 50-80 字，读起来像一段完整的话。"

    _log_call("split_article_to_scenes", settings.llm_model)
    resp = await _client.chat.completions.create(
        model=settings.llm_model,
        messages=[
            {"role": "system", "content": SPLIT_SYSTEM},
            {"role": "user", "content": user_msg},
        ],
        temperature=0.7,
        response_format={"type": "json_object"},
    )

    raw = resp.choices[0].message.content
    return json.loads(raw)


async def translate_to_chinese(text: str) -> str:
    """将英文图片提示词翻译为中文（混元模型对中文 prompt 效果更好）"""
    _log_call("translate_to_chinese", settings.llm_model_mini)
    resp = await _client.chat.completions.create(
        model=settings.llm_model_mini,
        messages=[
            {
                "role": "system",
                "content": "将以下英文图片生成提示词翻译为中文，保留所有描述细节，只返回翻译结果，不要解释。",
            },
            {"role": "user", "content": text},
        ],
        temperature=0.1,
    )
    return resp.choices[0].message.content.strip()


async def translate_to_english(text: str) -> str:
    """将中文人物描述翻译为英文，用于图片生成 prompt"""
    _log_call("translate_to_english", settings.llm_model_mini)
    resp = await _client.chat.completions.create(
        model=settings.llm_model_mini,
        messages=[
            {
                "role": "system",
                "content": "Translate the following Chinese person appearance description into English for use in an image generation prompt. Return only the translated text, no explanation.",
            },
            {"role": "user", "content": text},
        ],
        temperature=0.3,
    )
    return resp.choices[0].message.content.strip()


async def enhance_prompt_with_portrait(base_prompt: str, portrait_description: str) -> str:
    """将人物形象信息融入图片提示词"""
    _log_call("enhance_prompt_with_portrait", settings.llm_model_mini)
    resp = await _client.chat.completions.create(
        model=settings.llm_model_mini,
        messages=[
            {
                "role": "system",
                "content": "You are a prompt engineer. Enhance the given image generation prompt by naturally incorporating the character description. Return only the enhanced prompt, no explanation.",
            },
            {
                "role": "user",
                "content": f"Base prompt: {base_prompt}\nCharacter description: {portrait_description}\nEnhanced prompt:",
            },
        ],
        temperature=0.5,
    )
    return resp.choices[0].message.content.strip()


_vision_client = AsyncOpenAI(
    api_key=settings.vision_api_key,
    base_url=settings.vision_base_url,
    timeout=300.0,
)


async def repair_ocr_text(raw_text: str, image_path: str = "") -> str:
    """用视觉模型对照页面图片修复 OCR 文本，还原原始排版结构"""
    if not raw_text or len(raw_text.strip()) < 10:
        return raw_text

    messages = [
        {
            "role": "system",
            "content": (
                "你是一位 OCR 文本修复专家。用户给你一张文档页面的图片和 OCR 识别出的原始文本。\n"
                "请对照图片中的实际内容，修复和还原文本。\n\n"
                "【修复规则】\n"
                "- 对照图片修复 OCR 错别字和乱码\n"
                "- 删除无法理解的乱码片段和识别噪声\n"
                "- 不凭空增加图片中没有的内容\n\n"
                "【格式规则】\n"
                "- 严格按照图片中的原始排版结构输出\n"
                "- 标题单独一行，前后空一行\n"
                "- 目录/列表保留编号和层级缩进，用空格缩进表示层级\n"
                "- 表格用对齐的纯文本格式还原，列之间用制表符分隔\n"
                "- 段落之间用空行分隔\n"
                "- 不要添加 Markdown 标记（如 #、*、-）\n"
                "- 不要合并图片中明显分开的行\n\n"
                "只返回修复后的文本，不要任何解释或标注。"
            ),
        },
    ]

    user_content = []
    if image_path and Path(image_path).exists():
        img_data = base64.b64encode(Path(image_path).read_bytes()).decode()
        mime = mimetypes.guess_type(image_path)[0] or "image/png"
        user_content.append({
            "type": "image_url",
            "image_url": {"url": f"data:{mime};base64,{img_data}"},
        })

    user_content.append({
        "type": "text",
        "text": f"以下是 OCR 识别的原始文本，请对照图片修复：\n\n{raw_text}",
    })
    messages.append({"role": "user", "content": user_content})

    _log_call("repair_ocr_text", settings.vision_model)
    resp = await _vision_client.chat.completions.create(
        model=settings.vision_model,
        messages=messages,
        temperature=0.2,
    )
    return resp.choices[0].message.content.strip()


async def extract_text_from_image(image_path: str) -> str:
    tesseract_path = shutil.which(settings.tesseract_cmd) or settings.tesseract_cmd
    if not shutil.which(settings.tesseract_cmd) and not Path(settings.tesseract_cmd).exists():
        raise RuntimeError(
            f"未找到 Tesseract 可执行文件: {settings.tesseract_cmd}，请先安装 tesseract-ocr 并确认命令可用"
        )

    def _run_ocr() -> str:
        proc = subprocess.run(
            [
                tesseract_path,
                image_path,
                "stdout",
                "-l",
                settings.tesseract_lang,
                "--psm",
                "6",
            ],
            capture_output=True,
            text=True,
            timeout=120,
        )
        if proc.returncode != 0:
            detail = (proc.stderr or proc.stdout or "").strip()
            raise RuntimeError(f"Tesseract OCR 失败: {detail or '未知错误'}")
        return proc.stdout.strip()

    return await asyncio.to_thread(_run_ocr)


# ── Markdown 转 PPT 拆分 ─────────────────────────────────

MD2PPT_SYSTEM = """你是一位专业的演示文稿设计师。
用户给你一篇 Markdown 文章，你要将它智能拆分为 PPT 幻灯片结构。

【拆分规则】
- 第一页为标题页：提取文章标题作为 title，摘要作为 subtitle（放在 bullets[0]）
- 每个一级标题(#)或二级标题(##)通常对应一张新幻灯片
- 同一标题下的内容拆分为要点(bullets)，每页不超过 5 个要点
- 如果某个章节内容过多，拆分为多张幻灯片
- 代码块单独成页，layout 标记为 "code"，代码内容放在 bullets[0]
- 最后一页为总结页

【layout 类型】
- title: 标题页（仅标题 + 副标题）
- content: 标准内容页（标题 + 要点列表）
- code: 代码展示页（标题 + 代码内容）
- section: 章节分隔页（大标题，用于章节过渡）
- summary: 总结页

返回严格 JSON：
{
  "slides": [
    {
      "slide_id": 1,
      "title": "幻灯片标题",
      "bullets": ["要点1", "要点2"],
      "notes": "演讲者备注（可选，空字符串表示无）",
      "layout": "content"
    }
  ]
}
"""


async def split_markdown_to_slides(markdown_text: str) -> dict:
    """将 Markdown 文本智能拆分为幻灯片结构"""
    _log_call("split_markdown_to_slides", settings.llm_model)
    client = AsyncOpenAI(
        api_key=settings.openai_api_key,
        base_url=settings.openai_base_url,
        timeout=600.0,
    )
    resp = await client.chat.completions.create(
        model=settings.llm_model,
        messages=[
            {"role": "system", "content": MD2PPT_SYSTEM},
            {"role": "user", "content": f"请将以下 Markdown 文章拆分为 PPT 幻灯片结构：\n\n{markdown_text}"},
        ],
        temperature=0.5,
        response_format={"type": "json_object"},
    )
    return json.loads(resp.choices[0].message.content)