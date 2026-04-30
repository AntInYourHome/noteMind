"""
NoteMind AI 客户端 — 纯标准库实现，零外部依赖
使用 urllib 直接调用 qwen3.6-flash API
"""

import base64
import json
import logging
import os
import random
import time
import urllib.request
import urllib.error

logger = logging.getLogger("notemind")

_MAX_RETRIES = 3
_BASE_DELAY = 1.0  # 秒


def _get_config() -> dict:
    api_key = os.environ.get("QWEN_API_KEY")
    if not api_key:
        raise ValueError("QWEN_API_KEY 环境变量未设置")
    return {
        "api_key": api_key,
        "base_url": "https://dashscope.aliyuncs.com/compatible-mode/v1",
        "model": "qwen3.6-flash",
    }


def _should_retry(status_code: int) -> bool:
    """判断是否应重试。"""
    # 429 限流、5xx 服务器错误、503 服务不可用
    return status_code in (429, 500, 502, 503, 504)


def _call_api(messages: list, max_tokens: int = 500, retries: int = None) -> str:
    cfg = _get_config()
    url = f"{cfg['base_url']}/chat/completions"

    payload = json.dumps({
        "model": cfg["model"],
        "messages": messages,
        "max_tokens": max_tokens,
    }).encode("utf-8")

    req = urllib.request.Request(
        url,
        data=payload,
        headers={
            "Content-Type": "application/json",
            "Authorization": f"Bearer {cfg['api_key']}",
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
