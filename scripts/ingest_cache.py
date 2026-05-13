"""
NoteMind — SHA256 增量缓存

缓存源文件内容哈希，跳过未变更文件的重新处理。
缓存文件位于 vault 下的 .notemind/ingest_cache.json。

缓存结构:
{
  "version": 1,
  "entries": {
    "/absolute/path/to/source.pdf": {
      "sha256": "abc123...",
      "processed_at": "2026-05-12T10:00:00Z",
      "output_files": ["wiki/entities/xxx.md", "wiki/concepts/yyy.md"],
      "category": "技术文档",
      "tags": ["AI", "机器学习"]
    }
  }
}
"""

import hashlib
import json
import logging
import os
from pathlib import Path
from typing import Optional

logger = logging.getLogger("notemind")

CACHE_VERSION = 1
CACHE_DIR = ".notemind"
CACHE_FILENAME = "ingest_cache.json"


class IngestCache:
    """SHA256 增量缓存管理器。线程安全（单进程场景足够）。"""

    def __init__(self, vault_path: str):
        self.vault_path = vault_path
        self.cache_dir = os.path.join(vault_path, CACHE_DIR)
        self.cache_path = os.path.join(self.cache_dir, CACHE_FILENAME)
        self._data: dict = self._load()

    # ── 公共接口 ──────────────────────────────────────────────

    def get(self, source_path: str) -> Optional[dict]:
        """获取缓存条目。返回 None 表示未命中。"""
        key = os.path.realpath(source_path)
        entry = self._data.get("entries", {}).get(key)
        if entry is None:
            return None
        # 验证文件仍然存在且哈希匹配
        if not os.path.exists(key):
            self.invalidate(key)
            return None
        return entry

    def put(self, source_path: str, sha256: str, output_files: list[str],
            category: str = "", tags: list[str] = None) -> None:
        """写入缓存条目。"""
        from datetime import datetime
        key = os.path.realpath(source_path)
        self._data.setdefault("entries", {})[key] = {
            "sha256": sha256,
            "processed_at": datetime.utcnow().isoformat() + "Z",
            "output_files": output_files,
            "category": category,
            "tags": tags or [],
        }
        self._save()

    def invalidate(self, source_path: str) -> bool:
        """使指定源的缓存失效。返回是否成功删除。"""
        key = os.path.realpath(source_path)
        return self._data.get("entries", {}).pop(key, None) is not None

    def invalidate_all(self) -> int:
        """清空所有缓存。返回删除数量。"""
        count = len(self._data.get("entries", {}))
        self._data["entries"] = {}
        self._save()
        return count

    def stats(self) -> dict:
        """返回缓存统计信息。"""
        entries = self._data.get("entries", {})
        return {
            "total": len(entries),
            "cache_size_bytes": os.path.getsize(self.cache_path) if os.path.exists(self.cache_path) else 0,
        }

    # ── 内部实现 ──────────────────────────────────────────────

    def _load(self) -> dict:
        """从磁盘加载缓存。"""
        if not os.path.exists(self.cache_path):
            return {"version": CACHE_VERSION, "entries": {}}
        try:
            with open(self.cache_path, "r", encoding="utf-8") as f:
                data = json.load(f)
            if data.get("version") != CACHE_VERSION:
                logger.warning(f"缓存版本不匹配 (期望 {CACHE_VERSION}, 实际 {data.get('version')})，重建缓存")
                return {"version": CACHE_VERSION, "entries": {}}
            return data
        except (json.JSONDecodeError, IOError) as e:
            logger.warning(f"缓存加载失败，重建: {e}")
            return {"version": CACHE_VERSION, "entries": {}}

    def _save(self) -> None:
        """持久化缓存到磁盘。"""
        os.makedirs(self.cache_dir, exist_ok=True)
        self._data["version"] = CACHE_VERSION
        with open(self.cache_path, "w", encoding="utf-8") as f:
            json.dump(self._data, f, ensure_ascii=False, indent=2)


def compute_sha256(file_path: str) -> str:
    """计算文件 SHA256 哈希。"""
    h = hashlib.sha256()
    with open(file_path, "rb") as f:
        for chunk in iter(lambda: f.read(65536), b""):
            h.update(chunk)
    return h.hexdigest()


def check_cache_hit(cache: IngestCache, source_path: str) -> Optional[dict]:
    """
    检查缓存是否命中。命中时返回缓存条目，并在日志中记录跳过信息。

    返回值:
        dict: 缓存条目（包含 output_files, category, tags）
        None: 未命中，需要正常处理
    """
    current_hash = compute_sha256(source_path)
    entry = cache.get(source_path)

    if entry is not None and entry["sha256"] == current_hash:
        fname = os.path.basename(source_path)
        logger.info(f"  [CACHE HIT] {fname} — 内容未变更，跳过处理")
        return entry

    return None
