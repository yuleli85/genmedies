"""
真人剧集 LLM 服务
  - generate_script   : 根据梗概生成剧本（scenes + dialogues）
  - split_shots       : 将单集剧本拆解为分镜列表
"""
import json
import hashlib
import logging
from openai import AsyncOpenAI
from config import settings

_client = AsyncOpenAI(
    api_key=settings.openai_api_key,
    base_url=settings.openai_base_url,
    timeout=300.0,
)

_CHAT_URL = f"{settings.openai_base_url.rstrip('/')}/chat/completions"


def _log_call(tag: str, model: str):
    logging.warning(f"[AI-CALL][drama_llm:{tag}] POST {_CHAT_URL} model={model}")

# ── 剧本生成 ──────────────────────────────────────────────

SCRIPT_SYSTEM = """你是一位专业的影视编剧。根据用户提供的题材、梗概和角色设定，生成一集完整的剧本。

【输出格式要求】
返回严格 JSON，结构如下：
{
  "title": "剧集标题",
  "episode": 集数（整数）,
  "scenes": [
    {
      "scene_id": 1,
      "location": "场景地点",
      "time_of_day": "日/夜/黄昏",
      "description": "场景环境描述，20字以内",
      "dialogues": [
        {"character": "角色名", "line": "台词内容", "emotion": "情绪标签（平静/激动/悲伤/愤怒/喜悦）"}
      ]
    }
  ]
}

【创作要求】
- 场景数量：6~10个
- 每个场景台词：2~6句
- 台词口语化、自然，符合角色性格
- 情节有起承转合，结尾留有悬念或情感落点
- 禁止出现暴力、色情内容
"""


async def generate_script(
    genre: str,
    plot_summary: str,
    episode: int,
    characters: list[dict],
    style: str,
) -> dict:
    """生成单集剧本"""
    char_desc = "\n".join(
        f"- {c['name']}（{c.get('gender','')}{c.get('age','')}岁）：{c.get('appearance','')}，{c.get('personality','')}"
        for c in characters
    )
    user_msg = (
        f"题材：{genre}\n"
        f"风格：{style}\n"
        f"第{episode}集梗概：{plot_summary}\n"
        f"角色设定：\n{char_desc}\n\n"
        "请生成本集完整剧本。"
    )
    _log_call("generate_script", settings.llm_model)
    resp = await _client.chat.completions.create(
        model=settings.llm_model,
        messages=[
            {"role": "system", "content": SCRIPT_SYSTEM},
            {"role": "user",   "content": user_msg},
        ],
        temperature=0.8,
        response_format={"type": "json_object"},
    )
    return json.loads(resp.choices[0].message.content)


# ── 分镜拆解 ──────────────────────────────────────────────

SHOT_SYSTEM = """你是一位专业的影视分镜师。将剧本场景拆解为具体的拍摄镜头列表。

【最重要原则 - 画面必须匹配台词】
image_prompt 必须精确描绘 dialogue 发生时的画面。观众看到画面时，应该能直接理解这句台词是在什么情境下说的。

错误示例：
- dialogue: "我不会放弃的！" → image_prompt: "A beautiful sunset over the city" ❌ (画面与台词无关)
- dialogue: "你怎么来了？" → image_prompt: "A man walking on the street" ❌ (没有展示说话者和听话者的互动)

正确示例：
- dialogue: "我不会放弃的！" → image_prompt: "Close-up of Lin Chen (young man, determined expression, clenched fists), tears in eyes, facing camera, dramatic lighting, cinematic, realistic, 16:9" ✓
- dialogue: "你怎么来了？" → image_prompt: "Medium shot of Xiao Mei (young woman, surprised expression) standing at doorway, looking at a man entering, warm indoor lighting, cinematic, realistic, 16:9" ✓

【image_prompt 必须包含】
1. 说话者的名字和外貌特征（从角色设定中获取）
2. 说话者此刻的表情（根据台词情绪推断）
3. 说话者的动作或姿态
4. 场景环境和光线
5. 如果台词涉及对话对象，必须包含对方

【约束】
- 单镜头时长 4~8 秒
- 同一场景连续动作拆分为多个镜头
- 景别：特写/近景/中景/全景/远景
- 运镜：固定/推/拉/摇/跟/升/降

【输出格式】
返回严格 JSON：
{
  "shots": [
    {
      "shot_id": 1,
      "scene_id": 对应场景ID,
      "shot_type": "景别",
      "camera_move": "运镜方式",
      "characters": ["出场角色名列表"],
      "character": "说台词的角色名（用于配音匹配），无台词则为空字符串",
      "action": "人物动作描述，英文，用于图生视频提示词",
      "dialogue": "本镜头对应台词（中文），无则为空字符串",
      "duration": 时长秒数,
      "mood": "氛围关键词",
      "image_prompt": "英文图片生成提示词，必须描绘说台词那一刻的画面，格式：[景别] of [角色名] ([外貌], [表情], [动作]), [场景环境], [光线], cinematic, realistic, 16:9"
    }
  ]
}
"""


async def split_shots(scenes: list[dict], characters: list[dict], style: str) -> list[dict]:
    """将场景列表拆解为分镜"""
    char_desc = ", ".join(
        f"{c['name']}({c.get('appearance','')})" for c in characters
    )
    scenes_text = json.dumps(scenes, ensure_ascii=False)
    user_msg = (
        f"风格：{style}\n"
        f"角色外貌：{char_desc}\n\n"
        f"场景列表：\n{scenes_text}\n\n"
        "请拆解为分镜列表。"
    )
    _log_call("split_shots", settings.llm_model)
    resp = await _client.chat.completions.create(
        model=settings.llm_model,
        messages=[
            {"role": "system", "content": SHOT_SYSTEM},
            {"role": "user",   "content": user_msg},
        ],
        temperature=0.7,
        response_format={"type": "json_object"},
    )
    data = json.loads(resp.choices[0].message.content)
    return data.get("shots", [])


# ── 缓存 key 工具 ─────────────────────────────────────────

def script_cache_key(genre: str, plot_summary: str, style: str, episode: int) -> str:
    raw = f"{genre}|{plot_summary}|{style}|{episode}"
    return hashlib.md5(raw.encode()).hexdigest()


def shots_cache_key(scenes_json: str, style: str) -> str:
    raw = f"{scenes_json}|{style}"
    return hashlib.md5(raw.encode()).hexdigest()
