"""
NoteMind 文档记忆 — 轻量级 SQLite 存储已处理文档的元数据和知识
"""

import json
import os
import sqlite3
from datetime import datetime
from pathlib import Path


class MemoryStore:
    """SQLite 文档记忆存储。"""

    def __init__(self, db_path: str = ".notemind_memory.db"):
        self.db_path = db_path
        self._init_db()

    def _connect(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        return conn

    def _init_db(self):
        """初始化数据库表。"""
        with self._connect() as conn:
            conn.execute("""
                CREATE TABLE IF NOT EXISTS documents (
                    id TEXT PRIMARY KEY,
                    filename TEXT,
                    category TEXT,
                    tags TEXT,
                    summary TEXT,
                    sections TEXT,
                    processed_at TEXT,
                    file_size INTEGER,
                    word_count INTEGER
                )
            """)
            conn.execute("""
                CREATE TABLE IF NOT EXISTS knowledge_index (
                    tag TEXT,
                    doc_id TEXT,
                    FOREIGN KEY (doc_id) REFERENCES documents(id)
                )
            """)
            conn.execute("""
                CREATE INDEX IF NOT EXISTS idx_knowledge_tag ON knowledge_index(tag)
            """)
            conn.execute("""
                CREATE INDEX IF NOT EXISTS idx_documents_category ON documents(category)
            """)

    def store_document(self, doc_id: str, filename: str, category: str,
                       tags: list[str], summary: str, sections: list[dict] = None,
                       file_size: int = 0, word_count: int = 0):
        """存储已处理文档的信息。"""
        with self._connect() as conn:
            conn.execute(
                "INSERT OR REPLACE INTO documents VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (
                    doc_id,
                    filename,
                    category,
                    json.dumps(tags, ensure_ascii=False),
                    summary,
                    json.dumps(sections, ensure_ascii=False) if sections else None,
                    datetime.now().isoformat(),
                    file_size,
                    word_count,
                )
            )
            # 更新标签索引
            conn.execute("DELETE FROM knowledge_index WHERE doc_id = ?", (doc_id,))
            for tag in tags:
                conn.execute(
                    "INSERT INTO knowledge_index (tag, doc_id) VALUES (?, ?)",
                    (tag, doc_id)
                )

    def get_document(self, doc_id: str) -> dict | None:
        """根据 ID 获取文档记忆。"""
        with self._connect() as conn:
            row = conn.execute("SELECT * FROM documents WHERE id = ?", (doc_id,)).fetchone()
            if row is None:
                return None
            return {
                "id": row["id"],
                "filename": row["filename"],
                "category": row["category"],
                "tags": json.loads(row["tags"]) if row["tags"] else [],
                "summary": row["summary"] or "",
                "sections": json.loads(row["sections"]) if row["sections"] else [],
                "processed_at": row["processed_at"],
                "file_size": row["file_size"],
                "word_count": row["word_count"],
            }

    def get_related_documents(self, tags: list[str] = None, category: str = None,
                              limit: int = 5) -> list[dict]:
        """查找相似文档（基于标签或分类）。"""
        with self._connect() as conn:
            if tags:
                placeholders = ",".join(["?"] * len(tags))
                rows = conn.execute(f"""
                    SELECT DISTINCT d.* FROM documents d
                    JOIN knowledge_index ki ON d.id = ki.doc_id
                    WHERE ki.tag IN ({placeholders})
                    ORDER BY d.processed_at DESC
                    LIMIT ?
                """, (*tags, limit)).fetchall()
            elif category:
                rows = conn.execute("""
                    SELECT * FROM documents WHERE category = ?
                    ORDER BY processed_at DESC
                    LIMIT ?
                """, (category, limit)).fetchall()
            else:
                rows = conn.execute("""
                    SELECT * FROM documents ORDER BY processed_at DESC LIMIT ?
                """, (limit,)).fetchall()

            results = []
            for row in rows:
                results.append({
                    "filename": row["filename"],
                    "category": row["category"],
                    "tags": json.loads(row["tags"]) if row["tags"] else [],
                    "summary": (row["summary"] or "")[:200],
                })
            return results

    def build_memory_context(self, tags: list[str] = None, category: str = None) -> str:
        """为 AI 生成记忆上下文提示。"""
        related = self.get_related_documents(tags, category, limit=3)
        if not related:
            return ""

        lines = ["\n\n参考记忆（已处理过的类似文档）："]
        for i, doc in enumerate(related, 1):
            lines.append(f"  {i}. 《{doc['filename']}》 → 分类: {doc['category']}, 标签: {', '.join(doc['tags'][:3])}")
            if doc["summary"]:
                lines.append(f"     摘要: {doc['summary'][:100]}...")
        return "\n".join(lines)

    def get_stats(self) -> dict:
        """获取记忆库统计。"""
        with self._connect() as conn:
            doc_count = conn.execute("SELECT COUNT(*) as c FROM documents").fetchone()["c"]
            tag_count = conn.execute("SELECT COUNT(DISTINCT tag) as c FROM knowledge_index").fetchone()["c"]
            categories = conn.execute(
                "SELECT category, COUNT(*) as c FROM documents GROUP BY category ORDER BY c DESC"
            ).fetchall()
            return {
                "documents": doc_count,
                "unique_tags": tag_count,
                "categories": [{"name": r["category"], "count": r["c"]} for r in categories],
            }

    def close(self):
        """关闭连接（SQLite 自动提交）。"""
        pass  # SQLite context manager handles it
