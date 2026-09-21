"""
项目状态持久化服务 — 每步完成后将状态写入磁盘 JSON
"""
import json
from pathlib import Path
from config import settings

STATE_DIR = Path(settings.upload_dir) / "projects"
STATE_DIR.mkdir(parents=True, exist_ok=True)


def _state_file(project_id: str) -> Path:
    return STATE_DIR / f"{project_id}.json"


def load_project(project_id: str) -> dict:
    f = _state_file(project_id)
    if f.exists():
        return json.loads(f.read_text(encoding="utf-8"))
    return {}


def save_project(project_id: str, data: dict) -> None:
    f = _state_file(project_id)
    f.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")


def merge_project(project_id: str, patch: dict) -> dict:
    state = load_project(project_id)
    state.update(patch)
    save_project(project_id, state)
    return state


def list_projects() -> list[dict]:
    results = []
    for f in sorted(STATE_DIR.glob("*.json"), key=lambda p: p.stat().st_mtime, reverse=True):
        try:
            data = json.loads(f.read_text(encoding="utf-8"))
            entry = {
                "project_id": f.stem,
                "title":      data.get("title", "未命名"),
                "type":       data.get("type", "video"),
                "updated_at": data.get("updated_at", ""),
            }
            if data.get("type") in ("ppt", "drama"):
                entry["phase"] = data.get("phase", "review")
            else:
                entry["step"] = data.get("step", 1)
            results.append(entry)
        except Exception:
            pass
    return results
