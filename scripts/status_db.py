"""SQLite-based file processing status tracking."""

import hashlib
import os
import sqlite3
from datetime import datetime
from typing import Optional, Tuple


DB_NAME = ".notemind_status.db"


class StatusDB:
    """状态数据库管理器，显式生命周期管理。"""

    def __init__(self, vault_path: str):
        self.vault_path = vault_path
        self.db_path = os.path.join(vault_path, DB_NAME)
        self._conn: Optional[sqlite3.Connection] = None

    def connect(self) -> "StatusDB":
        """打开连接，创建表结构（如果不存在）。"""
        if self._conn is not None:
            return self
        os.makedirs(self.vault_path, exist_ok=True)
        self._conn = sqlite3.connect(self.db_path)
        self._conn.execute("""
            CREATE TABLE IF NOT EXISTS file_status (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                source_path TEXT UNIQUE,
                file_name TEXT,
                status TEXT,
                md_path TEXT,
                category TEXT,
                error TEXT,
                file_size INTEGER,
                file_mtime TEXT,
                file_md5 TEXT,
                processed_at TEXT
            )
        """)
        self._conn.execute("CREATE INDEX IF NOT EXISTS idx_source ON file_status(source_path)")
        self._conn.commit()
        return self

    def close(self) -> None:
        """关闭连接。"""
        if self._conn:
            try:
                self._conn.close()
            except Exception:
                pass
            self._conn = None

    @staticmethod
    def compute_hash(file_path: str) -> str:
        """计算文件 MD5。"""
        h = hashlib.md5()
        with open(file_path, "rb") as f:
            for chunk in iter(lambda: f.read(8192), b""):
                h.update(chunk)
        return h.hexdigest()

    def _file_info(self, file_path: str) -> tuple:
        """获取文件元信息。"""
        try:
            file_size = os.path.getsize(file_path)
            file_mtime = datetime.fromtimestamp(os.path.getmtime(file_path)).strftime("%Y-%m-%d %H:%M:%S")
            file_md5 = self.compute_hash(file_path)
        except Exception:
            file_size = 0
            file_mtime = ""
            file_md5 = ""
        return file_size, file_mtime, file_md5

    def check_updated(self, file_path: str) -> Tuple[Optional[str], bool]:
        """检查文件是否有更新。

        Returns:
            (previous_status, is_updated)
        """
        if self._conn is None:
            self.connect()
        file_size = os.path.getsize(file_path)
        current_md5 = self.compute_hash(file_path)

        row = self._conn.execute(
            "SELECT status, file_size, file_mtime, file_md5 FROM file_status WHERE source_path = ?",
            (file_path,)
        ).fetchone()

        if row is None:
            return None, True  # 新文件

        prev_status, prev_size, prev_mtime, prev_md5 = row
        is_updated = (prev_md5 != current_md5) or (prev_size != file_size)
        return prev_status, is_updated

    def record(self, file_path: str, status_type: str, md_path: str = None,
               category: str = None, error: str = None) -> None:
        """记录单个文件的处理状态。

        Args:
            file_path: 源文件路径
            status_type: "success" | "failed" | "updated" | "unchanged" | "unsupported"
            md_path: 生成的 MD 文件路径
            category: 分类路径
            error: 错误信息
        """
        if self._conn is None:
            self.connect()
        file_name = os.path.basename(file_path)
        processed_at = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        file_size, file_mtime, file_md5 = self._file_info(file_path)

        try:
            self._conn.execute("""
                INSERT OR REPLACE INTO file_status
                (source_path, file_name, status, md_path, category, error, file_size, file_mtime, file_md5, processed_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """, (file_path, file_name, status_type, md_path, category, error, file_size, file_mtime, file_md5, processed_at))
            self._conn.commit()
        except sqlite3.Error as e:
            import logging
            logging.getLogger("notemind").warning(f"  状态记录失败: {e}")

    def summary(self) -> dict:
        """获取处理状态统计。"""
        if self._conn is None:
            self.connect()
        result = {"success": 0, "failed": 0, "updated": 0, "unchanged": 0}
        for row in self._conn.execute("SELECT status, COUNT(*) FROM file_status GROUP BY status"):
            status, count = row
            result[status] = count
        return result

    def get_unsupported_entries(self) -> list:
        """获取所有不支持格式的文件记录。"""
        if self._conn is None:
            self.connect()
        cursor = self._conn.execute(
            "SELECT source_path, category FROM file_status WHERE status = 'unsupported'"
        )
        return cursor.fetchall()

    def reset(self) -> None:
        """重置连接（用于新 vault）。"""
        try:
            if self._conn:
                self._conn.close()
        except Exception:
            pass
        self._conn = None


# --- 全局兼容接口（过渡期，供 import.py 旧代码调用）---

_status_db_conn = None


def _get_status_db(vault_path: str) -> sqlite3.Connection:
    """兼容旧接口：获取状态数据库连接（单例）。"""
    global _status_db_conn
    if _status_db_conn is not None:
        return _status_db_conn
    db_path = os.path.join(vault_path, DB_NAME)
    os.makedirs(vault_path, exist_ok=True)
    conn = sqlite3.connect(db_path)
    conn.execute("""
        CREATE TABLE IF NOT EXISTS file_status (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            source_path TEXT UNIQUE,
            file_name TEXT,
            status TEXT,
            md_path TEXT,
            category TEXT,
            error TEXT,
            file_size INTEGER,
            file_mtime TEXT,
            file_md5 TEXT,
            processed_at TEXT
        )
    """)
    conn.execute("CREATE INDEX IF NOT EXISTS idx_source ON file_status(source_path)")
    conn.commit()
    _status_db_conn = conn
    return conn


def _close_status_db():
    """兼容旧接口。"""
    global _status_db_conn
    if _status_db_conn:
        try:
            _status_db_conn.close()
        except Exception:
            pass
        _status_db_conn = None


def _reset_status_db():
    """兼容旧接口。"""
    global _status_db_conn
    try:
        if _status_db_conn:
            _status_db_conn.close()
    except Exception:
        pass
    _status_db_conn = None
