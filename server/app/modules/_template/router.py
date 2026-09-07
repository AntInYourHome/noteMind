"""新工具后端模板：复制本目录后，改 TOOL 元信息与接口实现。

简单 CRUD 可直接复用 crud 公共模块（见 docs/开发指南.md），不必手写。
"""
from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from ...auth import get_current_user
from ...crud import create_row, delete_row, list_rows, update_row
from ...db import get_db
from ...models import User
from .models import Item

# 平台元信息：title 进门户菜单；tables 声明的表会出现在管理面"数据管理"
TOOL = {
    "title": "工具名称（显示在菜单）",
    "importable": False,
    "tables": {"template_items": "条目表"},
}

router = APIRouter()


@router.get("")
def list_items(
    skip: int = 0,
    limit: int = 50,
    keyword: str = "",
    user: User = Depends(get_current_user),   # 每个接口都必须带鉴权
    db: Session = Depends(get_db),
):
    return list_rows(db, Item, skip=skip, limit=limit, keyword=keyword)


@router.post("")
def create_item(
    data: dict,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    return create_row(db, Item, data)


@router.put("/{item_id}")
def update_item(
    item_id: int,
    data: dict,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    return update_row(db, Item, item_id, data)


@router.delete("/{item_id}")
def delete_item(
    item_id: int,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    return delete_row(db, Item, item_id)
