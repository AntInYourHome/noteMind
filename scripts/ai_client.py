"""
NoteMind AI 客户端 — 多 Provider 轮询 + 并发调用
纯标准库实现，支持配置多个 API Key 提高吞吐量
"""

import base64
import json
import logging
import os
import random
import time
import urllib.request
import urllib.error
from concurrent.futures import ThreadPoolExecutor, as_completed
from threading import Lock

logger = logging.getLogger("notemind")


# --- Provider 池 ---

_DEFAULT_PROVIDER = {
    "api_key_env": "QWEN_API_KEY",
    "model": "qwen3.6-flash",
    "base_url": "https://dashscope.aliyuncs.com/compatible-mode/v1",
}


class ProviderHealthTracker:
    """追踪单个 provider 的健康状态。"""

    def __init__(self, provider: dict):
        self.provider = provider
        self.success_count = 0
        self.failure_count = 0
        self.rate_limit_count = 0
        self.last_error: str | None = None
        self.last_success_time: float | None = None
        self.last_error_time: float | None = None
        self.circuit_open_until: float = 0  # 熔断器冷却截止时间

    def record_success(self):
        self.success_count += 1
        self.last_success_time = time.time()
        # 成功后重置熔断
        self.circuit_open_until = 0

    def record_failure(self, error: str, is_rate_limit: bool = False):
        self.failure_count += 1
        self.last_error = error
        self.last_error_time = time.time()
        if is_rate_limit:
            self.rate_limit_count += 1
            # 429 限流：开启熔断 30 秒
            self.circuit_open_until = time.time() + 30

    def is_available(self) -> bool:
        """是否可用（未被熔断）。"""
        if time.time() < self.circuit_open_until:
            return False
        return True

    def health_score(self) -> float:
        """健康评分 0.0-1.0。"""
        total = self.success_count + self.failure_count
        if total == 0:
            return 1.0  # 初始状态视为可用
        success_rate = self.success_count / total
        # 限流频率惩罚
        rate_limit_penalty = min(0.5, self.rate_limit_count / max(1, total) * 2)
        return max(0.0, success_rate - rate_limit_penalty)

    def status_label(self) -> str:
        if not self.is_available():
            remaining = int(self.circuit_open_until - time.time())
            return f"限流冷却中 ({remaining}s)"
        score = self.health_score()
        total = self.success_count + self.failure_count
        if total == 0:
            return "可用 (未使用)"
        if score >= 0.9:
            return f"健康 ({self.success_count}/{total} 成功)"
        elif score >= 0.5:
            return f"降级 ({self.success_count}/{total} 成功, 限流{self.rate_limit_count}次)"
        else:
            return f"异常 ({self.success_count}/{total} 成功, 限流{self.rate_limit_count}次)"


