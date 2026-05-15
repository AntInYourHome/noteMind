"""Path computation utilities for vault/source alignment."""

import os


def compute_source_relative_path(file_path: str, source_dir: str, vault_path: str) -> str:
    """计算 vault 内镜像 source 结构的相对目录路径。

    例如: source=/vault/source, file=/vault/source/安全/白皮书.pdf → "安全"
    文件在 source 根目录时返回 ""（空字符串，表示 vault 根目录）。
    source 不在 vault 下时返回 "外部文件"。
    返回值统一使用 '/' 分隔符，确保跨设备同步兼容。
    """
    rel = os.path.relpath(file_path, source_dir)
    rel_dir = os.path.dirname(rel)
    if not rel_dir:
        return ""  # 根目录文件，放在 vault 根目录
    # 安全检查：防止路径穿越
    abs_dest = os.path.normpath(os.path.join(vault_path, rel_dir))
    abs_vault = os.path.normpath(vault_path)
    if not abs_dest.startswith(abs_vault + os.sep) and abs_dest != abs_vault:
        return "外部文件"
    # 统一用 '/' 分隔符（跨平台兼容）
    return rel_dir.replace(os.sep, "/")


def compute_vault_rel_path(file_path: str, source_dir: str, vault_path: str) -> str:
    """计算源文件相对于 vault 的路径，用于 MD 文档的 original_path。

    如果 source 在 vault 下，返回 vault 内相对路径。
    否则返回 source 内相对路径（带 source/ 前缀）。
    返回值统一使用 '/' 分隔符，确保跨设备同步兼容。
    """
    try:
        rel = os.path.relpath(file_path, vault_path)
        if not rel.startswith(".."):
            return rel.replace(os.sep, "/")
    except (ValueError, OSError):
        pass
    # source 在 vault 外，使用 source 内相对路径
    try:
        src_rel = os.path.relpath(file_path, source_dir)
        return "source/" + src_rel.replace(os.sep, "/")
    except (ValueError, OSError):
        return os.path.basename(file_path)
