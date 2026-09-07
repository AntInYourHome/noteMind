"""管理面·数据管理：任意工具表的通用 增删改查/导入/导出，全部走 crud.py 公共模块。"""
from fastapi import APIRouter, Body, Depends, File, HTTPException, UploadFile, Response
from sqlalchemy.orm import Session

from .auth import require_admin
from .crud import (
    create_row,
    delete_row,
    export_bytes,
    import_rows,
    list_rows,
    table_columns,
    update_row,
)
from .db import get_db
from .models import User
from .registry import find_table, load_tools
from .utils.importer import read_rows

router = APIRouter(prefix="/api/admin/data", dependencies=[Depends(require_admin)])


def _model(tool: str, table: str):
    model = find_table(tool, table)
    if model is None:
        raise HTTPException(404, f"工具 {tool} 不存在数据表 {table}")
    return model


@router.get("/{tool}")
def list_tables(tool: str, admin: User = Depends(require_admin)):
    for t in load_tools():
        if t["meta"]["name"] == tool:
            return {
                "tool": tool,
                "title": t["meta"]["title"],
                "tables": {name: tb["label"] for name, tb in t["meta"]["tables"].items()},
            }
    raise HTTPException(404, "工具不存在")


@router.get("/{tool}/{table}")
def rows(
    tool: str,
    table: str,
    skip: int = 0,
    limit: int = 50,
    keyword: str = "",
    admin: User = Depends(require_admin),
    db: Session = Depends(get_db),
):
    model = _model(tool, table)
    result = list_rows(db, model, skip=skip, limit=limit, keyword=keyword)
    result["columns"] = table_columns(model)
    result["table_label"] = table
    return result


@router.post("/{tool}/{table}")
def create(
    tool: str,
    table: str,
    data: dict = Body(..., embed=True),
    admin: User = Depends(require_admin),
    db: Session = Depends(get_db),
):
    return create_row(db, _model(tool, table), data)


@router.put("/{tool}/{table}/{row_id}")
def update(
    tool: str,
    table: str,
    row_id,
    data: dict = Body(..., embed=True),
    admin: User = Depends(require_admin),
    db: Session = Depends(get_db),
):
    return update_row(db, _model(tool, table), row_id, data)


@router.delete("/{tool}/{table}/{row_id}")
def remove(
    tool: str,
    table: str,
    row_id,
    admin: User = Depends(require_admin),
    db: Session = Depends(get_db),
):
    return delete_row(db, _model(tool, table), row_id)


@router.post("/{tool}/{table}/import")
async def import_data(
    tool: str,
    table: str,
    file: UploadFile,
    admin: User = Depends(require_admin),
    db: Session = Depends(get_db),
):
    """CSV/XLSX 导入，首行为表头（须与列名一致），非法行自动跳过。"""
    model = _model(tool, table)
    rows = read_rows(file)
    return import_rows(db, model, rows)


@router.get("/{tool}/{table}/export")
def export(
    tool: str,
    table: str,
    format: str = "csv",
    admin: User = Depends(require_admin),
    db: Session = Depends(get_db),
):
    if format not in ("csv", "xlsx"):
        raise HTTPException(400, "仅支持 csv / xlsx")
    content, media_type, filename = export_bytes(db, _model(tool, table), format)
    return Response(
        content=content,
        media_type=media_type,
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )
