"""
图片 Prompt 级缓存(Redis + 文件双层)

- 主索引: Redis key=genvoid:img:<md5(prompt)> -> 缓存文件路径, TTL 72h
- 回退索引: uploads/image_cache.json (Redis 不可用时)
- 内容存储: uploads/image_cache/<md5>.<ext> (始终落盘)

接口:
  get(prompt)              命中返回缓存图片 Path, 未命中返回 None
  put(prompt, image_path)  把新图片登记到缓存
  prompt_key(prompt)       获取规范化 MD5
"""
import hashlib
import json
import logging
import shutil
import time
from pathlib import Path

try:
    import redis
except ImportError:
    redis = None

from config import settings

_CACHE_FILE = Path("uploads/image_cache.json")
_CACHE_DIR = Path("uploads/image_cache")
TTL = 72 * 3600

_REDIS_PREFIX = "genvoid:img:"
_redis_client = None
_redis_tried = False


def _get_redis():
    global _redis_client, _redis_tried
    if _redis_tried:
        return _redis_client
    _redis_tried = True
    if redis is None:
        logging.warning("[image_cache] redis-py 未安装,使用文件回退")
        return None
    url = settings.redis_url
    try:
        client = redis.Redis.from_url(
            url,
            socket_connect_timeout=1,
            socket_timeout=1,
            decode_responses=True,
        )
        client.ping()
        _redis_client = client
        # 日志不输出 URL,避免密码泄露
        logging.info("[image_cache] Redis 已连接")
    except Exception as e:
        logging.warning("[image_cache] Redis 不可用: %s,使用文件回退", e)
    return _redis_client


def _load_file_index() -> dict:
    if _CACHE_FILE.exists():
        try:
            return json.loads(_CACHE_FILE.read_text(encoding="utf-8"))
        except Exception:
            return {}
    return {}


def _save_file_index(cache: dict) -> None:
    _CACHE_FILE.parent.mkdir(parents=True, exist_ok=True)
    _CACHE_FILE.write_text(json.dumps(cache, ensure_ascii=False, indent=2), encoding="utf-8")


def prompt_key(prompt: str) -> str:
    return hashlib.md5(prompt.strip().encode("utf-8")).hexdigest()


def get(prompt: str) -> Path | None:
    if not prompt or not prompt.strip():
        return None
    key = prompt_key(prompt)

    r = _get_redis()
    if r is not None:
        try:
            path_str = r.get(_REDIS_PREFIX + key)
            if path_str:
                p = Path(path_str)
                if p.exists():
                    return p
                r.delete(_REDIS_PREFIX + key)
        except Exception as e:
            logging.warning("[image_cache] Redis get 失败: %s", e)

    cache = _load_file_index()
    entry = cache.get(key)
    if not entry:
        return None
    if time.time() - entry.get("ts", 0) > TTL:
        Path(entry.get("path", "")).unlink(missing_ok=True)
        del cache[key]
        _save_file_index(cache)
        return None
    p = Path(entry["path"])
    if not p.exists():
        return None
    if r is not None:
        try:
            r.setex(_REDIS_PREFIX + key, TTL, str(p))
        except Exception:
            pass
    return p


def put(prompt: str, image_path: Path) -> None:
    if not prompt or not prompt.strip():
        return
    image_path = Path(image_path)
    if not image_path.exists():
        return
    key = prompt_key(prompt)
    _CACHE_DIR.mkdir(parents=True, exist_ok=True)
    ext = image_path.suffix or ".png"
    cached = _CACHE_DIR / f"{key}{ext}"
    try:
        shutil.copy2(image_path, cached)
    except Exception as e:
        logging.warning("[image_cache] 复制到缓存目录失败: %s", e)
        return

    r = _get_redis()
    if r is not None:
        try:
            r.setex(_REDIS_PREFIX + key, TTL, str(cached))
        except Exception as e:
            logging.warning("[image_cache] Redis put 失败: %s", e)

    cache = _load_file_index()
    cache[key] = {"path": str(cached), "ts": time.time()}
    _save_file_index(cache)
