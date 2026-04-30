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


class APIProviderPool:
    """管理多个 API provider，轮询分配请求。"""

    def __init__(self, providers: list[dict] = None, concurrency: int = 5):
        """
        Args:
            providers: 配置列表 [{"api_key": "...", "model": "...", "base_url": "..."}, ...]
                      如果为 None，使用环境变量单 provider
            concurrency: 最大并发数
        """
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

    def next_provider(self) -> dict:
        """轮询获取下一个 provider。"""
        with self._lock:
            p = self.providers[self._index % len(self.providers)].copy()
            self._index += 1
            return p

    def call(self, messages: list, max_tokens: int = 500, retries: int = 3) -> str:
        """调用 API（使用下一个 provider）。"""
        return _call_with_provider(self.next_provider(), messages, max_tokens, retries)

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
