"""数据库操作公共模块：对任意工具表提供 增删改查 / 导入 / 导出。

管理面"数据管理"页面基于本模块实现；工具开发者也可以直接使用：
    from ..crud import list_rows, create_row, update_row, delete_row, import_rows, export_bytes
"""
import csv
import io
from datetime import date, datetime
from decimal import Decimal

from fastapi import HTTPException
from sqlalchemy import BigInteger, Boolean, Date, DateTime, Float, Integer, String, Text, or_
from sqlalchemy import func
from sqlalchemy.orm import Session

from .db import Base

EXPORT_MAX_ROWS = 100_000


# ---------- 元信息 ----------

def table_columns(model) -> list[dict]:
    """返回表的列元信息，供前端动态渲染表格/表单。"""
    cols = []
    for c in model.__table__.columns:
        t = c.type
        if isinstance(t, (Integer, BigInteger)):
            kind = "integer"
        elif isinstance(t, Float):
            kind = "float"
        elif isinstance(t, Boolean):
            kind = "boolean"
        elif isinstance(t, DateTime):
            kind = "datetime"
        elif isinstance(t, Date):
            kind = "date"
        elif isinstance(t, Text):
            kind = "text"
        else:
            kind = "string"
        cols.append({
            "name": c.name,
            "kind": kind,
            "pk": c.primary_key,
            "required": (
                not c.nullable and not c.primary_key
                and c.default is None and c.server_default is None
            ),
            "max_length": getattr(t, "length", None),
        })
    return cols


def pk_column(model):
    return next(c for c in model.__table__.columns if c.primary_key)


# ---------- 序列化与类型转换 ----------

def serialize_value(v):
    if isinstance(v, (datetime, date)):
        return v.isoformat(sep=" ")
    if isinstance(v, Decimal):
        return float(v)
    if isinstance(v, bytes):
        return None
    return v


def row_dict(model, obj) -> dict:
    return {c.name: serialize_value(getattr(obj, c.name)) for c in model.__table__.columns}


def coerce(col_meta: dict, value):
    """按列类型把外部输入（JSON/CSV单元格）转换为可入库的值。"""
    if value is None or (isinstance(value, str) and value.strip() == ""):
        return None
    kind = col_meta["kind"]
    try:
        if kind == "integer":
            return int(float(str(value)))
        if kind == "float":
            return float(str(value))
        if kind == "boolean":
            if isinstance(value, bool):
                return value
            s = str(value).strip().lower()
            if s in ("true", "1", "是", "yes", "y"):
                return True
            if s in ("false", "0", "否", "no", "n"):
                return False
            raise ValueError(value)
        if kind == "datetime":
            return datetime.fromisoformat(str(value).replace("T", " ").strip()[:26])
        if kind == "date":
            return datetime.fromisoformat(str(value).strip()[:10]).date()
        return str(value)
    except (ValueError, TypeError):
        raise HTTPException(400, f"字段 {col_meta['name']} 的值无法转换为 {kind} 类型：{value!r}")


# ---------- 增删改查 ----------

def list_rows(db: Session, model, skip: int = 0, limit: int = 50, keyword: str = "") -> dict:
    q = db.query(model)
    kw = (keyword or "").strip()
    if kw:
        text_cols = [c for c in model.__table__.columns if isinstance(c.type, (String, Text))]
        if text_cols:
            q = q.filter(or_(c.contains(kw) for c in text_cols))
    total = db.query(func.count()).select_from(q.subquery()).scalar() or 0
    items = q.order_by(pk_column(model).desc()).offset(skip).limit(min(limit, 500)).all()
    return {"total": total, "items": [row_dict(model, o) for o in items]}


def create_row(db: Session, model, data: dict) -> dict:
    cols = {c["name"]: c for c in table_columns(model)}
    kwargs = {}
    for name, value in (data or {}).items():
        meta = cols.get(name)
        if meta is None or meta["pk"]:
            continue
        kwargs[name] = coerce(meta, value)
    obj = model(**kwargs)
    db.add(obj)
    db.commit()
    db.refresh(obj)
    return row_dict(model, obj)


def update_row(db: Session, model, row_id, data: dict) -> dict:
    obj = db.get(model, row_id)
    if not obj:
        raise HTTPException(404, "记录不存在")
    cols = {c["name"]: c for c in table_columns(model)}
    for name, value in (data or {}).items():
        meta = cols.get(name)
        if meta is None or meta["pk"]:
            continue
        setattr(obj, name, coerce(meta, value))
    db.commit()
    db.refresh(obj)
    return row_dict(model, obj)


def delete_row(db: Session, model, row_id) -> dict:
    obj = db.get(model, row_id)
    if not obj:
        raise HTTPException(404, "记录不存在")
    db.delete(obj)
    db.commit()
    return {"ok": True}


# ---------- 导入 / 导出 ----------

def import_rows(db: Session, model, rows: list[dict]) -> dict:
    """rows: [{表头: 值}, ...]，表头须与列名一致；非法行跳过并计数。"""
    cols = {c["name"]: c for c in table_columns(model)}
    inserted, skipped = 0, 0
    for row in rows:
        kwargs = {}
        try:
            for name, meta in cols.items():
                if meta["pk"] or name not in row:
                    continue
                v = coerce(meta, row[name])
                if v is None and meta["required"]:
                    raise ValueError(name)
                kwargs[name] = v
            db.add(model(**kwargs))
            db.commit()
            inserted += 1
        except Exception:
            db.rollback()
            skipped += 1
    return {"inserted": inserted, "skipped": skipped, "total_rows": len(rows)}


def _all_rows(db: Session, model):
    return db.query(model).order_by(pk_column(model)).limit(EXPORT_MAX_ROWS).all()


def export_bytes(db: Session, model, fmt: str = "csv") -> tuple[bytes, str, str]:
    """导出全表，返回 (内容, Content-Type, 文件名)。fmt: csv | xlsx"""
    cols = table_columns(model)
    headers = [c["name"] for c in cols]
    rows = _all_rows(db, model)
    name = model.__tablename__
    if fmt == "xlsx":
        from openpyxl import Workbook

        wb = Workbook(write_only=True)
        ws = wb.create_sheet()
        ws.append(headers)
        for o in rows:
            ws.append([serialize_value(getattr(o, c["name"])) for c in cols])
        buf = io.BytesIO()
        wb.save(buf)
        return buf.getvalue(), "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet", f"{name}.xlsx"
    # csv 带 BOM，Excel 直接打开不乱码
    out = io.StringIO()
    writer = csv.writer(out)
    writer.writerow(headers)
    for o in rows:
        writer.writerow([serialize_value(getattr(o, c["name"])) for c in cols])
    return ("\ufeff" + out.getvalue()).encode("utf-8"), "text/csv; charset=utf-8", f"{name}.csv"
