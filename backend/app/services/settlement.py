"""电量结算业务规则：老结算列表的入口，底层已并入结算流转台账。

旧页面仍调用本服务，但推进规则、金额口径与历史记录统一由
SettlementLedgerService 维护，避免台账与列表两套状态各说各话。
"""
from __future__ import annotations

from typing import Any

from app.services.settlement_ledger import (
    STATUS_CHECKING,
    STATUS_CONFIRMED,
    STATUS_DISPUTED,
    STATUS_PAID,
    STATUS_PENDING,
    SettlementLedgerService,
)

# 老页面的状态/动作枚举保持原样，前端无需改动
STATUS_ORDER = [STATUS_PENDING, STATUS_CHECKING, STATUS_CONFIRMED, STATUS_PAID, STATUS_DISPUTED]

# 老动作名 → 台账动作名（旧版「确认结算」一步付清的语义在台账里拆成两段）
LEGACY_ACTION_MAP = {
    "发起核对": "发起核对",
    "确认结算": "确认结算",
    "标记争议": "标记争议",
}

_ledger = SettlementLedgerService()


class SettlementService:
    def list_entries(
        self,
        *,
        keyword: str | None = None,
        status: str | None = None,
        page: int = 1,
        size: int = 20,
    ) -> tuple[list[dict[str, Any]], int]:
        return _ledger.list_entries(keyword=keyword, status=status, page=page, size=size)

    def get_entry(self, entry_id: int) -> dict[str, Any] | None:
        return _ledger.get_entry(entry_id)

    def create_entry(self, values: dict[str, Any]) -> tuple[dict[str, Any] | None, list[str]]:
        required = ["结算单号", "结算对象", "结算周期"]
        missing = [field for field in required if not str(values.get(field) or "").strip()]
        if missing:
            return None, missing
        entry, _message = _ledger.create_entry(values)
        return entry, []

    def run_action(self, entry_id: int, action: str) -> tuple[dict[str, Any] | None, str]:
        mapped = LEGACY_ACTION_MAP.get(action)
        if mapped is None:
            return None, f"动作「{action}」不属于电量结算可执行范围"
        if mapped == "标记争议":
            entry, message = _ledger.mark_disputed(entry_id, remark="老结算列表标记，原因待补")
        else:
            entry, message = _ledger.advance(entry_id, mapped)
        return entry, message
