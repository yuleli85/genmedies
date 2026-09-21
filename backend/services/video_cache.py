"""
视频 Prompt 级缓存(Redis + 文件双层)

- key = md5(image_bytes) + prompt + duration + provider
- 主索引: Redis key=genvoid:vid:<md5> -> 缓存文件路径, TTL 72h
- 回退索引: uploads/video_cache.json (Redis 不可用时)
- 内容存储: uploads/video_cache/<md5>.mp4 (始终落盘)
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

_CACHE_FILE = Path("uploads/video_cache.json")
_CACHE_DIR = Path("uploads/video_cache")
TTL = 72 * 3600

_REDIS_PREFIX = "genvoid:vid:"
_redis_client = None
_redis_tried = False


def _get_redis():
    global _redis_client, _redis_tried
    if _redis_tried:
        return _redis_client
    _redis_tried = True
    if redis is None:
        logging.warning("[video_cache] redis-py 未安装,使用文件回退")
        return None
    try:
        client = redis.Redis.from_url(
            settings.redis_url,
            socket_connect_timeout=1,
            socket_timeout=1,
            decode_responses=True,
        )
        client.ping()
        _redis_client = client
        logging.info("[video_cache] Redis 已连接")
    except Exception as e:
        logging.warning("[video_cache] Redis 不可用: %s,使用文件回退", e)
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


def scene_key(image_path: Path, prompt: str, duration: int, provider: str = "local") -> str:
    h = hashlib.md5()
    image_path = Path(image_path)
    if image_path.exists():
        h.update(image_path.read_bytes())
    h.update((prompt or "").encode("utf-8"))
    h.update(str(duration).encode("utf-8"))
    h.update(provider.encode("utf-8"))
    return h.hexdigest()


def get(image_path: Path, prompt: str, duration: int, provider: str = "local") -> Path | None:
    image_path = Path(image_path)
    if not image_path.exists():
        return None
    key = scene_key(image_path, prompt, duration, provider)

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
            logging.warning("[video_cache] Redis get 失败: %s", e)

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


def put(image_path: Path, prompt: str, duration: int, video_path: Path, provider: str = "local") -> None:
    image_path = Path(image_path)
    video_path = Path(video_path)
    if not image_path.exists() or not video_path.exists():
        return
    key = scene_key(image_path, prompt, duration, provider)
    _CACHE_DIR.mkdir(parents=True, exist_ok=True)
    cached = _CACHE_DIR / f"{key}.mp4"
    try:
        shutil.copy2(video_path, cached)
    except Exception as e:
        logging.warning("[video_cache] 复制到缓存目录失败: %s", e)
        return

    r = _get_redis()
    if r is not None:
        try:
            r.setex(_REDIS_PREFIX + key, TTL, str(cached))
        except Exception as e:
            logging.warning("[video_cache] Redis put 失败: %s", e)

    cache = _load_file_index()
    cache[key] = {"path": str(cached), "ts": time.time()}
    _save_file_index(cache)