class APIProviderPool:
    """管理多个 API provider，轮询分配请求。"""

    def __init__(self, providers: list[dict] = None, concurrency: int = 5):
        if providers:
            self.providers = providers
        else:
            key = os.environ.get("QWEN_API_KEY")
            if not key:
                raise ValueError("QWEN_API_KEY 环境变量未设置且未配置 providers")
            self.providers = [_DEFAULT_PROVIDER.copy()]
            self.providers[0]["api_key"] = key

        self.concurrency = max(1, concurrency)
        self._index = 0
        self._lock = Lock()
        # 健康追踪
        self._trackers: list[ProviderHealthTracker] = [
            ProviderHealthTracker(p) for p in self.providers
        ]

    def next_provider(self) -> tuple[dict, ProviderHealthTracker]:
        """轮询获取下一个可用的 provider 及其追踪器。

        优先跳过处于熔断冷却状态的 provider。
        如果所有 provider 都不可用，则强制使用下一个。
        """
        with self._lock:
            n = len(self.providers)
            # 第一轮：找可用的
            for _ in range(n):
                idx = self._index % n
                self._index += 1
                tracker = self._trackers[idx]
                if tracker.is_available():
                    return self.providers[idx].copy(), tracker
            # 全部熔断：强制返回下一个（带警告）
            idx = self._index % n
            self._index += 1
            logger.warning("所有 provider 均处于限流冷却中，强制调用")
            return self.providers[idx].copy(), self._trackers[idx]

    def call(self, messages: list, max_tokens: int = 500, retries: int = 3) -> str:
        """调用 API（使用下一个可用的 provider）。"""
        provider, tracker = self.next_provider()
        try:
            result = _call_with_provider(provider, messages, max_tokens, retries)
            tracker.record_success()
            return result
        except Exception as e:
            is_rate_limit = "429" in str(e)
            tracker.record_failure(str(e), is_rate_limit)
            raise

    def batch_call(self, tasks: list[dict]) -> list:
        """批量并发调用。

        Args:
            tasks: [{"messages": [...], "max_tokens": 500, "retries": 3}, ...]

        Returns:
            结果列表，与 tasks 顺序一致，失败项为 {"error": "..."}
        """
        results = [None] * len(tasks)

        def run(idx: int, task: dict):
            try:
                return idx, self.call(task["messages"], task.get("max_tokens", 500), task.get("retries", 3))
            except Exception as e:
                return idx, {"error": str(e)}

        with ThreadPoolExecutor(max_workers=self.concurrency) as pool:
            futures = [pool.submit(run, i, t) for i, t in enumerate(tasks)]
            for future in as_completed(futures):
                idx, result = future.result()
                results[idx] = result

        return results

    def get_provider_health(self) -> list[dict]:
        """获取所有 provider 的健康状态。

        Returns:
            [{"model": "...", "base_url": "...", "status": "...", "score": 0.95,
              "success": 10, "failure": 1, "rate_limits": 0}, ...]
        """
        health = []
        for tracker in self._trackers:
            p = tracker.provider
            health.append({
                "model": p.get("model", "unknown"),
                "base_url": p.get("base_url", ""),
                "status": tracker.status_label(),
                "score": tracker.health_score(),
                "success": tracker.success_count,
                "failure": tracker.failure_count,
                "rate_limits": tracker.rate_limit_count,
                "available": tracker.is_available(),
            })
        return health

    def print_health_report(self):
        """打印 provider 健康报告。"""
        health = self.get_provider_health()
        if not health:
            return
        logger.info("=" * 50)
        logger.info("NoteMind Provider 健康报告")
        logger.info("=" * 50)
        for h in health:
            icon = "✅" if h["available"] else "⛔"
            logger.info(
                f"  {icon} {h['model']} | 评分: {h['score']:.2f} | "
                f"成功: {h['success']} | 失败: {h['failure']} | "
                f"限流: {h['rate_limits']} | 状态: {h['status']}"
            )
        # 总结
        available = sum(1 for h in health if h["available"])
        total = len(health)
        total_success = sum(h["success"] for h in health)
        total_failure = sum(h["failure"] for h in health)
        total_rl = sum(h["rate_limits"] for h in health)
        logger.info("-" * 50)
        logger.info(
            f"  可用: {available}/{total} | "
            f"总成功: {total_success} | 总失败: {total_failure} | "
            f"总限流: {total_rl}"
        )
        logger.info("=" * 50)

    def reset_health_stats(self):
        """重置所有健康统计（用于新的批次开始）。"""
        for tracker in self._trackers:
            tracker.success_count = 0
            tracker.failure_count = 0
            tracker.rate_limit_count = 0
            tracker.last_error = None
            tracker.circuit_open_until = 0


# --- 全局单例（向后兼容） ---

_pool: APIProviderPool | None = None
_pool_lock = Lock()


def init_pool(providers: list[dict] = None, concurrency: int = 5):
    """初始化全局 provider 池。"""
    global _pool
    with _pool_lock:
        if _pool is None:
            _pool = APIProviderPool(providers, concurrency)


def get_pool() -> APIProviderPool:
    """获取全局 provider 池（懒加载）。"""
    global _pool
    with _pool_lock:
        if _pool is None:
            _pool = APIProviderPool()
        return _pool


# --- 底层调用 ---

_MAX_RETRIES = 3
_BASE_DELAY = 1.0


def _should_retry(status_code: int) -> bool:
    return status_code in (429, 500, 502, 503, 504)


