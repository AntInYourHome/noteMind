"""Configuration management for NoteMind."""

import json
import os
from pathlib import Path
from typing import Optional


def load_config(override_vault: Optional[str] = None,
                config_path: Optional[str] = None) -> dict:
    """加载配置文件。

    Args:
        override_vault: 覆盖 vault 路径
        config_path: 配置文件路径（默认 config.json）

    Returns:
        配置字典，vault.path 已展开 ~
    """
    if config_path is None:
        config_path = Path(__file__).parent.parent / "config.json"
    cfg_path = Path(config_path)
    if not cfg_path.exists():
        raise FileNotFoundError(f"配置文件不存在: {cfg_path}")
    with open(cfg_path, "r", encoding="utf-8") as f:
        cfg = json.load(f)
    vault_path = override_vault or cfg["vault"]["path"]
    cfg["vault"]["path"] = os.path.expanduser(vault_path)
    return cfg


def get_vault_path(cfg: dict) -> str:
    """获取 vault 路径。"""
    return cfg["vault"]["path"]


def get_source_path(cfg: dict, vault_path: str, args_source: Optional[str] = None) -> str:
    """获取 source 路径。

    默认 vault 下的 myfiles 目录。
    """
    if args_source:
        return os.path.realpath(args_source)
    return os.path.realpath(os.path.join(vault_path, "myfiles"))
