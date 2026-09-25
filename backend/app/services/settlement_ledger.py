"""结算流转台账业务规则。

与老的电量结算模块（settlement）相互独立：台账单独建表、单独接口，老的结算列表
口径保持不变。台账的核心约束：

* 主状态只能沿 待核对 → 核对中 → 已确认 → 已付清 单向推进，不能回退；
* 每推进一步都追加一条操作记录（操作人、时间、动作、备注）；
* 「有争议」是挂起标记：只挂起被标记的那一张，恢复后回到核对中；已付清的不能挂起；
* 应结金额在「确认结算」时锁定，已付金额在「登记付款 / 合并付款」时跟随状态变化，
  金额对不上的推进一律拦下；
* 同一结算周期合并付款时整批校验、原子生效，争议单只挂起自身、不影响同批其他单。
"""
from __future__ import annotations

from datetime import datetime
from typing import Any

from app.store import store

MODULE = "settlement_ledger"
REQUIRED_FIELDS = ["结算单号", "结算对象", "结算周期"]

MAIN_STATUSES = ["待核对", "核对中", "已确认", "已付清"]
DISPUTED_STATUS = "有争议"
ALL_STATUSES = [*MAIN_STATUSES, DISPUTED_STATUS]

# 状态机：当前主状态 -> 允许推进到的下一个主状态
NEXT_STATUS: dict[str, str] = {
    "待核对": "核对中",
    "核对中": "已确认",
    "已确认": "已付清",
}

ACTION_LABELS = {
    "开始核对": "开始核对",
    "确认结算": "确认结算",
    "登记付款": "登记付款",
    "标记争议": "标记争议",
    "恢复争议": "恢复争议",
}

DEFAULT_OPERATOR = "值班管理员"
AMOUNT_EPSILON = 0.01  # 合并付款允许的最小误差（元）


class LedgerError(Exception):
    """推进前置校验失败：消息会原样返回给页面说明原因，调用方负责保持原状态。"""


def now_text() -> str:
    return datetime.now().strftime("%Y-%m-%d %H:%M:%S")


def _operator(values: dict[str, Any] | None) -> str:
    name = str((values or {}).get("operator") or "").strip()
    return name or DEFAULT_OPERATOR


def _remark(values: dict[str, Any] | None) -> str:
    return str((values or {}).get("remark") or "").strip()


def parse_amount(value: Any) -> float | None:
    """把前端传进来的金额转成数字；空值、非数字、负数都视为无效。"""
    if value is None or value == "":
        return None
    try:
        amount = float(value)
    except (TypeError, ValueError):
        return None
    if amount != amount or amount < 0:  # NaN 或负数
        return None
    return round(amount, 2)


def display_status(entry: dict[str, Any]) -> str:
    """台账对外的展示状态：主状态叠加争议挂起标记，列表与详情共用这一个口径。"""
    return DISPUTED_STATUS if entry.get("disputed") else str(entry.get("status"))


def make_record(action: str, operator: str, remark: str = "", *, at: str | None = None) -> dict[str, Any]:
    return {
        "seq": 0,
        "time": at or now_text(),
        "action": action,
        "operator": operator,
        "remark": remark,
    }


def _append_record(entry: dict[str, Any], record: dict[str, Any]) -> None:
    records: list[dict[str, Any]] = entry.setdefault("records", [])
    record["seq"] = len(records) + 1
    records.append(record)


def _settle_amount(entry: dict[str, Any], field: str, value: Any, label: str) -> float:
    amount = parse_amount(value)
    if amount is None:
        raise LedgerError(f"{label}必须是不小于 0 的数字，当前为「{value}」")
    entry[field] = amount
    return amount


def _snapshot(entry: dict[str, Any]) -> dict[str, Any]:
    """列表口径：状态字段与后端内部字段对齐，但不带操作记录，减少列表传输量。"""
    view = dict(entry)
    view["status"] = display_status(entry)
    view["pending"] = not (entry["status"] == "已付清" and not entry.get("disputed"))
    view["abnormal"] = bool(entry.get("disputed"))
    view["结算状态"] = view["status"]
    view.pop("records", None)
    return view


