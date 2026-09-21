"""
任务状态管理 — 内存存储（生产环境可换 Redis）
"""
import uuid
from datetime import datetime
from enum import Enum
from typing import Any
from pydantic import BaseModel


class TaskStatus(str, Enum):
    PENDING = "pending"
    RUNNING = "running"
    DONE = "done"
    ERROR = "error"


class Task(BaseModel):
    task_id: str
    status: TaskStatus = TaskStatus.PENDING
    progress: int = 0          # 0-100
    message: str = ""
    result: Any = None
    created_at: str = ""
    updated_at: str = ""


_store: dict[str, Task] = {}


def create_task() -> Task:
    tid = str(uuid.uuid4())
    now = datetime.utcnow().isoformat()
    t = Task(task_id=tid, created_at=now, updated_at=now)
    _store[tid] = t
    return t


def get_task(task_id: str) -> Task | None:
    return _store.get(task_id)


def update_task(task_id: str, **kwargs) -> Task:
    t = _store[task_id]
    for k, v in kwargs.items():
        setattr(t, k, v)
    t.updated_at = datetime.utcnow().isoformat()
    return t
