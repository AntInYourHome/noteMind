"""crud 公共模块单元测试：类型转换与列元信息。"""
import pytest
from fastapi import HTTPException

from app.crud import coerce, table_columns
from app.modules.notes.models import Note


def test_table_columns_meta():
    cols = {c["name"]: c for c in table_columns(Note)}
    assert cols["id"]["pk"] is True and cols["id"]["kind"] == "integer"
    assert cols["title"]["kind"] == "string" and cols["title"]["required"] is True
    assert cols["content"]["kind"] == "text" and cols["content"]["required"] is False
    assert cols["created_at"]["kind"] == "datetime"


def test_coerce_scalars():
    assert coerce({"kind": "integer"}, "3") == 3
    assert coerce({"kind": "integer"}, "3.7") == 3
    assert coerce({"kind": "float"}, "1.5") == 1.5
    assert coerce({"kind": "boolean"}, "是") is True
    assert coerce({"kind": "boolean"}, "false") is False
    assert coerce({"kind": "boolean"}, True) is True
    assert coerce({"kind": "string"}, 123) == "123"


def test_coerce_datetime():
    from datetime import datetime

    v = coerce({"kind": "datetime"}, "2026-09-03 10:00:00")
    assert v == datetime(2026, 9, 3, 10, 0, 0)
    v = coerce({"kind": "date"}, "2026-09-03")
    assert v.year == 2026 and v.month == 9


def test_coerce_blank_becomes_none():
    assert coerce({"kind": "integer"}, "") is None
    assert coerce({"kind": "string"}, "  ") is None


def test_coerce_invalid_raises_400():
    with pytest.raises(HTTPException) as e:
        coerce({"kind": "integer", "name": "n"}, "abc")
    assert e.value.status_code == 400
