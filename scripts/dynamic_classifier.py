"""
NoteMind 动态分类器 — 基于 embedding 相似度 + AI 验证的动态分类引擎

一级分类保持固定（关键词匹配），二级/三级分类通过 SQLite 主题群动态生成。
"""

import json
import logging
import math
import os
import sqlite3

logger = logging.getLogger("notemind")

# 分类阈值
MATCH_THRESHOLD = 0.65       # embedding 直接匹配阈值
AI_VALIDATE_THRESHOLD = 0.45 # embedding AI 验证下限
KEYWORD_MATCH_THRESHOLD = 0.2  # 关键词匹配阈值（离线模式，初期关键词少）


class DynamicClassifier:
    """动态分类引擎。"""

    def __init__(self, db_path: str):
        self.db_path = db_path
        self._ensure_schema()

    def _ensure_schema(self):
        """确保 SQLite schema 存在。"""
        conn = sqlite3.connect(self.db_path)
        conn.executescript("""
            CREATE TABLE IF NOT EXISTS topic_clusters (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                name TEXT NOT NULL,
                level1 TEXT NOT NULL,
                level2 TEXT,
                level3 TEXT,
                description TEXT,
                centroid_embedding BLOB,
                doc_count INTEGER DEFAULT 0,
                status TEXT DEFAULT 'active',
                UNIQUE(name, level1)
            );
            CREATE TABLE IF NOT EXISTS topic_members (
                topic_id INTEGER,
                doc_id TEXT,
                score REAL DEFAULT 1.0,
                PRIMARY KEY (topic_id, doc_id)
            );
            CREATE TABLE IF NOT EXISTS topic_keywords (
                topic_id INTEGER,
                keyword TEXT,
                weight REAL DEFAULT 1.0,
                PRIMARY KEY (topic_id, keyword)
            );
            CREATE TABLE IF NOT EXISTS document_vectors (
                doc_id TEXT PRIMARY KEY,
                embedding BLOB,
                embedding_model TEXT DEFAULT 'text-embedding-v3'
            );
            CREATE INDEX IF NOT EXISTS idx_topic_l1 ON topic_clusters(level1, status);
            CREATE INDEX IF NOT EXISTS idx_members_doc ON topic_members(doc_id);
        """)
        conn.close()

    def classify(self, text: str, title: str = "", tags: list[str] = None,
                 doc_id: str = "") -> tuple[str, list[str]]:
        """动态分类入口。

        Args:
            text: 文档摘要/分类输入文本
            title: 文档标题
            tags: 已有标签列表
            doc_id: 文档唯一标识（MD5 或文件名）

        Returns:
            (完整分类路径, 文档类型标签列表)
        """
        from scripts.classifier import LEVEL1_KEYWORDS

        # Step 1: 一级分类（固定，关键词匹配）
        level1 = _match_level1(text, title, LEVEL1_KEYWORDS)
        if not level1:
            return "其他", []

        # Step 2: 计算 embedding（在线）或提取关键词（离线）
        embedding = None
        try:
            from scripts.ai_client import generate_embedding
            embedding = generate_embedding(text[:8000])
        except Exception as e:
            logger.debug(f"  [动态分类] Embedding 不可用: {e}")

        if not embedding:
            # 离线模式：使用关键词匹配降级
            level2, level3 = self._classify_by_keywords(text, title, level1, doc_id)
            doc_type_tags = _extract_doc_type_tags(text, title)
            parts = [level1]
            if level2:
                parts.append(level2)
            if level3:
                parts.append(level3)
            return "/".join(parts), doc_type_tags

        # Step 3: 查找候选主题群
        candidates = self._find_candidates(level1, embedding, top_k=10)

        # Step 4: 分配或创建
        doc_id = doc_id or title or "unknown"
        level2, level3 = None, None

        if candidates and candidates[0]["score"] >= MATCH_THRESHOLD:
            # 直接匹配
            best = candidates[0]
            level2 = best.get("level2")
            level3 = best.get("level3")
            self._assign_to_topic(doc_id, best["id"], best["score"])
            logger.info(f"  [动态分类] 匹配主题: {best['name']} (score={best['score']:.3f})")
        elif candidates and candidates[0]["score"] >= AI_VALIDATE_THRESHOLD:
            # AI 验证
            best = candidates[0]
            if self._ai_validate(text, title, best["name"], best.get("description", ""),
                                  best["score"]):
                level2 = best.get("level2")
                level3 = best.get("level3")
                self._assign_to_topic(doc_id, best["id"], best["score"])
                logger.info(f"  [动态分类] AI 验证通过: {best['name']} (score={best['score']:.3f})")
            else:
                level2, level3 = self._create_new_topic(doc_id, text, title, level1, embedding)
                logger.info(f"  [动态分类] AI 拒绝匹配，创建新主题: {level2}/{level3}")
        else:
            # 创建新主题
            level2, level3 = self._create_new_topic(doc_id, text, title, level1, embedding)
            logger.info(f"  [动态分类] 无匹配候选，创建新主题: {level2}/{level3}")

        # 存储 embedding
        if doc_id:
            self._store_embedding(doc_id, embedding)

        # 构建完整路径
        parts = [level1]
        if level2:
            parts.append(level2)
        if level3:
            parts.append(level3)
        full_path = "/".join(parts)

        # 文档类型标签（回退到静态分类器）
        doc_type_tags = _extract_doc_type_tags(text, title)

        return full_path, doc_type_tags

    def _find_candidates(self, level1: str, embedding: list[float],
                         top_k: int = 10) -> list[dict]:
        """在指定一级分类下查找相似主题群。"""
        import struct

        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        rows = conn.execute(
            "SELECT id, name, level2, level3, description, centroid_embedding, doc_count "
            "FROM topic_clusters WHERE level1 = ? AND status = 'active'",
            (level1,)
        ).fetchall()

        candidates = []
        dim = len(embedding)
        for row in rows:
            if row["centroid_embedding"]:
                centroid = list(struct.unpack(f"{dim}f", row["centroid_embedding"]))
                score = cosine_similarity(embedding, centroid)
                candidates.append({
                    "id": row["id"],
                    "name": row["name"],
                    "level2": row["level2"],
                    "level3": row["level3"],
                    "description": row["description"],
                    "score": score,
                    "doc_count": row["doc_count"],
                })

        conn.close()
        candidates.sort(key=lambda x: x["score"], reverse=True)
        return candidates[:top_k]

    def _classify_by_keywords(self, text: str, title: str, level1: str,
                               doc_id: str) -> tuple[str | None, str | None]:
        """离线模式：基于关键词匹配分类。

        策略：提取文档中的 2-4 字关键词，与 topic_keywords 表比对，
        得分最高的主题群即为分类结果。
        """
        candidates = self._find_candidates_by_keywords(level1, text, title)

        if candidates and candidates[0]["score"] >= KEYWORD_MATCH_THRESHOLD:
            best = candidates[0]
            self._assign_to_topic_keyword(doc_id, best["id"], best["score"])
            logger.info(f"  [动态分类] 关键词匹配: {best['name']} (score={best['score']:.3f})")
            return best.get("level2"), best.get("level3")

        # 无匹配：AI 创建新主题（如果 AI 可用）
        try:
            level2, level3 = self._create_new_topic(doc_id, text, title, level1, None)
            logger.info(f"  [动态分类] 无匹配，创建新主题: {level2}/{level3}")
            return level2, level3
        except Exception:
            logger.warning("  [动态分类] AI 不可用，回退到一级分类")
            return None, None

    def _find_candidates_by_keywords(self, level1: str, text: str,
                                      title: str, top_k: int = 10) -> list[dict]:
        """关键词匹配：比对 topic_keywords 表。"""
        import re

        # 提取文档关键词（2-4 字中文词组 + 已有标签）
        doc_keywords = set()
        # 从文本中提取常见中文词组
        for n in range(2, 5):
            for match in re.finditer(r'[\u4e00-\u9fff]{' + str(n) + r'}', text[:3000]):
                word = match.group()
                # 过滤停用词
                if len(word) >= 2:
                    doc_keywords.add(word)
        # 加入标题
        for match in re.finditer(r'[\u4e00-\u9fff]{2,6}', title):
            doc_keywords.add(match.group())

        conn = sqlite3.connect(self.db_path)
        rows = conn.execute(
            "SELECT id, name, level2, level3, doc_count FROM topic_clusters "
            "WHERE level1 = ? AND status = 'active'",
            (level1,)
        ).fetchall()

        candidates = []
        for row in rows:
            topic_id = row[0]
            # 获取该主题的关键词
            kw_rows = conn.execute(
                "SELECT keyword, weight FROM topic_keywords WHERE topic_id = ?",
                (topic_id,)
            ).fetchall()
            topic_kw = {r[0]: r[1] for r in kw_rows}

            if not topic_kw:
                # 没有关键词的主题，跳过
                continue

            # 计算匹配得分：匹配关键词的权重和 / 总权重
            matched_score = sum(w for kw, w in topic_kw.items() if kw in doc_keywords)
            total_score = sum(topic_kw.values())
            score = matched_score / total_score if total_score > 0 else 0.0

            if score > 0:
                candidates.append({
                    "id": topic_id,
                    "name": row[1],
                    "level2": row[2],
                    "level3": row[3],
                    "score": score,
                    "doc_count": row[4],
                })

        conn.close()
        candidates.sort(key=lambda x: x["score"], reverse=True)
        return candidates[:top_k]

    def _assign_to_topic_keyword(self, doc_id: str, topic_id: int, score: float):
        """关键词模式下分配文档（不更新 centroid）。"""
        conn = sqlite3.connect(self.db_path)
        conn.execute(
            "UPDATE topic_clusters SET doc_count = doc_count + 1 WHERE id = ?",
            (topic_id,)
        )
        conn.execute(
            "INSERT OR IGNORE INTO topic_members (topic_id, doc_id, score) VALUES (?, ?, ?)",
            (topic_id, doc_id, score)
        )
        conn.commit()
        conn.close()

    def _assign_to_topic(self, doc_id: str, topic_id: int, score: float):
        """将文档分配给主题群，更新 centroid 和 doc_count。"""
        import struct

        conn = sqlite3.connect(self.db_path)
        # 获取当前 centroid 和 doc_count
        row = conn.execute(
            "SELECT centroid_embedding, doc_count FROM topic_clusters WHERE id = ?",
            (topic_id,)
        ).fetchone()
        if not row:
            conn.close()
            return

        dim = 1024  # 假设维度
        if row["centroid_embedding"]:
            old_centroid = list(struct.unpack(f"{dim}f", row["centroid_embedding"]))
        else:
            old_centroid = [0.0] * dim

        n = row["doc_count"] or 0
        # 增量更新 centroid
        new_centroid = [(old_centroid[i] * n + 1.0) / (n + 1) for i in range(dim)]
        # 归一化
        norm = math.sqrt(sum(x * x for x in new_centroid))
        if norm > 0:
            new_centroid = [x / norm for x in new_centroid]

        conn.execute(
            "UPDATE topic_clusters SET centroid_embedding = ?, doc_count = doc_count + 1 "
            "WHERE id = ?",
            (struct.pack(f"{dim}f", *new_centroid), topic_id)
        )
        conn.execute(
            "INSERT OR IGNORE INTO topic_members (topic_id, doc_id, score) VALUES (?, ?, ?)",
            (topic_id, doc_id, score)
        )
        conn.commit()
        conn.close()

    def _create_new_topic(self, doc_id: str, text: str, title: str,
                          level1: str, embedding: list[float]) -> tuple[str | None, str | None]:
        """通过 AI 创建新主题群。"""
        import struct

        from scripts.ai_client import _call_api

        messages = [
            {
                "role": "system",
                "content": (
                    "你是文档主题分析专家。根据文档内容，判断它属于哪个二级/三级分类。"
                    "如果这是全新主题领域，请创建新的分类名称。"
                    "输出 JSON 格式: {\"level2\": \"二级分类\", \"level3\": \"三级分类\", \"name\": \"主题名称\", \"description\": \"简短描述\"}"
                    "如果不需要三级分类，level3 设为 null。"
                )
            },
            {
                "role": "user",
                "content": f"一级分类: {level1}\n文档标题: {title}\n内容: {text[:3000]}"
            },
        ]

        try:
            result = _call_api(messages, max_tokens=200)
            content = result.get("content", "")
            # 解析 JSON
            import re
            json_match = re.search(r'\{[^}]+\}', content, re.DOTALL)
            if json_match:
                data = json.loads(json_match.group())
                level2 = data.get("level2")
                level3 = data.get("level3")
                name = data.get("name", level3 or level2 or level1)
                description = data.get("description", "")
            else:
                # fallback
                level2 = level1
                level3 = None
                name = level1
                description = ""
        except Exception as e:
            logger.warning(f"  [动态分类] AI 创建主题失败: {e}，回退到一级分类")
            return None, None

        # 存储 embedding（离线模式可能为空）
        centroid_blob = None
        if embedding:
            dim = len(embedding)
            norm = math.sqrt(sum(x * x for x in embedding))
            if norm > 0:
                normalized = [x / norm for x in embedding]
            else:
                normalized = embedding[:]
            centroid_blob = struct.pack(f"{dim}f", *normalized)

        conn = sqlite3.connect(self.db_path)
        try:
            cursor = conn.execute(
                "INSERT OR IGNORE INTO topic_clusters "
                "(name, level1, level2, level3, description, centroid_embedding, doc_count) "
                "VALUES (?, ?, ?, ?, ?, ?, ?)",
                (name, level1, level2, level3, description, centroid_blob, 1)
            )
            topic_id = cursor.lastrowid
            # 如果没有插入（重复名称），获取已有 ID
            if topic_id == 0:
                row = conn.execute(
                    "SELECT id FROM topic_clusters WHERE name = ? AND level1 = ?",
                    (name, level1)
                ).fetchone()
                topic_id = row[0] if row else 0

            conn.execute(
                "INSERT OR IGNORE INTO topic_members (topic_id, doc_id, score) VALUES (?, ?, ?)",
                (topic_id, doc_id, 1.0)
            )
            conn.commit()
        finally:
            conn.close()

        return level2, level3

    def _ai_validate(self, text: str, title: str, topic_name: str,
                     topic_desc: str, score: float) -> bool:
        """AI 验证分类是否合理（用于 borderline 场景）。"""
        from scripts.ai_client import _call_api

        messages = [
            {
                "role": "system",
                "content": "你是文档分类审核专家。判断文档是否属于指定主题。只回答 yes 或 no。"
            },
            {
                "role": "user",
                "content": (
                    f"主题: {topic_name} ({topic_desc})\n"
                    f"文档标题: {title}\n内容: {text[:2000]}\n"
                    f"该文档是否属于此主题？回答 yes 或 no。"
                )
            },
        ]

        try:
            result = _call_api(messages, max_tokens=10)
            content = result.get("content", "").strip().lower()
            return "yes" in content
        except Exception:
            return True  # API 失败时默认通过


