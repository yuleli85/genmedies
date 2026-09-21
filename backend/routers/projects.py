"""
项目管理路由
GET  /api/projects              — 列出所有已保存项目
GET  /api/projects/{id}         — 读取项目状态
POST /api/projects/{id}         — 保存/更新项目状态
DELETE /api/projects/{id}       — 删除项目
"""
from datetime import datetime
from fastapi import APIRouter, HTTPException
from services.project_store import load_project, save_project, merge_project, list_projects

router = APIRouter(prefix="/api/projects", tags=["projects"])


@router.get("")
async def get_projects():
    return list_projects()


@router.get("/{project_id}")
async def get_project(project_id: str):
    data = load_project(project_id)
    if not data:
        raise HTTPException(404, "项目不存在")
    return data


@router.post("/{project_id}")
async def update_project(project_id: str, body: dict):
    body["updated_at"] = datetime.utcnow().isoformat()
    state = merge_project(project_id, body)
    return state


@router.delete("/{project_id}")
async def delete_project(project_id: str):
    from pathlib import Path
    from config import settings
    f = Path(settings.upload_dir) / "projects" / f"{project_id}.json"
    if f.exists():
        f.unlink()
    return {"ok": True}
