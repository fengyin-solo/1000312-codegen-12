"""结算流转台账接口：进度推进、争议挂起/恢复、同周期合并付款、推进记录。

业务判断全部落在 SettlementLedgerService；路由层只做参数解析与结果包装，
推进失败时返回 ok=false 与可读原因，服务端状态保持不变。
"""
from __future__ import annotations

from fastapi import APIRouter, HTTPException, Query

from app.schemas import ActionResult, EntryPayload, PageResult
from app.services.settlement_ledger import LEDGER_STATUSES, SettlementLedgerService

router = APIRouter(prefix="/api/settlement-ledger", tags=["结算流转台账"])

service = SettlementLedgerService()

LIST_FIELDS = [
    "结算单号", "结算对象", "结算周期", "上网电量", "电价标准",
    "应结金额", "已付金额", "结算状态",
]


@router.get("", response_model=PageResult[dict])
def list_entries(
    keyword: str | None = Query(default=None, description="按结算单号或结算对象检索"),
    status: str | None = Query(default=None, description="待核对/核对中/已确认/已付清/有争议"),
    period: str | None = Query(default=None, description="按结算周期精确过滤"),
    target: str | None = Query(default=None, description="按结算对象模糊过滤"),
    page: int = 1,
    size: int = 20,
) -> PageResult[dict]:
    """台账列表，与老结算列表共用同一份主数据，口径一致。"""
    if size > 200:
        raise HTTPException(status_code=400, detail="每页最多 200 条，请缩小分页范围")
    if status and status not in LEDGER_STATUSES:
        raise HTTPException(status_code=400, detail=f"状态「{status}」不在台账状态范围内")
    items, total = service.list_entries(
        keyword=keyword, status=status, period=period, target=target, page=page, size=size
    )
    return PageResult(items=items, total=total, page=page, size=size)


@router.get("/summary")
def summary() -> dict:
    """各状态单数与待付/已付金额合计，供台账顶部进度卡片使用。"""
    return service.summary()


@router.get("/periods")
def periods() -> dict:
    """已有结算周期下拉项。"""
    return {"items": service.list_periods()}


@router.get("/{entry_id}")
def get_entry(entry_id: int) -> dict:
    entry = service.get_entry(entry_id)
    if entry is None:
        raise HTTPException(status_code=404, detail=f"结算单 {entry_id} 不存在或已归档")
    return entry


@router.get("/{entry_id}/history")
def get_history(entry_id: int) -> dict:
    """推进记录：每一步的操作人、时间、动作与当时的应结/已付金额。"""
    history = service.get_history(entry_id)
    if history is None:
        raise HTTPException(status_code=404, detail=f"结算单 {entry_id} 不存在或已归档")
    return {"id": entry_id, "total": len(history), "items": history}


@router.post("", response_model=ActionResult)
def create_entry(payload: EntryPayload) -> ActionResult:
    values = dict(payload.values or {})
    if payload.remark:
        values.setdefault("remark", payload.remark)
    entry, message = service.create_entry(values)
    if entry is None:
        return ActionResult(ok=False, message=message)
    return ActionResult(ok=True, message=message, entry=entry)


@router.post("/{entry_id}/advance", response_model=ActionResult)
def advance_entry(entry_id: int, payload: EntryPayload) -> ActionResult:
    """沿 待核对→核对中→已确认→已付清 单步推进；不满足条件时原状态不变。"""
    values = payload.values or {}
    action = str(values.get("action") or "").strip()
    operator = str(values.get("operator") or "").strip() or None
    entry, message = service.advance(entry_id, action, operator=operator, remark=payload.remark)
    if entry is None:
        return ActionResult(ok=False, message=message)
    return ActionResult(ok=True, message=message, entry=entry)


@router.post("/{entry_id}/dispute", response_model=ActionResult)
def mark_disputed(entry_id: int, payload: EntryPayload) -> ActionResult:
    """把一张核对中/已确认的结算单标记争议，仅挂起该单。"""
    values = payload.values or {}
    operator = str(values.get("operator") or "").strip() or None
    entry, message = service.mark_disputed(entry_id, operator=operator, remark=payload.remark)
    if entry is None:
        return ActionResult(ok=False, message=message)
    return ActionResult(ok=True, message=message, entry=entry)


@router.post("/{entry_id}/resolve", response_model=ActionResult)
def resolve_dispute(entry_id: int, payload: EntryPayload) -> ActionResult:
    """解除争议，结算单回到核对中。"""
    values = payload.values or {}
    operator = str(values.get("operator") or "").strip() or None
    entry, message = service.resolve_dispute(entry_id, operator=operator, remark=payload.remark)
    if entry is None:
        return ActionResult(ok=False, message=message)
    return ActionResult(ok=True, message=message, entry=entry)


@router.post("/merge-payment", response_model=ActionResult)
def merge_payment(payload: EntryPayload) -> ActionResult:
    """同周期多张已确认结算单合并付款：整批校验通过才整体推进。"""
    values = payload.values or {}
    entry_ids = values.get("entry_ids") or []
    if not isinstance(entry_ids, list):
        return ActionResult(ok=False, message="entry_ids 必须是结算单编号数组")
    operator = str(values.get("operator") or "").strip() or None
    entries, message, batch_no = service.merge_payment(
        entry_ids, values.get("paid_amount"), operator=operator, remark=payload.remark
    )
    if entries is None:
        return ActionResult(ok=False, message=message)
    return ActionResult(
        ok=True,
        message=message,
        entry={"batch_no": batch_no, "entry_ids": [e["id"] for e in entries], "items": entries},
    )
