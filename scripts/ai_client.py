"""
NoteMind AI 客户端 — 多 Provider 轮询 + 自动降级
业务优先：遇到 429 时自动降级，确保任务完成

降级链路：
  1. 换 provider（轮询到其他 Key）
  2. 降级并发度（concurrency 减半）
  3. 跳过非关键任务（图片分析 → 纯文本摘要）
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

# --- 测试模式：模拟 10% 随机 API 错误 ---
# 设置环境变量 NOTEMIND_TEST_CHAOS=1 启用
_TEST_CHAOS = os.environ.get("NOTEMIND_TEST_CHAOS", "0") == "1"
_CHAOS_ERROR_TYPES = [
    RuntimeError("AI API 错误 (429): {\"error\":{\"message\":\"Rate limit exceeded\"}}"),
    RuntimeError("AI API 错误 (500): {\"error\":{\"message\":\"Internal server error\"}}"),
    RuntimeError("AI API 错误 (503): {\"error\":{\"message\":\"Service temporarily unavailable\"}}"),
    RuntimeError("AI API 错误 (502): {\"error\":{\"message\":\"Bad gateway\"}}"),
]

logger = logging.getLogger("notemind")


# --- Provider 池 ---

_DEFAULT_PROVIDER = {
    "api_key_env": "QWEN_API_KEY",
    "model": "qwen3.6-flash",
    "base_url": "https://dashscope.aliyuncs.com/compatible-mode/v1",
    "multimodal": False,
}

# Level 3: 模型路由 — 标签提取使用更便宜模型（可选）
_tags_model: dict | None = None


def set_tags_model(model_config: dict | None):
    """设置标签提取专用的模型（通常为更便宜的模型）。

    Args:
        model_config: {"model": "qwen-turbo", "base_url": "...", "api_key": "..."}
    """
    global _tags_model
    _tags_model = model_config


def _get_tags_model() -> dict | None:
    """获取标签提取模型配置。"""
    return _tags_model


def _call_with_model(model_config: dict, messages: list, max_tokens: int = 500, retries: int = 3) -> dict:
    """使用指定的模型配置调用 API（不经过 provider 池）。"""
    import urllib.request
    import urllib.error
    import json
    import random

    url = f"{model_config['base_url']}/chat/completions"
    payload = json.dumps({
        "model": model_config["model"],
        "messages": messages,
        "max_tokens": max_tokens,
    }).encode("utf-8")

    req = urllib.request.Request(
        url, data=payload,
        headers={
            "Content-Type": "application/json",
            "Authorization": f"Bearer {model_config.get('api_key', '')}",
        },
        method="POST",
    )

    for attempt in range(1, retries + 1):
        try:
            start = time.time()
            with urllib.request.urlopen(req, timeout=60) as resp:
                latency = time.time() - start
                data = json.loads(resp.read().decode("utf-8"))
                usage = data.get("usage", {})
                choices = data.get("choices")
                if not choices:
                    raise RuntimeError(f"API 返回空 choices: {data}")
                message = choices[0].get("message")
                if not message:
                    raise RuntimeError(f"API 返回空 message: {data}")
                content = message.get("content", "")
                return {
                    "content": content.strip() if content else "[空响应]",
                    "input_tokens": usage.get("prompt_tokens", 0),
                    "output_tokens": usage.get("completion_tokens", 0),
                    "latency": latency,
                }
        except Exception as e:
            if attempt < retries:
                delay = 1 * (2 ** (attempt - 1)) + random.uniform(0, 1)
                time.sleep(delay)
            else:
                raise


class ProviderHealthTracker:
    """追踪单个 provider 的健康状态。"""

    # 连续 429 次数达到此阈值时，进入长冷却（5 分钟）
    DEGRADATION_THRESHOLD = 3

    def __init__(self, provider: dict):
        self.provider = provider
        self.success_count = 0
        self.failure_count = 0
        self.rate_limit_count = 0
        self.consecutive_429 = 0  # 连续 429 次数
        self.consecutive_5xx = 0  # 连续 5xx 次数
        self.last_error: str | None = None
        self.last_success_time: float | None = None
        self.last_error_time: float | None = None
        self.circuit_open_until: float = 0  # 冷却截止时间

    def record_success(self):
        self.success_count += 1
        self.last_success_time = time.time()
        self.consecutive_429 = 0  # 成功后重置连续计数
        self.consecutive_5xx = 0
        self.circuit_open_until = 0  # 重置冷却

    def record_failure(self, error: str, is_rate_limit: bool = False,
                       is_server_error: bool = False):
        self.failure_count += 1
        self.last_error = error
        self.last_error_time = time.time()

        if is_rate_limit:
            self.rate_limit_count += 1
            self.consecutive_429 += 1
            # 连续 429 达到阈值：5 分钟长冷却
            if self.consecutive_429 >= self.DEGRADATION_THRESHOLD:
                cool = 300  # 5 分钟
                model = self.provider.get('model', '?')
                logger.warning(
                    f"[降级] Provider {model} 连续 429 {self.consecutive_429} 次，"
                    f"进入长冷却 {cool}s"
                )
            else:
                cool = 30  # 普通 30 秒冷却
            self.circuit_open_until = time.time() + cool

        elif is_server_error:
            self.consecutive_5xx += 1
            # 连续 5xx 达到阈值：2 分钟中冷却
            if self.consecutive_5xx >= self.DEGRADATION_THRESHOLD:
                cool = 120  # 2 分钟
                model = self.provider.get('model', '?')
                logger.warning(
                    f"[降级] Provider {model} 连续 5xx {self.consecutive_5xx} 次，"
                    f"进入中冷却 {cool}s"
                )
            else:
                cool = 15  # 普通 15 秒冷却
            self.circuit_open_until = time.time() + cool

        else:
            # 其他错误：不触发冷却，仅记录
            pass

    def is_available(self) -> bool:
        """是否可用（未处于冷却中）。"""
        return time.time() >= self.circuit_open_until

    def health_score(self) -> float:
        """健康评分 0.0-1.0。"""
        total = self.success_count + self.failure_count
        if total == 0:
            return 1.0
        success_rate = self.success_count / total
        rate_limit_penalty = min(0.5, self.rate_limit_count / max(1, total) * 2)
        return max(0.0, success_rate - rate_limit_penalty)

    def status_label(self) -> str:
        if not self.is_available():
            remaining = int(self.circuit_open_until - time.time())
            if remaining > 60:
                return f"长冷却 ({remaining // 60}m{remaining % 60}s)"
            return f"冷却中 ({remaining}s)"
        score = self.health_score()
        total = self.success_count + self.failure_count
        if total == 0:
            return "可用 (未使用)"
        if score >= 0.9:
            return f"健康 ({self.success_count}/{total})"
        elif score >= 0.5:
            return f"限流 ({self.success_count}/{total}, 429×{self.rate_limit_count})"
        else:
            return f"异常 ({self.success_count}/{total}, 429×{self.rate_limit_count})"


class APIProviderPool:
    """管理多个 API provider，自动降级 + 轮询分配。"""

    def __init__(self, providers: list[dict] = None, concurrency: int = 5):
        if providers:
            self.providers = providers
        else:
            key = os.environ.get("QWEN_API_KEY")
            if not key:
                raise ValueError("QWEN_API_KEY 环境变量未设置且未配置 providers")
            self.providers = [_DEFAULT_PROVIDER.copy()]
            self.providers[0]["api_key"] = key

        self._original_concurrency = max(1, concurrency)
        self.concurrency = self._original_concurrency
        self._index = 0
        self._lock = Lock()
        self._trackers: list[ProviderHealthTracker] = [
            ProviderHealthTracker(p) for p in self.providers
        ]
        # 降级状态
        self._degraded_mode = False  # 是否进入降级模式（降低并发）
        self._total_429_count = 0  # 全局 429 计数

    def next_provider(self, multimodal: bool = False) -> tuple[dict, ProviderHealthTracker]:
        """轮询获取下一个可用的 provider。

        降级策略：
        - 跳过降级/冷却中的 provider
        - multimodal=True 时仅选择支持多模态的 provider
        - 全部不可用时强制返回
        """
        with self._lock:
            n = len(self.providers)
            for _ in range(n):
                idx = self._index % n
                self._index += 1
                tracker = self._trackers[idx]
                if tracker.is_available():
                    if multimodal and not self.providers[idx].get("multimodal", False):
                        continue
                    return self.providers[idx].copy(), tracker
            # 全部不可用
            idx = self._index % n
            self._index += 1
            return self.providers[idx].copy(), self._trackers[idx]

    def _on_error(self, tracker: ProviderHealthTracker, error_str: str, error_type: str):
        """处理 429 限流或 5xx 服务器错误，触发降级链路。

        Args:
            tracker: 该 provider 的健康追踪器
            error_str: 错误信息字符串
            error_type: '429' 或 '5xx'
        """
        with self._lock:
            self._total_429_count += 1

        is_rate_limit = (error_type == "429")
        tracker.record_failure(error_str, is_rate_limit=is_rate_limit,
                               is_server_error=not is_rate_limit)

        # 检查是否所有 provider 都不可用
        available_count = sum(1 for t in self._trackers if t.is_available())
        total = len(self._trackers)

        if available_count == 0:
            logger.warning(
                f"[降级] 所有 provider 均不可用（{error_type}），"
                f"触发全局降级模式（错误×{self._total_429_count}）"
            )
            self._enter_degraded_mode()
        elif available_count < total:
            logger.info(
                f"[降级] {total - available_count}/{total} 个 provider 不可用，"
                f"剩余 {available_count} 个可用"
            )

    def _enter_degraded_mode(self):
        """进入降级模式：并发度减半，最小为 1。"""
        with self._lock:
            if self._degraded_mode:
                return  # 已经进入过
            new_concurrency = max(1, self.concurrency // 2)
            if new_concurrency < self.concurrency:
                self.concurrency = new_concurrency
                self._degraded_mode = True
                logger.warning(
                    f"[降级] 并发度已从 {self._original_concurrency} → {new_concurrency}"
                )

    def call(self, messages: list, max_tokens: int = 500, retries: int = 3,
             multimodal: bool = False) -> dict:
        """调用 API，自动选择可用的 provider。

        Returns:
            {"content": str, "input_tokens": int, "output_tokens": int, "latency": float}
        """
        provider, tracker = self.next_provider(multimodal=multimodal)
        try:
            result = _call_with_provider(provider, messages, max_tokens, retries)
            tracker.record_success()
            # 向后兼容：如果 _call_with_provider 返回 dict，则返回完整结果
            if isinstance(result, dict):
                return result
            return {"content": result, "input_tokens": 0, "output_tokens": 0, "latency": 0}
        except Exception as e:
            error_str = str(e)
            if "429" in error_str:
                self._on_error(tracker, error_str, error_type="429")
            elif any(code in error_str for code in ("500", "502", "503", "504")):
                self._on_error(tracker, error_str, error_type="5xx")
            else:
                tracker.record_failure(error_str, is_rate_limit=False)
            raise

    def call_text(self, messages: list, max_tokens: int = 500, retries: int = 3,
                  multimodal: bool = False) -> str:
        """向后兼容：只返回文本内容。"""
        result = self.call(messages, max_tokens, retries, multimodal)
        return result.get("content", "") if isinstance(result, dict) else result

    def batch_call(self, tasks: list[dict]) -> list:
        """批量并发调用，自动根据降级状态调整并发度。"""
        results = [None] * len(tasks)

        def run(idx: int, task: dict):
            try:
                return idx, self.call(
                    task["messages"],
                    task.get("max_tokens", 500),
                    task.get("retries", 3)
                )
            except Exception as e:
                return idx, {"error": str(e)}

        # 使用当前降级后的并发度
        workers = min(self.concurrency, len(tasks))
        with ThreadPoolExecutor(max_workers=workers) as pool:
            futures = [pool.submit(run, i, t) for i, t in enumerate(tasks)]
            for future in as_completed(futures):
                idx, result = future.result()
                results[idx] = result

        return results

    def has_multimodal_provider(self) -> bool:
        """是否有支持多模态的 provider 可用。"""
        for i, p in enumerate(self.providers):
            if p.get("multimodal", False) and self._trackers[i].is_available():
                return True
        return False

    def is_degraded(self) -> bool:
        """是否处于降级模式。"""
        return self._degraded_mode

    def get_provider_health(self) -> list[dict]:
        """获取所有 provider 的健康状态。"""
        health = []
        for tracker in self._trackers:
            p = tracker.provider
            health.append({
                "model": p.get("model", "unknown"),
                "base_url": p.get("base_url", ""),
                "multimodal": p.get("multimodal", False),
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
        cooling_count = sum(1 for h in health if not h["available"])
        mm_count = sum(1 for h in health if h["multimodal"])
        mm_available = sum(1 for h in health if h["multimodal"] and h["available"])
        logger.info("=" * 60)
        logger.info("NoteMind Provider 健康报告")
        logger.info("=" * 60)
        logger.info(
            f"  总数: {len(health)} | 多模态可用: {mm_available}/{mm_count} | "
            f"冷却中: {cooling_count} | 当前并发: {self.concurrency}"
        )
        logger.info("-" * 60)
        for h in health:
            if h["available"]:
                icon = "✅"
            else:
                icon = "⏳"
            mm_tag = " [多模态]" if h["multimodal"] else ""
            logger.info(
                f"  {icon} {h['model']}{mm_tag} | 评分: {h['score']:.2f} | "
                f"成功: {h['success']} | 失败: {h['failure']} | "
                f"限流: {h['rate_limits']} | 状态: {h['status']}"
            )
        available = sum(1 for h in health if h["available"])
        total = len(health)
        logger.info("-" * 60)
        logger.info(
            f"  可用: {available}/{total} | "
            f"并发: {self.concurrency}/{self._original_concurrency} | "
            f"全局429: {self._total_429_count}"
        )
        logger.info("=" * 60)

    def reset_health_stats(self):
        """重置所有健康统计。"""
        for tracker in self._trackers:
            tracker.success_count = 0
            tracker.failure_count = 0
            tracker.rate_limit_count = 0
            tracker.consecutive_429 = 0
            tracker.consecutive_5xx = 0
            tracker.last_error = None
            tracker.circuit_open_until = 0
        self._degraded_mode = False
        self.concurrency = self._original_concurrency
        self._total_429_count = 0


# --- 全局单例 ---

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


def _call_with_provider(provider: dict, messages: list, max_tokens: int = 500, retries: int = None) -> dict:
    # --- 测试模式：10% 随机注入错误 ---
    if _TEST_CHAOS and random.random() < 0.1:
        err = random.choice(_CHAOS_ERROR_TYPES)
        logger.warning(f"[混沌测试] 模拟 API 错误: {type(err).__name__}")
        raise err

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
            start = time.time()
            with urllib.request.urlopen(req, timeout=60) as resp:
                latency = time.time() - start
                data = json.loads(resp.read().decode("utf-8"))
                usage = data.get("usage", {})
                choices = data.get("choices")
                if not choices:
                    raise RuntimeError(f"API 返回空 choices: {data}")
                message = choices[0].get("message")
                if not message:
                    raise RuntimeError(f"API 返回空 message: {data}")
                content = message.get("content", "")
                content = content.strip() if content else "[空响应]"
                return {
                    "content": content,
                    "input_tokens": usage.get("prompt_tokens", 0),
                    "output_tokens": usage.get("completion_tokens", 0),
                    "latency": latency,
                }
        except urllib.error.HTTPError as e:
            body = e.read().decode("utf-8", errors="replace")

            # 307 临时重定向：立即跟随，不计入重试次数
            if e.code == 307:
                redirect_url = e.headers.get("Location")
                if redirect_url:
                    # 重新构建 Request 对象指向新 URL
                    req = urllib.request.Request(
                        redirect_url,
                        data=req.data,
                        headers=dict(req.headers),
                        method="POST",
                    )
                    delay = _BASE_DELAY + random.uniform(0, 0.5)
                    logger.warning(f"API 307 重定向到: {redirect_url}, {delay:.1f}s 后重试...")
                    time.sleep(delay)
                    continue
                last_error = RuntimeError(f"AI API 307 重定向但无 Location 头")
            else:
                last_error = RuntimeError(f"AI API 错误 ({e.code}): {body}")

            if attempt < max_retries:
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

def _call_api(messages: list, max_tokens: int = 500, retries: int = None,
              multimodal: bool = False) -> dict:
    """向后兼容：使用全局 provider 池调用。

    Returns:
        {"content": str, "input_tokens": int, "output_tokens": int, "latency": float}
    """
    return get_pool().call(messages, max_tokens, retries, multimodal=multimodal)


# --- 业务函数 ---

def test_api_availability(pool: "APIProviderPool") -> dict:
    """测试所有 provider 的 API 可用性。

    Returns:
        {"total": n, "available": n, "unavailable": n, "details": [...]}
    """
    results = {"total": 0, "available": 0, "unavailable": 0, "details": []}

    for i, provider in enumerate(pool.providers):
        tracker = pool._trackers[i]
        model = provider.get("model", "unknown")
        base_url = provider.get("base_url", "")
        results["total"] += 1

        try:
            result = pool.call(
                [{"role": "user", "content": "回复OK"}],
                max_tokens=10,
                retries=1,
            )
            content = result.get("content", "") if isinstance(result, dict) else ""
            if content:
                results["available"] += 1
                results["details"].append({
                    "model": model,
                    "status": "可用",
                    "latency": result.get("latency", 0),
                })
                tracker.record_success()
            else:
                raise RuntimeError("空响应")
        except Exception as e:
            results["unavailable"] += 1
            results["details"].append({
                "model": model,
                "status": f"不可用: {e}",
            })

    return results


def print_api_test_report(results: dict):
    """打印 API 可用性测试报告。"""
    logger.info("=" * 50)
    logger.info("API 可用性测试")
    logger.info("=" * 50)
    for d in results["details"]:
        icon = "✅" if "可用" in d["status"] and d["status"] == "可用" else "❌"
        if d["status"] == "可用":
            logger.info(f"  {icon} {d['model']} | 延迟: {d.get('latency', 0):.2f}s | 状态: 可用")
        else:
            logger.info(f"  {icon} {d['model']} | 状态: {d['status']}")
    logger.info("-" * 50)
    logger.info(
        f"  总计: {results['total']} | 可用: {results['available']} | "
        f"不可用: {results['unavailable']}"
    )
    logger.info("=" * 50)


def analyze_image(image_path: str) -> str:
    """分析图片内容，返回概要。使用本地 MiniMind-V 模型。

    如果本地 VLM 不可用，抛出 ValueError 让调用方使用 OCR 降级。
    """
    if not _use_local_vlm():
        raise ValueError("本地 VLM 不可用（未启用或模型文件缺失），跳过图片分析")

    try:
        from scripts.vlm_local import describe_image
        desc = describe_image(image_path)
        if desc and desc.strip():
            return desc.strip()
    except Exception as e:
        raise ValueError(f"本地 VLM 推理失败: {e}")


# --- 本地 VLM 开关 ---

def _use_local_vlm() -> bool:
    """检查是否启用本地 VLM 推理。"""
    env_val = os.environ.get("NOTEMIND_LOCAL_VLM", "auto")
    if env_val == "0" or env_val.lower() == "false":
        return False
    if env_val == "1" or env_val.lower() == "true":
        return True
    # auto: 检查文件是否存在
    try:
        from scripts.vlm_local import is_available
        return is_available()
    except ImportError:
        return False


# --- 性能统计全局计数器 ---

_perf_stats = {
    "api_calls": 0,
    "input_tokens": 0,
    "output_tokens": 0,
    "total_latency": 0.0,
    "errors": 0,
}

def get_perf_stats() -> dict:
    """获取当前会话的性能统计。"""
    return _perf_stats.copy()

def reset_perf_stats():
    """重置性能统计。"""
    _perf_stats.update({
        "api_calls": 0,
        "input_tokens": 0,
        "output_tokens": 0,
        "total_latency": 0.0,
        "errors": 0,
    })


# --- Prompt 模板（Level 2: 精简 + system message 缓存） ---

_SUMMARY_SYSTEM = "你是文档摘要专家。用中文提取核心要点，控制在 300 字以内。"
_TAGS_SYSTEM = "你是关键词提取专家。从内容中提取 3-8 个中文标签，用逗号分隔。"
_OUTLINE_SYSTEM = "你是文档结构分析专家。根据各章节摘要，提取文档的一级/二级章节标题列表，每行一个，使用 '- ' 开头。不要包含页码、重复项或太细的子章节。只输出标题列表。"


def generate_summary(text: str) -> str:
    """对长文本生成摘要。

    使用 system message 分离模式：固定模板放 system（DashScope 缓存），
    只发送文本到 user，减少每次请求的 input tokens。
    """
    if len(text) < 200:
        return text.strip()

    messages = [
        {"role": "system", "content": _SUMMARY_SYSTEM},
        {"role": "user", "content": text[:5000]},
    ]

    try:
        result = _call_api(messages, max_tokens=300)
        _perf_stats["api_calls"] += 1
        _perf_stats["input_tokens"] += result.get("input_tokens", 0)
        _perf_stats["output_tokens"] += result.get("output_tokens", 0)
        _perf_stats["total_latency"] += result.get("latency", 0)
        return result.get("content", "")
    except Exception:
        _perf_stats["errors"] += 1
        raise


def generate_tags(text: str) -> list[str]:
    """从文本中提取 3-8 个标签。

    Level 3: 模型路由 — 如果配置了 tags_model，用更便宜的模型做标签提取。
    Level 2: system message 分离 + 更短的文本截取（1500 字符）。
    """
    if len(text) < 50:
        return []

    messages = [
        {"role": "system", "content": _TAGS_SYSTEM},
        {"role": "user", "content": text[:1500]},
    ]

    # Level 3: 如果有 tags_model 配置，使用更便宜的模型
    model_override = _get_tags_model()

    try:
        if model_override:
            result = _call_with_model(model_override, messages, max_tokens=100)
        else:
            result = _call_api(messages, max_tokens=100)
        _perf_stats["api_calls"] += 1
        _perf_stats["input_tokens"] += result.get("input_tokens", 0)
        _perf_stats["output_tokens"] += result.get("output_tokens", 0)
        _perf_stats["total_latency"] += result.get("latency", 0)
        raw = result.get("content", "")
        tags = [t.strip() for t in raw.replace("，", ",").split(",") if t.strip()]
        return tags[:8]
    except Exception:
        _perf_stats["errors"] += 1
        raise


def generate_outline(section_summaries: list[dict]) -> list[str]:
    """从章节摘要列表中提取文档大纲（一级/二级章节标题）。

    Args:
        section_summaries: [{"title": "...", "summary": "..."}, ...]

    Returns:
        ["- 第一章 概述", "- 第二章 安全架构", ...]
    """
    if not section_summaries:
        return []

    # 构建输入：每行 "标题: 摘要"
    lines = []
    for s in section_summaries:
        title = s.get("title", "")
        summary = s.get("summary", "")[:100]
        if title and summary:
            lines.append(f"{title}: {summary}")
        elif title:
            lines.append(title)

    combined = "\n".join(lines)[:5000]
    if not combined.strip():
        return []

    messages = [
        {"role": "system", "content": _OUTLINE_SYSTEM},
        {"role": "user", "content": combined},
    ]

    try:
        result = _call_api(messages, max_tokens=500)
        _perf_stats["api_calls"] += 1
        _perf_stats["input_tokens"] += result.get("input_tokens", 0)
        _perf_stats["output_tokens"] += result.get("output_tokens", 0)
        _perf_stats["total_latency"] += result.get("latency", 0)
        content = result.get("content", "")
        # 解析输出：提取以 "- " 开头的行
        outline = [line for line in content.strip().split("\n")
                   if line.startswith("- ") and len(line.strip()) > 2]
        return outline[:30]  # 最多 30 个章节标题
    except Exception:
        _perf_stats["errors"] += 1
        # fallback：去重后的原始标题
        seen = set()
        fallback = []
        for s in section_summaries:
            t = s.get("title", "")
            if t and t not in seen and len(t) > 3:
                seen.add(t)
                fallback.append(f"- {t}")
        return fallback[:20]


# --- 日志分析 ---

def analyze_provider_from_logs(log_lines: list[str]) -> list[dict]:
    """从日志行中分析 provider 健康状态。"""
    import re

    patterns = {
        "rate_limit": re.compile(r"状态码: 429"),
        "server_error": re.compile(r"状态码: (500|502|503|504)"),
        "timeout": re.compile(r"API 超时"),
        "network_error": re.compile(r"API 网络错误"),
        "auth_error": re.compile(r"状态码: (401|403)"),
        "degradation": re.compile(r"\[降级\].*429"),
        "server_degradation": re.compile(r"\[降级\].*5xx"),
    }

    stats = {
        "rate_limit": 0,
        "server_error": 0,
        "timeout": 0,
        "network_error": 0,
        "auth_error": 0,
        "degradation": 0,
        "server_degradation": 0,
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

    if stats["degradation"] > 0:
        analysis.append({
            "severity": "HIGH",
            "issue": "Provider 429 降级触发",
            "count": stats["degradation"],
            "advice": "系统已自动冷却（换 Key/降并发），如频繁触发需增加 Key",
        })

    if stats["server_degradation"] > 0:
        analysis.append({
            "severity": "MEDIUM",
            "issue": "Provider 5xx 降级触发",
            "count": stats["server_degradation"],
            "advice": "API 服务端不稳定，已自动冷却该 provider，持续出现需考虑更换服务商",
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

    if stats["timeout"] > 0:
        analysis.append({
            "severity": "MEDIUM",
            "issue": "请求超时",
            "count": stats["timeout"],
            "advice": "检查网络连接稳定性，或考虑降低 concurrency",
        })

    if stats["server_error"] > 0:
        analysis.append({
            "severity": "MEDIUM",
            "issue": "服务器错误 (5xx)",
            "count": stats["server_error"],
            "advice": "API 服务端问题，稍后自动重试",
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
