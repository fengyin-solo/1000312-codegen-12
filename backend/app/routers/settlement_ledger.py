"""结算流转台账接口。

与 /api/settlement（老的电量结算列表）并存：台账提供状态机推进、争议挂起/恢复、
同周期合并付款与推进记录查询；老列表的接口与字段不变。
"""
from __future__ import annotations

from fastapi import APIRouter, HTTPException, Query

from app.schemas import ActionResult, EntryPayload, PageResult
from app.services.settlement_ledger import SettlementLedgerService

router = APIRouter(prefix="/api/settlement-ledger", tags=["结算流转台账"])

service = SettlementLedgerService()

LIST_FIELDS = ["结算单号", "结算对象", "结算周期", "上网电量", "电价标准", "应结金额", "已付金额", "结算状态"]
STATUSES = ["待核对", "核对中", "已确认", "已付清", "有争议"]
ACTIONS = ["开始核对", "确认结算", "登记付款", "标记争议", "恢复争议"]


@router.get("/stats")
def ledger_stats() -> dict:
    """台账概览：各状态单数与应结/已付合计，供页面卡片与列表口径一致地展示。"""
    return service.stats()


@router.get("/merge/preview")
def merge_preview(period: str = Query(description="结算周期，精确匹配")) -> dict:
    """合并付款前预览：列出该周期各状态的结算单，便于页面先核对再提交。"""
    all_rows, _ = service.list_entries(period=period, page=1, size=10000)
    groups: dict[str, list[str]] = {label: [] for label in STATUSES}
    total_due = 0.0
    for row in all_rows:
        groups[str(row.get("结算状态"))].append(str(row.get("结算单号")))
        if row.get("结算状态") == "已确认":
            total_due += float(row.get("应结金额") or 0)
    return {
        "结算周期": period,
        "分组": groups,
        "可合并单数": len(groups["已确认"]),
        "应结合计": round(total_due, 2),
    }


@router.get("", response_model=PageResult[dict])
def list_entries(
    keyword: str | None = Query(default=None, description="按结算单号检索"),
    status: str | None = Query(default=None, description="待核对、核对中、已确认、已付清、有争议"),
    period: str | None = Query(default=None, description="按结算周期模糊检索"),
    page: int = 1,
    size: int = 20,
) -> PageResult[dict]:
    """按结算单号、状态、周期过滤台账；没有数据时返回空页，不报错。"""
    if size > 200:
        raise HTTPException(status_code=400, detail="每页最多 200 条，请缩小分页范围")
    if status and status not in STATUSES:
        raise HTTPException(status_code=400, detail=f"状态「{status}」不在台账状态范围内")
    items, total = service.list_entries(keyword=keyword, status=status, period=period, page=page, size=size)
    return PageResult(items=items, total=total, page=page, size=size)


@router.get("/{entry_id}", response_model=dict)
def get_entry(entry_id: int) -> dict:
    """读取单条结算单台账明细，含每一步的推进记录；不存在时给出可读说明。"""
    entry = service.get_entry(entry_id)
    if entry is None:
        raise HTTPException(status_code=404, detail=f"结算单 {entry_id} 不存在或已归档")
    return entry


@router.post("", response_model=ActionResult)
def create_entry(payload: EntryPayload) -> ActionResult:
    """登记一张结算单：初始状态固定为待核对，同时写入第一条推进记录。"""
    entry, message = service.create_entry(payload.values)
    if entry is None:
        return ActionResult(ok=False, message=message)
    return ActionResult(ok=True, message=message, entry=entry)


@router.post("/merge", response_model=ActionResult)
def merge_pay(payload: EntryPayload) -> ActionResult:
    """同一结算周期多张已确认结算单合并付款：整批校验、原子生效；
    其中被标争议的只挂起自身，不阻塞其他单整体推进。"""
    try:
        summary, message = service.merge_pay(payload.values)
    except Exception as exc:  # noqa: BLE001 - 业务校验失败统一回传可读原因
        return ActionResult(ok=False, message=str(exc))
    if summary is None:
        return ActionResult(ok=False, message=message)
    return ActionResult(ok=True, message=message, entry=summary)


@router.post("/{entry_id}/actions", response_model=ActionResult)
def run_action(entry_id: int, payload: EntryPayload) -> ActionResult:
    """对单张结算单推进状态；前置校验不通过时保持原状态，消息说明失败原因。"""
    action = str(payload.values.get("action") or "").strip()
    values = {key: value for key, value in payload.values.items() if key != "action"}
    values.setdefault("remark", payload.remark)
    entry, message = service.run_action(entry_id, action, values)
    if entry is None:
        return ActionResult(ok=False, message=message)
    return ActionResult(ok=True, message=message, entry=entry)
