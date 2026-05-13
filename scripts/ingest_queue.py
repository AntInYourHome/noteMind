"""
NoteMind — 持久化摄入队列

串行处理源文件，每处理完一个文件即保存进度。
支持崩溃恢复、--resume 从断点继续、取消和重试。

队列文件位于 vault 下的 .notemind/ingest_queue.json。

队列结构:
{
  "version": 1,
  "project_id": "vault_path_hash",
  "tasks": [
    {"id": "uuid", "path": "/abs/path/to/file.pdf", "status": "done", "retry_count": 0},
    {"id": "uuid", "path": "/abs/path/to/file2.pdf", "status": "pending", "retry_count": 0},
    {"id": "uuid", "path": "/abs/path/to/file3.pdf", "status": "failed", "retry_count": 2},
    ...
  ]
}
"""

import json
import logging
import os
import uuid
from typing import Optional

logger = logging.getLogger("notemind")

QUEUE_VERSION = 1
QUEUE_DIR = ".notemind"
QUEUE_FILENAME = "ingest_queue.json"
MAX_RETRIES = 3


class IngestTask:
    def __init__(self, file_path: str):
        self.id = str(uuid.uuid4())[:8]
        self.path = os.path.realpath(file_path)
        self.status = "pending"  # pending | processing | done | failed | cancelled
        self.retry_count = 0

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "path": self.path,
            "status": self.status,
            "retry_count": self.retry_count,
        }

    @classmethod
    def from_dict(cls, d: dict) -> "IngestTask":
        task = cls.__new__(cls)
        task.id = d["id"]
        task.path = d["path"]
        task.status = d["status"]
        task.retry_count = d.get("retry_count", 0)
        return task


class IngestQueue:
    """持久化摄入队列。"""

    def __init__(self, vault_path: str):
        self.vault_path = vault_path
        self.queue_dir = os.path.join(vault_path, QUEUE_DIR)
        self.queue_path = os.path.join(self.queue_dir, QUEUE_FILENAME)
        self.tasks: list[IngestTask] = []
        self._load()

    # ── 公共接口 ──────────────────────────────────────────────

    def enqueue_batch(self, files: list[str]) -> int:
        """批量入队。返回新增任务数（排除已存在的）。"""
        existing_paths = {t.path for t in self.tasks}
        new_count = 0
        for fp in files:
            rp = os.path.realpath(fp)
            if rp not in existing_paths:
                self.tasks.append(IngestTask(rp))
                new_count += 1
                existing_paths.add(rp)
        if new_count > 0:
            self._save()
        return new_count

    def get_next_pending(self) -> Optional[IngestTask]:
        """获取下一个待处理任务。"""
        for task in self.tasks:
            if task.status == "pending":
                return task
        return None

    def mark_processing(self, task_id: str) -> None:
        self._find(task_id).status = "processing"
        self._save()

    def mark_done(self, task_id: str) -> None:
        self._find(task_id).status = "done"
        self._save()

    def mark_failed(self, task_id: str) -> None:
        task = self._find(task_id)
        task.retry_count += 1
        if task.retry_count < MAX_RETRIES:
            task.status = "pending"  # 下次会重试
            logger.info(f"  任务 {task_id} 将重试 ({task.retry_count}/{MAX_RETRIES})")
        else:
            task.status = "failed"
            logger.warning(f"  任务 {task_id} 已达最大重试次数，标记为失败")
        self._save()

    def cancel(self, task_id: str) -> bool:
        task = self._find(task_id)
        if task.status in ("pending", "processing"):
            task.status = "cancelled"
            self._save()
            return True
        return False

    def retry_failed(self) -> int:
        """重置所有失败任务为 pending。返回重置数量。"""
        count = 0
        for task in self.tasks:
            if task.status == "failed":
                task.status = "pending"
                task.retry_count = 0
                count += 1
        if count > 0:
            self._save()
        return count

    def summary(self) -> dict:
        counts = {"pending": 0, "processing": 0, "done": 0, "failed": 0, "cancelled": 0}
        for t in self.tasks:
            counts[t.status] = counts.get(t.status, 0) + 1
        return {
            "total": len(self.tasks),
            **counts,
        }

    def is_empty(self) -> bool:
        return all(t.status in ("done", "cancelled", "failed") for t in self.tasks)

    def clear_completed(self) -> int:
        """清除已完成的任务。返回清除数量。"""
        before = len(self.tasks)
        self.tasks = [t for t in self.tasks if t.status not in ("done", "cancelled")]
        removed = before - len(self.tasks)
        if removed > 0:
            self._save()
        return removed

    # ── 内部实现 ──────────────────────────────────────────────

    def _find(self, task_id: str) -> IngestTask:
        for t in self.tasks:
            if t.id == task_id:
                return t
        raise KeyError(f"Task {task_id} not found")

    def _load(self) -> None:
        if not os.path.exists(self.queue_path):
            return
        try:
            with open(self.queue_path, "r", encoding="utf-8") as f:
                data = json.load(f)
            if data.get("version") != QUEUE_VERSION:
                logger.warning(f"队列版本不匹配，重建队列")
                return
            self.tasks = [IngestTask.from_dict(d) for d in data.get("tasks", [])]
            logger.info(f"  队列已恢复: {len(self.tasks)} 个任务")
        except (json.JSONDecodeError, IOError, KeyError) as e:
            logger.warning(f"队列加载失败，重建: {e}")
            self.tasks = []

    def _save(self) -> None:
        os.makedirs(self.queue_dir, exist_ok=True)
        data = {
            "version": QUEUE_VERSION,
            "project_id": self.vault_path,
            "tasks": [t.to_dict() for t in self.tasks],
        }
        with open(self.queue_path, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=2)
