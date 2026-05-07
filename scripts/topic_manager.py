"""
NoteMind 主题群管理器 — 主题群生命周期管理（合并/拆分/关键词）
"""

import json
import logging
import math
import sqlite3
import struct

logger = logging.getLogger("notemind")


class TopicClusterManager:
    """管理主题群的创建、合并、拆分和关键词提取。"""

    def __init__(self, db_path: str):
        self.db_path = db_path

    def get_all_topics(self, level1: str = None) -> list[dict]:
        """获取所有活跃主题群。"""
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        if level1:
            rows = conn.execute(
                "SELECT * FROM topic_clusters WHERE level1 = ? AND status = 'active' "
                "ORDER BY doc_count DESC", (level1,)
            ).fetchall()
        else:
            rows = conn.execute(
                "SELECT * FROM topic_clusters WHERE status = 'active' "
                "ORDER BY level1, doc_count DESC"
            ).fetchall()
        conn.close()

        result = []
        for row in rows:
            item = dict(row)
            if item["centroid_embedding"]:
                item.pop("centroid_embedding")  # 移除二进制数据
            result.append(item)
        return result

    def get_topic_keywords(self, topic_id: int) -> list[tuple[str, float]]:
        """获取主题群的关键词。"""
        conn = sqlite3.connect(self.db_path)
        rows = conn.execute(
            "SELECT keyword, weight FROM topic_keywords WHERE topic_id = ? ORDER BY weight DESC",
            (topic_id,)
        ).fetchall()
        conn.close()
        return [(r[0], r[1]) for r in rows]

    def add_keyword(self, topic_id: int, keyword: str, weight: float = 1.0):
        """添加或更新主题关键词。"""
        conn = sqlite3.connect(self.db_path)
        conn.execute(
            "INSERT INTO topic_keywords (topic_id, keyword, weight) "
            "VALUES (?, ?, ?) ON CONFLICT(topic_id, keyword) DO UPDATE SET weight = ?",
            (topic_id, keyword, weight, weight)
        )
        conn.commit()
        conn.close()

    def check_merge(self, level1: str = None, threshold: float = 0.85) -> list[tuple[int, int]]:
        """检查并合并相似度高于阈值的主题群。

        Args:
            level1: 限定一级分类（None 表示检查所有）
            threshold: 余弦相似度阈值

        Returns:
            已合并的 (topic_a_id, topic_b_id) 列表
        """
        conn = sqlite3.connect(self.db_path)
        if level1:
            rows = conn.execute(
                "SELECT id, centroid_embedding FROM topic_clusters "
                "WHERE level1 = ? AND status = 'active' AND centroid_embedding IS NOT NULL",
                (level1,)
            ).fetchall()
        else:
            rows = conn.execute(
                "SELECT id, centroid_embedding FROM topic_clusters "
                "WHERE status = 'active' AND centroid_embedding IS NOT NULL"
            ).fetchall()
        conn.close()

        if len(rows) < 2:
            return []

        dim = len(struct.unpack(f"{len(rows[0][1]) // 4}f", rows[0][1]))
        vectors = {}
        for row in rows:
            vectors[row[0]] = list(struct.unpack(f"{dim}f", row[1]))

        # 检查所有配对
        topic_ids = list(vectors.keys())
        merge_pairs = []
        for i in range(len(topic_ids)):
            for j in range(i + 1, len(topic_ids)):
                a_id, b_id = topic_ids[i], topic_ids[j]
                sim = cosine_similarity(vectors[a_id], vectors[b_id])
                if sim >= threshold:
                    merge_pairs.append((a_id, b_id))

        # 执行合并
        merged = []
        for a_id, b_id in merge_pairs:
            self._merge_topics(a_id, b_id)
            merged.append((a_id, b_id))

        if merged:
            logger.info(f"  [主题管理] 合并了 {len(merged)} 对主题群")
        return merged

    def _merge_topics(self, survivor_id: int, merged_id: int):
        """将 merged_id 合并到 survivor_id。"""
        conn = sqlite3.connect(self.db_path)

        # 转移成员
        conn.execute(
            "INSERT OR IGNORE INTO topic_members (topic_id, doc_id, score) "
            "SELECT ?, doc_id, score FROM topic_members WHERE topic_id = ?",
            (survivor_id, merged_id)
        )
        # 删除旧成员
        conn.execute("DELETE FROM topic_members WHERE topic_id = ?", (merged_id,))

        # 合并关键词
        conn.execute(
            "INSERT INTO topic_keywords (topic_id, keyword, weight) "
            "SELECT ?, keyword, weight FROM topic_keywords WHERE topic_id = ? "
            "ON CONFLICT(topic_id, keyword) DO UPDATE SET weight = MAX(topic_keywords.weight, excluded.weight)",
            (survivor_id, merged_id)
        )

        # 更新文档计数
        conn.execute(
            "UPDATE topic_clusters SET doc_count = doc_count + "
            "(SELECT doc_count FROM topic_clusters WHERE id = ?) WHERE id = ?",
            (merged_id, survivor_id)
        )

        # 标记被合并的主题
        conn.execute(
            "UPDATE topic_clusters SET status = 'merged', merged_from = ? WHERE id = ?",
            (survivor_id, merged_id)
        )

        conn.commit()
        conn.close()

    def check_split(self, threshold: int = 50) -> list[tuple[int, int, int]]:
        """检查文档数超过阈值的主题群，尝试拆分。

        Returns:
            (original_id, new_id_1, new_id_2) 列表
        """
        conn = sqlite3.connect(self.db_path)
        rows = conn.execute(
            "SELECT id, level1, level2, level3, name FROM topic_clusters "
            "WHERE status = 'active' AND doc_count >= ?",
            (threshold,)
        ).fetchall()
        conn.close()

        splits = []
        for row in rows:
            topic_id, level1, level2, level3, name = row
            result = self._split_topic(topic_id)
            if result:
                splits.append((topic_id, result[0], result[1]))

        if splits:
            logger.info(f"  [主题管理] 拆分了 {len(splits)} 个主题群")
        return splits

    def _split_topic(self, topic_id: int) -> tuple[int, int] | None:
        """拆分主题群。简单策略：按关键词分成两组。"""
        # 简化实现：不自动拆分，仅记录日志
        # 完整拆分需要 k-means + AI 命名，复杂度较高
        logger.debug(f"  [主题管理] 主题 {topic_id} 文档数较多，但未自动拆分")
        return None

    def run_maintenance(self, level1: str = None) -> dict:
        """定期维护：合并 + 拆分。"""
        merged = self.check_merge(level1)
        splits = self.check_split()
        return {"merged": len(merged), "splits": len(splits)}


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
