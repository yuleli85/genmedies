import os
from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    kling_access_key: str = "AhkRGkdNELTGetEpmPF4bGrEDJdYhDkM"
    kling_secret_key: str = "8MRJHNyMTLErAFd4T4QRbaEp98JMtfpr"
    kling_api_base: str = "https://api.klingai.com"
    stability_api_key: str = ""
    siliconflow_api_key: str = ""
    openai_api_key: str = ""
    openai_base_url: str = "https://api.openai.com/v1"
    llm_model: str = "gpt-4o"
    llm_model_mini: str = "gpt-4o-mini"
    deepseek_ocr_api_key: str = ""
    deepseek_ocr_base_url: str = "https://api.deepseek.com/v1"
    deepseek_ocr_model: str = "deepseek-ocr"
    tesseract_cmd: str = "tesseract"
    tesseract_lang: str = "chi_sim+eng"
    vision_api_key: str = ""
    vision_base_url: str = "https://dashscope.aliyuncs.com/compatible-mode/v1"
    vision_model: str = "qwen-vl-max"
    upload_dir: str = "uploads"
    max_file_size_mb: int = 50
    tencent_secret_id: str = ""
    tencent_secret_key: str = ""
    jimeng_api_key: str = ""
    jimeng_video_api_key: str = ""
    jimeng_api_base: str = "https://ark.cn-beijing.volces.com/api/v3"
    jimeng_image_model: str = ""
    jimeng_video_model: str = ""
    tos_access_key: str = ""
    tos_secret_key: str = ""
    tos_bucket: str = ""
    tos_endpoint: str = "https://tos-cn-beijing.volces.com"
    tos_region: str = "cn-beijing"
    redis_url: str = "redis://127.0.0.1:6379/0"
    replicate_api_token: str = "r8_LQsj9DBHCUHySUzDxGxG1nNHy4wj7oO2WReXp"

    class Config:
        env_file = ".env"
        env_file_encoding = "utf-8"


settings = Settings()