class SettlementLedgerService:
    # ------------------------------------------------------------------ 查询
    def list_entries(
        self,
        *,
        keyword: str | None = None,
        status: str | None = None,
        period: str | None = None,
        page: int = 1,
        size: int = 20,
    ) -> tuple[list[dict[str, Any]], int]:
        rows = store.rows(MODULE)
        if keyword:
            rows = [row for row in rows if keyword in str(row.get("结算单号", ""))]
        if period:
            rows = [row for row in rows if period in str(row.get("结算周期", ""))]
        if status:
            rows = [row for row in rows if display_status(row) == status]
        total = len(rows)
        start = max(page - 1, 0) * size
        return [_snapshot(row) for row in rows[start:start + size]], total

    def get_entry(self, entry_id: int) -> dict[str, Any] | None:
        """详情口径：直接返回台账记录本身（含操作记录），与列表同一份数据、同一状态口径。"""
        entry = store.find(MODULE, entry_id)
        if entry is None:
            return None
        view = dict(entry)
        view["status"] = display_status(entry)
        view["pending"] = not (entry["status"] == "已付清" and not entry.get("disputed"))
        view["abnormal"] = bool(entry.get("disputed"))
        view["结算状态"] = view["status"]
        view["records"] = [dict(item) for item in entry.get("records", [])]
        return view

    def stats(self) -> dict[str, Any]:
        rows = store.rows(MODULE)
        by_status = {label: 0 for label in ALL_STATUSES}
        for row in rows:
            by_status[display_status(row)] += 1
        return {
            "total": len(rows),
            "by_status": by_status,
            "disputed": by_status[DISPUTED_STATUS],
            "应结合计": round(sum(float(row.get("应结金额") or 0) for row in rows), 2),
            "已付合计": round(sum(float(row.get("已付金额") or 0) for row in rows), 2),
        }

    # ------------------------------------------------------------------ 登记
    def create_entry(self, values: dict[str, Any]) -> tuple[dict[str, Any] | None, str]:
        missing = [field for field in REQUIRED_FIELDS if not str(values.get(field) or "").strip()]
        if missing:
            return None, f"缺少必填字段：{'、'.join(missing)}"
        amount = parse_amount(values.get("应结金额"))
        if amount is None or amount <= 0:
            return None, "应结金额必须是大于 0 的数字，结算单先按初始状态「待核对」登记"
        rows = store.rows(MODULE)
        code = str(values["结算单号"]).strip()
        if any(str(row.get("结算单号")) == code for row in rows):
            return None, f"结算单号「{code}」已存在，不能重复登记"
        entry: dict[str, Any] = {
            "id": max((int(row.get("id", 0)) for row in rows), default=0) + 1,
            "结算单号": code,
            "结算对象": str(values["结算对象"]).strip(),
            "结算周期": str(values["结算周期"]).strip(),
            "上网电量": str(values.get("上网电量") or "").strip(),
            "电价标准": str(values.get("电价标准") or "").strip(),
            "应结金额": amount,
            "已付金额": 0.0,
            "status": "待核对",
            "disputed": False,
            "pending": True,
            "abnormal": False,
            "records": [],
        }
        _append_record(entry, make_record("登记结算单", _operator(values), _remark(values)))
        rows.append(entry)
        return self.get_entry(entry["id"]), "结算单已登记，初始状态为待核对"

    # ------------------------------------------------------------------ 单张推进
    def run_action(
        self, entry_id: int, action: str, values: dict[str, Any] | None = None
    ) -> tuple[dict[str, Any] | None, str]:
        entry = store.find(MODULE, entry_id)
        if entry is None:
            return None, f"结算单 {entry_id} 不存在或已归档"
        try:
            if action in ("开始核对", "确认结算", "登记付款"):
                self._advance(entry, action, values or {})
            elif action == "标记争议":
                self._mark_dispute(entry, values or {})
            elif action == "恢复争议":
                self._resolve_dispute(entry, values or {})
            else:
                return None, f"动作「{action}」不属于结算流转台账可执行范围"
        except LedgerError as exc:
            # 校验失败：不写任何字段、不追加记录，保持原状态并说明原因
            return None, str(exc)
        return self.get_entry(entry_id), f"结算单已{action}"

    def _guard_advance(self, entry: dict[str, Any], action: str) -> None:
        if entry.get("disputed"):
            raise LedgerError("结算单处于争议挂起状态，需先恢复争议再继续推进")
        current = str(entry["status"])
        expected_action = {"待核对": "开始核对", "核对中": "确认结算", "已确认": "登记付款"}.get(current)
        if expected_action is None:
            raise LedgerError(f"结算单已付清，付款进度不能回退到核对中")
        if action != expected_action:
            # 进度显示成初始状态（如刷新后仍停在待核对）或跳步推进都在这里拦住
            raise LedgerError(
                f"当前状态为「{current}」，下一步只能「{expected_action}」，不能直接「{action}」"
            )

    def _advance(self, entry: dict[str, Any], action: str, values: dict[str, Any]) -> None:
        self._guard_advance(entry, action)
        operator, remark = _operator(values), _remark(values)
        current = str(entry["status"])

        if action == "开始核对":
            entry["status"] = "核对中"
        elif action == "确认结算":
            # 确认时锁定应结金额；初始状态直接推进到确认会被 _guard_advance 拦住
            submitted = values.get("应结金额")
            if submitted is not None and str(submitted) != "":
                _settle_amount(entry, "应结金额", submitted, "应结金额")
            if float(entry.get("应结金额") or 0) <= 0:
                raise LedgerError("应结金额必须大于 0 才能确认结算")
            entry["status"] = "已确认"
        elif action == "登记付款":
            due = parse_amount(entry.get("应结金额"))
            if not due or due <= 0:
                raise LedgerError("应结金额尚未锁定，不能登记付款")
            paid = parse_amount(values.get("已付金额"))
            if paid is None:
                raise LedgerError(
                    f"已付金额必须是不小于 0 的数字，当前为「{values.get('已付金额')}」"
                )
            # 先校验、后落字段：金额对不上时原状态与原金额都不动
            if paid > due + AMOUNT_EPSILON:
                raise LedgerError(f"已付金额 {paid:.2f} 超过应结金额 {due:.2f}，不能推进")
            if abs(paid - due) > AMOUNT_EPSILON:
                raise LedgerError(
                    f"金额对不上：已付金额 {paid:.2f} 与应结金额 {due:.2f} 不一致，不能标记已付清"
                )
            entry["已付金额"] = due  # 付清后已付金额与应结金额严格一致
            entry["status"] = "已付清"
        _append_record(entry, make_record(action, operator, remark))

    def _mark_dispute(self, entry: dict[str, Any], values: dict[str, Any]) -> None:
        if entry.get("disputed"):
            raise LedgerError("结算单已在争议挂起中，无需重复标记")
        current = str(entry["status"])
        if current == "待核对":
            raise LedgerError("结算单还在待核对初始状态，先开始核对后才能标记争议")
        if current == "已付清":
            raise LedgerError("结算单已付清，不能再改回核对中，也不允许挂起争议")
        entry["disputed"] = True
        note = _remark(values)
        _append_record(
            entry,
            make_record(
                "标记争议",
                _operator(values),
                f"仅挂起本张结算单，原进度「{current}」保留{('：' + note) if note else ''}",
            ),
        )

    def _resolve_dispute(self, entry: dict[str, Any], values: dict[str, Any]) -> None:
        if not entry.get("disputed"):
            raise LedgerError("结算单当前没有争议挂起，无需恢复")
        # 恢复后统一回到核对中：争议解决后需要重新核对，再沿状态机继续推进
        entry["disputed"] = False
        entry["status"] = "核对中"
        _append_record(
            entry,
            make_record(
                "恢复争议",
                _operator(values),
                f"争议已处理，回到核对中重新核对{('；' + _remark(values)) if _remark(values) else ''}",
            ),
        )

    # ------------------------------------------------------------------ 同周期合并付款
    def merge_pay(self, values: dict[str, Any]) -> tuple[dict[str, Any] | None, str]:
        period = str(values.get("结算周期") or "").strip()
        if not period:
            return None, "合并付款必须指定结算周期"
        amount = parse_amount(values.get("已付金额"))
        if amount is None:
            return None, f"合并付款总额必须是不小于 0 的数字，当前为「{values.get('已付金额')}」"
        operator, remark = _operator(values), _remark(values)

        same_period = [
            row for row in store.rows(MODULE) if str(row.get("结算周期") or "").strip() == period
        ]
        if not same_period:
            return None, f"结算周期「{period}」下没有结算单"

        targets = [row for row in same_period if row["status"] == "已确认" and not row.get("disputed")]
        blocked_initial = [row for row in same_period if row["status"] == "待核对" and not row.get("disputed")]
        checking = [row for row in same_period if row["status"] == "核对中" and not row.get("disputed")]
        disputed = [row for row in same_period if row.get("disputed")]
        paid = [row for row in same_period if row["status"] == "已付清"]

        # 合并付款整体推进：同周期还有没走到已确认的单，整批先不付
        pending_others = blocked_initial + checking
        if not targets:
            if paid and not pending_others:
                return None, f"结算周期「{period}」的结算单均已付清，无需重复合并付款"
            return None, f"结算周期「{period}」下没有可合并付款的「已确认」结算单，请先完成核对确认"
        if pending_others:
            parts = []
            if blocked_initial:
                parts.append(f"{len(blocked_initial)} 张仍在待核对（{_codes(blocked_initial)}）")
            if checking:
                parts.append(f"{len(checking)} 张仍在核对中（{_codes(checking)}）")
            raise_msg = "付款进度未到齐：" + "、".join(parts) + "，请先完成核对确认"
            if disputed:
                raise_msg += f"；另有 {len(disputed)} 张争议挂起（{_codes(disputed)}），只挂起那几张、不参与本次付款"
            return None, raise_msg

        total_due = round(sum(float(row["应结金额"]) for row in targets), 2)
        if abs(amount - total_due) > AMOUNT_EPSILON:
            return None, (
                f"金额对不上：本次合并付款 {amount:.2f} 与 {len(targets)} 张已确认结算单"
                f"应结合计 {total_due:.2f} 不一致，整批付款未执行，各单保持原状态"
            )

        at = now_text()
        # 整批校验通过后原子生效：逐张推进到已付清并各自留痕
        for row in targets:
            due = float(row["应结金额"])
            row["已付金额"] = due
            row["status"] = "已付清"
            row["pending"] = False
            note_parts = [f"{period} 合并付款"]
            if len(targets) > 1:
                note_parts.append(f"同批 {len(targets)} 张合计 {total_due:.2f} 元")
            if remark:
                note_parts.append(remark)
            _append_record(row, make_record("登记付款", operator, "；".join(note_parts), at=at))

        message = f"{period} 合并付款完成：{len(targets)} 张结算单整体推进到已付清，合计 {total_due:.2f} 元"
        skipped: list[str] = []
        if disputed:
            skipped.append(f"{len(disputed)} 张争议单保持挂起（{_codes(disputed)}）")
        if paid:
            skipped.append(f"{len(paid)} 张已付清单未重复付款（{_codes(paid)}）")
        if skipped:
            message += "；" + "、".join(skipped)
        return {"结算周期": period, "count": len(targets), "总金额": total_due}, message


def _codes(rows: list[dict[str, Any]]) -> str:
    return "、".join(str(row.get("结算单号")) for row in rows)
