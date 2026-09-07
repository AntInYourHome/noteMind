"""小工具：日志解析。上传或粘贴日志，输出级别统计、时间范围和聚类后的错误/告警。

纯计算型工具的示例：无数据表（不需要 models.py），只提供接口。
"""
import re
from collections import Counter

from fastapi import APIRouter, Depends, File, Form, HTTPException, UploadFile

from ...auth import get_current_user
from ...models import User

TOOL = {"title": "日志解析", "importable": False}

router = APIRouter()

MAX_BYTES = 20 * 1024 * 1024
MAX_LINES = 2_000_000
TOP_N = 30

LEVEL_RE = re.compile(
    r"\b(ERROR|ERR|FATAL|CRITICAL|CRIT|WARNING|WARN|NOTICE|INFO|DEBUG|TRACE|VERBOSE)\b",
    re.IGNORECASE,
)
LEVEL_MAP = {
    "ERR": "ERROR", "FATAL": "ERROR", "CRIT": "ERROR", "CRITICAL": "ERROR",
    "WARNING": "WARN", "VERBOSE": "DEBUG",
}
ERROR_LEVELS = {"ERROR", "ERR", "FATAL", "CRITICAL", "CRIT"}
WARN_LEVELS = {"WARN", "WARNING"}

TS_PATTERNS = [
    re.compile(r"\d{4}-\d{2}-\d{2}[ T]\d{2}:\d{2}:\d{2}(?:[.,]\d+)?(?:Z|[+-]\d{2}:?\d{2})?"),
    re.compile(r"\[\s*\d+\.\d+\s*\]"),       # kernel 单调时间 [ 123.456]
    re.compile(r"[A-Z][a-z]{2}\s+\d{1,2}\s+\d{2}:\d{2}:\d{2}"),  # syslog
    re.compile(r"\d{2}:\d{2}:\d{2}(?:[.,]\d+)?"),
]

# 聚类归一化：数字/十六进制地址/引号串等替换为占位符
NOISE_RES = [
    (re.compile(r"\b0[xX][0-9a-fA-F]+\b"), "0xH"),
    (re.compile(r"\b[0-9a-fA-F]{8,}\b"), "HEX"),
    (re.compile(r"'[^']*'"), "'S'"),
    (re.compile(r'"[^"]*"'), '"S"'),
    (re.compile(r"\d+"), "N"),
]


def normalize(line: str) -> str:
    s = line.strip()
    for pat, rep in NOISE_RES:
        s = pat.sub(rep, s)
    return re.sub(r"\s+", " ", s)[:200]


def analyze_lines(lines: list[str]) -> dict:
    levels: Counter = Counter()
    error_groups: dict[str, dict] = {}
    warn_groups: dict[str, dict] = {}
    first_ts = last_ts = None

    for idx, line in enumerate(lines, 1):
        m = LEVEL_RE.search(line)
        if m:
            levels[LEVEL_MAP.get(m.group(1).upper(), m.group(1).upper())] += 1
        else:
            levels["OTHER"] += 1

        for pat in TS_PATTERNS:
            t = pat.search(line)
            if t:
                if first_ts is None:
                    first_ts = t.group(0)
                last_ts = t.group(0)
                break

        if not m:
            continue
        raw = m.group(1).upper()
        if raw in ERROR_LEVELS:
            bucket = error_groups
        elif raw in WARN_LEVELS:
            bucket = warn_groups
        else:
            continue
        key = normalize(line)
        g = bucket.get(key)
        if g is None:
            bucket[key] = {
                "pattern": key,
                "count": 1,
                "first_line": idx,
                "last_line": idx,
                "sample": line.strip()[:300],
            }
        else:
            g["count"] += 1
            g["last_line"] = idx

    def top(bucket: dict) -> list:
        return sorted(bucket.values(), key=lambda g: -g["count"])[:TOP_N]

    return {
        "levels": dict(levels),
        "first_timestamp": first_ts,
        "last_timestamp": last_ts,
        "error_groups": top(error_groups),
        "warn_groups": top(warn_groups),
    }


@router.post("/analyze")
async def analyze(
    file: UploadFile | None = File(None),
    text: str = Form(default=""),
    user: User = Depends(get_current_user),
):
    if file is not None:
        raw = await file.read()
        if len(raw) > MAX_BYTES:
            raise HTTPException(400, "文件超过 20MB 限制")
        content = raw.decode("utf-8", errors="replace")
    elif text.strip():
        content = text
    else:
        raise HTTPException(400, "请上传日志文件或粘贴日志文本")

    lines = content.splitlines()[:MAX_LINES]
    result = analyze_lines(lines)
    result["total_lines"] = len(lines)
    return result
