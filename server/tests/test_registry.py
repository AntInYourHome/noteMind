"""模块注册表：发现与表查找。"""
from app.modules.notes.models import Note
from app.registry import find_table, load_tools, tools_info


def test_tools_info_shape():
    info = tools_info()
    names = {t["name"] for t in info}
    assert {"notes", "log_parser", "arm_registers"} <= names
    # 元信息可 JSON 序列化（不含模型类）
    import json

    json.dumps(info)


def test_find_table():
    assert find_table("notes", "notes") is Note
    assert find_table("notes", "nope") is None
    assert find_table("nope", "notes") is None


def test_template_not_loaded():
    """_template 以下划线开头，仅作模板，不应被加载。"""
    assert all(t["meta"]["name"] != "_template" for t in load_tools())
