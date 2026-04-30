"""
NoteMind Agent 调度器 — 按任务优先级并发调度 AI 调用
"""

import logging
import threading
from concurrent.futures import ThreadPoolExecutor, as_completed
from queue import PriorityQueue

logger = logging.getLogger("notemind")

# 任务优先级（数字越小优先级越高）
PRIORITY_MAP = {
    "image_analysis": 1,
    "summary": 2,
    "classify": 3,
    "tags": 4,
}

DEFAULT_TIMEOUTS = {
    "image_analysis": 60,
    "summary": 60,
    "classify": 30,
    "tags": 30,
}


class AgentScheduler:
    """按优先级和并发度调度 AI 任务。"""

    def __init__(self, pool, max_workers: int = 5):
        """
        Args:
            pool: APIProviderPool 实例
            max_workers: 最大并发工作线程
        """
        self.pool = pool
        self.max_workers = max_workers
        self._task_counter = 0
        self._lock = threading.Lock()

    def run_tasks(self, tasks: list[dict]) -> list:
        """提交并执行一组任务。

        Args:
            tasks: [{"type": "summary", "fn": callable, "args": (...), "retries": 3}, ...]
                  fn 是实际调用的函数（如 generate_summary），args 是参数

        Returns:
            结果列表，与输入顺序一致，失败项为 {"error": "..."}
        """
        if not tasks:
            return []

        results = [None] * len(tasks)

        def run(idx: int, task: dict):
            fn = task["fn"]
            args = task.get("args", ())
            retries = task.get("retries", 3)
            try:
                return idx, fn(*args)
            except Exception as e:
                logger.warning(f"任务失败 (type={task.get('type', '?')}): {e}")
                return idx, {"error": str(e)}

        # 按优先级排序（高优先级先调度，但不阻塞低优先级并发）
        sorted_tasks = sorted(
            enumerate(tasks),
            key=lambda x: PRIORITY_MAP.get(x[1].get("type", "tags"), 99)
        )

        with ThreadPoolExecutor(max_workers=self.max_workers) as executor:
            futures = {}
            for orig_idx, task in sorted_tasks:
                future = executor.submit(run, orig_idx, task)
                futures[future] = orig_idx

            for future in as_completed(futures):
                idx, result = future.result()
                results[idx] = result

        return results

    def analyze_batch(self, texts: list[str], images: list[str] = None) -> dict:
        """批量分析一组文本和图片。

        Args:
            texts: 需要摘要和标签的文本列表
            images: 需要识别的图片路径列表

        Returns:
            {"summaries": [...], "tags": [...], "image_descs": [...]}
        """
        tasks = []
        task_types = []

        # 文本摘要任务
        for text in texts:
            if len(text) < 200:
                tasks.append({"type": "summary", "result": text.strip(), "is_literal": True})
                task_types.append("summary")
            else:
                from scripts.ai_client import generate_summary
                tasks.append({"type": "summary", "fn": generate_summary, "args": (text,)})
                task_types.append("summary")

        # 标签提取任务
        for text in texts:
            if len(text) < 50:
                tasks.append({"type": "tags", "result": [], "is_literal": True})
                task_types.append("tags")
            else:
                from scripts.ai_client import generate_tags
                tasks.append({"type": "tags", "fn": generate_tags, "args": (text,)})
                task_types.append("tags")

        # 图片识别任务
        image_descs = []
        if images:
            from scripts.ai_client import analyze_image
            for img_path in images:
                tasks.append({"type": "image_analysis", "fn": analyze_image, "args": (img_path,)})
                task_types.append("image_analysis")

        # 执行所有任务
        raw_results = self.run_tasks(tasks)

        # 解析结果
        n_texts = len(texts)
        summaries = []
        tags_list = []

        for i in range(n_texts):
            r = raw_results[i]
            if isinstance(r, dict) and r.get("is_literal"):
                summaries.append(r["result"])
            elif isinstance(r, dict) and "error" in r:
                summaries.append(f"（摘要生成失败: {r['error']}）")
            else:
                summaries.append(r if r else "")

        for i in range(n_texts):
            r = raw_results[n_texts + i]
            if isinstance(r, dict) and r.get("is_literal"):
                tags_list.append(r["result"])
            elif isinstance(r, dict) and "error" in r:
                tags_list.append([])
            elif isinstance(r, list):
                tags_list.append(r)
            else:
                # 解析标签字符串
                if isinstance(r, str):
                    tags_list.append([t.strip() for t in r.replace("，", ",").split(",") if t.strip()][:8])
                else:
                    tags_list.append([])

        # 图片描述
        img_offset = n_texts * 2
        for i in range(img_offset, len(raw_results)):
            r = raw_results[i]
            if isinstance(r, dict) and "error" in r:
                image_descs.append(f"（图片识别失败: {r['error']}）")
            else:
                image_descs.append(r if r else "")

        return {
            "summaries": summaries,
            "tags": tags_list,
            "image_descs": image_descs,
        }
