"""
NoteMind 指标采集器 — 记录处理指标、健康检查、日志打点
用于大规模批处理时的监控和异常恢复
"""

import json
import os
import time
from datetime import datetime
from pathlib import Path


class MetricsCollector:
    """收集和处理指标。"""

    def __init__(self, log_dir: str = "logs"):
        self.log_dir = log_dir
        os.makedirs(log_dir, exist_ok=True)

        self.start_time = datetime.now()
        self.metrics = {
            "run_id": self.start_time.strftime("%Y%m%d_%H%M%S"),
            "start_time": self.start_time.isoformat(),
            "total_files": 0,
            "processed": 0,
            "succeeded": 0,
            "failed": 0,
            "skipped": 0,
            "errors": [],
            "file_details": [],
        }

        self._file_start = None
        self._file_path = None

    # --- Checkpoint 断点续传 ---

    def save_checkpoint(self, source: str, files: list[str], processed_files: set[str]):
        """保存检查点到文件（原子写入，防止中断导致损坏）。"""
        checkpoint = {
            "source": source,
            "files": files,
            "processed": list(processed_files),
            "metrics": self.metrics,
            "saved_at": datetime.now().isoformat(),
        }
        path = os.path.join(self.log_dir, "checkpoint.json")
        tmp_path = path + ".tmp"
        try:
            with open(tmp_path, "w", encoding="utf-8") as f:
                json.dump(checkpoint, f, ensure_ascii=False, indent=2)
                f.flush()
                os.fsync(f.fileno())
            os.replace(tmp_path, path)
        except Exception:
            if os.path.exists(tmp_path):
                os.remove(tmp_path)
            raise

    @classmethod
    def load_checkpoint(cls, log_dir: str = "logs", logger=None) -> dict | None:
        """加载检查点。返回 None 表示无检查点。"""
        path = os.path.join(log_dir, "checkpoint.json")
        if not os.path.exists(path):
            return None
        try:
            with open(path, "r", encoding="utf-8") as f:
                return json.load(f)
        except json.JSONDecodeError as e:
            if logger:
                logger.warning(f"检查点文件损坏，将重新开始: {e}")
            return None
        except (OSError, IOError) as e:
            if logger:
                logger.warning(f"无法读取检查点文件: {e}")
            return None

    @classmethod
    def clear_checkpoint(cls, log_dir: str = "logs"):
        """清除检查点。"""
        path = os.path.join(log_dir, "checkpoint.json")
        if os.path.exists(path):
            os.remove(path)

    def set_total(self, count: int):
        """设置总文件数。"""
        self.metrics["total_files"] = count

    def start_file(self, file_path: str):
        """开始处理一个文件。"""
        self._file_start = time.time()
        self._file_path = file_path

    def end_file(self, status: str, detail: str = ""):
        """结束一个文件的处理。"""
        elapsed = time.time() - self._file_start if self._file_start else 0
        self.metrics["processed"] += 1

        if status == "ok":
            self.metrics["succeeded"] += 1
        elif status == "fail":
            self.metrics["failed"] += 1
            self.metrics["errors"].append({
                "file": self._file_path,
                "error": detail,
                "elapsed": round(elapsed, 2),
            })
        elif status == "skip":
            self.metrics["skipped"] += 1

        self.metrics["file_details"].append({
            "file": self._file_path,
            "status": status,
            "elapsed": round(elapsed, 2),
            "detail": detail,
        })

    def get_progress(self) -> dict:
        """获取当前进度。"""
        m = self.metrics
        return {
            "total": m["total_files"],
            "processed": m["processed"],
            "succeeded": m["succeeded"],
            "failed": m["failed"],
            "skipped": m["skipped"],
            "elapsed": round(time.time() - self.start_time.timestamp(), 1),
        }

    def log_progress(self, logger, interval: int = 10):
        """每隔 N 个文件打印进度摘要。"""
        m = self.metrics
        if m["processed"] > 0 and m["processed"] % interval == 0:
            progress = self.get_progress()
            logger.info(
                f"[进度] {progress['processed']}/{progress['total']} | "
                f"成功: {progress['succeeded']} | 失败: {progress['failed']} | "
                f"跳过: {progress['skipped']} | 耗时: {progress['elapsed']}s"
            )

    def get_health(self) -> dict:
        """健康检查：判断当前处理状态是否健康。"""
        m = self.metrics
        if m["processed"] == 0:
            return {"healthy": True, "message": "未开始处理"}

        fail_rate = m["failed"] / m["processed"]
        if fail_rate > 0.5:
            return {
                "healthy": False,
                "message": f"失败率过高: {fail_rate:.0%} ({m['failed']}/{m['processed']})",
            }

        return {
            "healthy": True,
            "message": f"正常处理中: 成功率 {1 - fail_rate:.0%}",
        }

    def save_report(self) -> str:
        """保存处理报告到文件。"""
        m = self.metrics
        m["end_time"] = datetime.now().isoformat()
        m["total_elapsed"] = round(time.time() - self.start_time.timestamp(), 1)

        report_path = os.path.join(self.log_dir, f"report_{m['run_id']}.json")
        with open(report_path, "w", encoding="utf-8") as f:
            json.dump(m, f, ensure_ascii=False, indent=2)

        return report_path

    def print_summary(self, logger):
        """打印最终报告。"""
        m = self.metrics
        progress = self.get_progress()
        logger.info("")
        logger.info("=" * 50)
        logger.info("=== NoteMind 处理报告 ===")
        logger.info("=" * 50)
        logger.info(f"运行 ID: {m['run_id']}")
        logger.info(f"总计: {m['total_files']} 个文件")
        logger.info(f"成功: {m['succeeded']}")
        logger.info(f"失败: {m['failed']}")
        logger.info(f"跳过: {m['skipped']}")
        logger.info(f"总耗时: {progress['elapsed']}s")

        health = self.get_health()
        logger.info(f"健康状态: {'[正常]' if health['healthy'] else '[警告] ' + health['message']}")

        if m["errors"]:
            logger.info(f"\n失败文件列表 (前 10 个):")
            for err in m["errors"][:10]:
                logger.info(f"  - {err['file']}: {err['error']} ({err['elapsed']}s)")

        logger.info("=" * 50)
