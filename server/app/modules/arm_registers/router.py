"""小工具：ARM(AArch64) 寄存器查询。静态数据集检索，无数据表。"""
from fastapi import APIRouter, Depends

from ...auth import get_current_user
from ...models import User
from .data import CLASSES, REGISTERS

TOOL = {"title": "ARM 寄存器查询", "importable": False}

router = APIRouter()


@router.get("/classes")
def list_classes(user: User = Depends(get_current_user)):
    return CLASSES


@router.get("")
def list_registers(
    skip: int = 0,
    limit: int = 50,
    keyword: str = "",
    klass: str = "",
    user: User = Depends(get_current_user),
):
    kw = keyword.strip().lower()
    items = []
    for r in REGISTERS:
        if klass and r["klass"] != klass:
            continue
        if kw and kw not in (
            r["name"].lower() + " " + (r["encoding"] or "").lower() + " " + r["desc"].lower()
        ):
            continue
        items.append(r)
    return {"total": len(items), "items": items[skip: skip + limit]}