def _call_with_provider(provider: dict, messages: list, max_tokens: int = 500, retries: int = None) -> str:
    api_key = provider.get("api_key", "")
    base_url = provider.get("base_url", _DEFAULT_PROVIDER["base_url"])
    model = provider.get("model", _DEFAULT_PROVIDER["model"])

    url = f"{base_url}/chat/completions"
    payload = json.dumps({
        "model": model,
        "messages": messages,
        "max_tokens": max_tokens,
    }).encode("utf-8")

    req = urllib.request.Request(
        url,
        data=payload,
        headers={
            "Content-Type": "application/json",
            "Authorization": f"Bearer {api_key}",
        },
        method="POST",
    )

    max_retries = retries if retries is not None else _MAX_RETRIES
    last_error = None

    for attempt in range(1, max_retries + 1):
        try:
            with urllib.request.urlopen(req, timeout=60) as resp:
                data = json.loads(resp.read().decode("utf-8"))
                return data["choices"][0]["message"]["content"].strip()
        except urllib.error.HTTPError as e:
            body = e.read().decode("utf-8", errors="replace")
            last_error = RuntimeError(f"AI API 错误 ({e.code}): {body}")
            if _should_retry(e.code) and attempt < max_retries:
                delay = _BASE_DELAY * (2 ** (attempt - 1)) + random.uniform(0, 1)
                logger.warning(f"API 调用失败 (第 {attempt}/{max_retries} 次, 状态码: {e.code}), {delay:.1f}s 后重试...")
                time.sleep(delay)
            else:
                raise last_error
        except urllib.error.URLError as e:
            last_error = RuntimeError(f"AI API 网络错误: {e.reason}")
            if attempt < max_retries:
                delay = _BASE_DELAY * (2 ** (attempt - 1)) + random.uniform(0, 1)
                logger.warning(f"API 网络异常 (第 {attempt}/{max_retries} 次), {delay:.1f}s 后重试...")
                time.sleep(delay)
            else:
                raise last_error
        except TimeoutError as e:
            last_error = RuntimeError(f"AI API 超时: {e}")
            if attempt < max_retries:
                delay = _BASE_DELAY * (2 ** (attempt - 1)) + random.uniform(0, 1)
                logger.warning(f"API 超时 (第 {attempt}/{max_retries} 次), {delay:.1f}s 后重试...")
                time.sleep(delay)
            else:
                raise last_error

    raise last_error or RuntimeError("API 调用失败，已达最大重试次数")


# --- 向后兼容的单调用接口 ---

def _call_api(messages: list, max_tokens: int = 500, retries: int = None) -> str:
    """向后兼容：使用全局 provider 池调用。"""
    return get_pool().call(messages, max_tokens, retries)


# --- 业务函数 ---

def analyze_image(image_path: str) -> str:
    """分析图片内容，返回概要。"""
    with open(image_path, "rb") as f:
        image_b64 = base64.b64encode(f.read()).decode("utf-8")

    ext = os.path.splitext(image_path)[1].lower()
    mime_map = {".jpg": "jpeg", ".jpeg": "jpeg", ".png": "png", ".gif": "gif", ".bmp": "bmp", ".webp": "webp"}
    mime = f"image/{mime_map.get(ext, 'jpeg')}"

    messages = [
        {
            "role": "user",
            "content": [
                {
                    "type": "text",
                    "text": (
                        "请用简洁的中文描述这张图片的内容，"
                        "包括图片类型、主要元素、可能的用途。"
                        "控制在 200 字以内。"
                    ),
                },
                {
                    "type": "image_url",
                    "image_url": {"url": f"data:{mime};base64,{image_b64}"},
                },
            ],
        }
    ]

    return _call_api(messages, max_tokens=500)


def generate_summary(text: str) -> str:
    """对长文本生成摘要。"""
    if len(text) < 200:
        return text.strip()

    messages = [
        {
            "role": "user",
            "content": (
                f"请用中文总结以下内容，提取核心要点（3-5 条），"
                f"控制在 300 字以内：\n\n{text[:5000]}"
            ),
        }
    ]

    return _call_api(messages, max_tokens=300)


