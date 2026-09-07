"""自动发现 modules/ 下的所有小工具模块。

每个小工具是一个子目录，包含：
  - router.py  必须有：router（APIRouter 实例）、TOOL（元信息 dict）
  - models.py  可选：该工具的数据表

新增工具 = 复制一个现有工具目录改名，无需修改本文件。
"""
import importlib
import pkgutil

from fastapi import APIRouter

from . import modules as modules_pkg
from .db import Base

_tool_cache: list[dict] | None = None


def load_tools() -> list[dict]:
    """扫描并挂载所有工具路由，返回工具元信息列表（含数据表清单）。"""
    global _tool_cache
    if _tool_cache is not None:
        return _tool_cache

    tools = []
    for m in pkgutil.iter_modules(modules_pkg.__path__):
        if m.name.startswith("_"):
            continue
        try:
            router_mod = importlib.import_module(f"app.modules.{m.name}.router")
        except ModuleNotFoundError:
            continue
        router = getattr(router_mod, "router", None)
        tool_meta = getattr(router_mod, "TOOL", None)
        if not isinstance(router, APIRouter) or not isinstance(tool_meta, dict):
            continue
        meta = {
            "name": m.name,
            "title": tool_meta.get("title", m.name),
            "importable": bool(tool_meta.get("importable", False)),
        }

        # 收集该工具的数据表（models.py 中定义的模型）
        tables: dict[str, dict] = {}
        try:
            models_mod = importlib.import_module(f"app.modules.{m.name}.models")
            labels = tool_meta.get("tables", {})
            for attr in vars(models_mod).values():
                if (
                    isinstance(attr, type)
                    and issubclass(attr, Base)
                    and attr is not Base
                    and attr.__module__ == f"app.modules.{m.name}.models"
                ):
                    tables[attr.__tablename__] = {
                        "label": labels.get(attr.__tablename__, attr.__tablename__),
                        "model": attr,
                    }
        except ModuleNotFoundError:
            pass
        meta["tables"] = tables

        tools.append({"meta": meta, "router": router})

    _tool_cache = tools
    return tools


def tools_info() -> list[dict]:
    return [
        {
            "name": t["meta"]["name"],
            "title": t["meta"]["title"],
            "importable": t["meta"]["importable"],
            "tables": {name: tb["label"] for name, tb in t["meta"]["tables"].items()},
        }
        for t in load_tools()
    ]


def find_table(tool_name: str, table_name: str):
    """按工具名+表名取模型类。"""
    for t in load_tools():
        if t["meta"]["name"] == tool_name:
            tb = t["meta"]["tables"].get(table_name)
            if tb:
                return tb["model"]
    return None