def _match_level1(text: str, title: str, keywords: dict) -> str:
    """一级分类：关键词匹配。"""
    combined = f"{title} {text[:500]}".lower()
    best_score = 0
    best_domain = "其他"

    for domain, domain_keywords in keywords.items():
        score = sum(1 for kw in domain_keywords if kw.lower() in combined)
        if score > best_score:
            best_score = score
            best_domain = domain

    return best_domain if best_score > 0 else "其他"


def _fallback_classify(text: str, title: str) -> tuple[str, list[str]]:
    """回退到静态分类器。"""
    try:
        from scripts.classifier import classify
        return classify(text, {"其他": []}, title)
    except Exception:
        return "其他", []


def _extract_doc_type_tags(text: str, title: str) -> list[str]:
    """提取文档类型标签（白皮书、教程、报告等）。"""
    try:
        from scripts.classifier import DOC_TYPE_KEYWORDS
        type_keywords = list(DOC_TYPE_KEYWORDS.keys())
        from scripts.classifier import _classify_doc_type
        return _classify_doc_type(text, title, type_keywords)
    except Exception:
        return []


def cosine_similarity(a: list[float], b: list[float]) -> float:
    """计算两个向量的余弦相似度。"""
    if not a or not b:
        return 0.0
    dot = sum(x * y for x, y in zip(a, b))
    norm_a = math.sqrt(sum(x * x for x in a))
    norm_b = math.sqrt(sum(x * x for x in b))
    if norm_a == 0 or norm_b == 0:
        return 0.0
    return dot / (norm_a * norm_b)