def generate_tags(text: str) -> list[str]:
    """从文本中提取 3-8 个标签。"""
    if len(text) < 50:
        return []

    messages = [
        {
            "role": "user",
            "content": (
                f"请从以下内容中提取 3-8 个中文标签（关键词），"
                f"用逗号分隔，只返回标签：\n\n{text[:3000]}"
            ),
        }
    ]

    raw = _call_api(messages, max_tokens=100)
    tags = [t.strip() for t in raw.replace("，", ",").split(",") if t.strip()]
    return tags[:8]


# --- 日志分析 ---

def analyze_provider_from_logs(log_lines: list[str]) -> list[dict]:
    """从日志行中分析 provider 健康状态。

    解析日志中的错误模式，识别限流、超时、认证失败等问题。

    Args:
        log_lines: 日志行列表（如从 import.log 读取）

    Returns:
        分析结果列表，每项包含错误类型、频率、建议
    """
    import re

    patterns = {
        "rate_limit": re.compile(r"状态码: 429"),
        "server_error": re.compile(r"状态码: (500|502|503|504)"),
        "timeout": re.compile(r"API 超时"),
        "network_error": re.compile(r"API 网络错误"),
        "auth_error": re.compile(r"状态码: (401|403)"),
        "all_providers_rate_limited": re.compile(r"所有 provider 均处于限流冷却中"),
    }

    stats = {
        "rate_limit": 0,
        "server_error": 0,
        "timeout": 0,
        "network_error": 0,
        "auth_error": 0,
        "all_providers_rate_limited": 0,
    }

    for line in log_lines:
        for key, pattern in patterns.items():
            if pattern.search(line):
                stats[key] += 1

    total_errors = sum(stats.values())
    analysis = []

    if stats["auth_error"] > 0:
        analysis.append({
            "severity": "CRITICAL",
            "issue": "认证失败",
            "count": stats["auth_error"],
            "advice": "检查 API Key 是否有效，base_url 是否正确",
        })

    if stats["rate_limit"] > 0:
        severity = "HIGH" if stats["rate_limit"] > 10 else "MEDIUM"
        analysis.append({
            "severity": severity,
            "issue": "API 限流 (429)",
            "count": stats["rate_limit"],
            "advice": (
                "减少 ai.concurrency 配置值（当前并发数），"
                "或增加更多 API Key 分散请求负载"
            ),
        })

    if stats["all_providers_rate_limited"] > 0:
        analysis.append({
            "severity": "HIGH",
            "issue": "所有 Provider 同时被限流",
            "count": stats["all_providers_rate_limited"],
            "advice": "所有 Key 同时达到限流阈值，必须降低并发数或增加更多 Key",
        })

    if stats["timeout"] > 0:
        analysis.append({
            "severity": "MEDIUM",
            "issue": "请求超时",
            "count": stats["timeout"],
            "advice": "检查网络连接稳定性，或考虑降低 concurrency 减轻服务器压力",
        })

    if stats["server_error"] > 0:
        analysis.append({
            "severity": "MEDIUM",
            "issue": "服务器错误 (5xx)",
            "count": stats["server_error"],
            "advice": "API 服务端问题，稍后自动重试，如持续出现需联系服务商",
        })

    if total_errors == 0:
        analysis.append({
            "severity": "OK",
            "issue": "无异常",
            "count": 0,
            "advice": "所有 provider 运行正常",
        })

    return analysis


def print_log_analysis(log_path: str):
    """读取日志文件并打印 provider 健康分析报告。"""
    try:
        with open(log_path, "r", encoding="utf-8") as f:
            lines = f.readlines()
    except FileNotFoundError:
        logger.warning(f"日志文件不存在: {log_path}")
        return
    except Exception as e:
        logger.warning(f"读取日志失败: {e}")
        return

    analysis = analyze_provider_from_logs(lines)

    logger.info("=" * 50)
    logger.info("NoteMind Provider 日志分析报告")
    logger.info(f"日志文件: {log_path}")
    logger.info("=" * 50)
    for item in analysis:
        icon_map = {"CRITICAL": "🔴", "HIGH": "🟠", "MEDIUM": "🟡", "OK": "✅"}
        icon = icon_map.get(item["severity"], "⚪")
        logger.info(f"  {icon} [{item['severity']}] {item['issue']} × {item['count']}")
        logger.info(f"     建议: {item['advice']}")
    logger.info("=" * 50)
