"""
分镜缓存 — 以文章内容 MD5 为 key，TTL 72 小时
"""
import hashlib
import json
import time
from pathlib import Path

_CACHE_FILE = Path("uploads/scenes_cache.json")
TTL = 72 * 3600


def _load() -> dict:
    if _CACHE_FILE.exists():
        try:
            return json.loads(_CACHE_FILE.read_text(encoding="utf-8"))
        except Exception:
            return {}
    return {}


def _save(cache: dict) -> None:
    _CACHE_FILE.parent.mkdir(parents=True, exist_ok=True)
    _CACHE_FILE.write_text(json.dumps(cache, ensure_ascii=False, indent=2), encoding="utf-8")


def content_key(text: str) -> str:
    return hashlib.md5(text.strip().encode("utf-8")).hexdigest()


def get(text: str) -> dict | None:
    key = content_key(text)
    cache = _load()
    entry = cache.get(key)
    if not entry:
        return None
    if time.time() - entry.get("ts", 0) > TTL:
        del cache[key]
        _save(cache)
        return None
    return entry["data"]


def set(text: str, result: dict) -> None:
    cache = _load()
    cache[content_key(text)] = {"data": result, "ts": time.time()}
    _save(cache)
