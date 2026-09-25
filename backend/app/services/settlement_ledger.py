"""结算流转台账业务规则。

状态机：待核对 → 核对中 → 已确认 → 已付清，争议为旁路挂起态（恢复后回核对中）。
所有推进只在本模块落库：每一步记录操作人、时间与当时金额；已付清不可逆；
合并付款整批校验通过后才整体推进，任一单不满足则全部保持原状态。
"""
from __future__ import annotations

from datetime import datetime
from typing import Any

from app.store import store

MODULE = "settlement"

# 主流程四个节点，顺序即推进方向，不允许跨级或回退
STATUS_PENDING = "待核对"
STATUS_CHECKING = "核对中"
STATUS_CONFIRMED = "已确认"
STATUS_PAID = "已付清"
# 争议是挂起旁路：只挂起被标记的那一张，恢复后回到核对中
STATUS_DISPUTED = "有争议"
MAIN_STATUSES = [STATUS_PENDING, STATUS_CHECKING, STATUS_CONFIRMED, STATUS_PAID]
LEDGER_STATUSES = MAIN_STATUSES + [STATUS_DISPUTED]

REQUIRED_FIELDS = ["结算单号", "结算对象", "结算周期"]

# 动作 → (允许的前置状态, 目标状态)
ADVANCE_RULES: dict[str, tuple[str, str]] = {
    "发起核对": (STATUS_PENDING, STATUS_CHECKING),
    "确认结算": (STATUS_CHECKING, STATUS_CONFIRMED),
    "登记付款": (STATUS_CONFIRMED, STATUS_PAID),
}
DISPUTE_ALLOWED_FROM = [STATUS_CHECKING, STATUS_CONFIRMED]

DEFAULT_OPERATOR = "值班管理员"


def _now() -> str:
    return datetime.now().strftime("%Y-%m-%d %H:%M:%S")


def _to_number(value: Any, field: str) -> float:
    """把登记时可能以字符串提交的数值转成 float；转不了直接说明原因。"""
    if value is None or str(value).strip() == "":
        raise ValueError(f"「{field}」未填写，无法核算金额")
    try:
        number = float(value)
    except (TypeError, ValueError) as exc:
        raise ValueError(f"「{field}」不是有效数字：{value}") from exc
    if number < 0:
        raise ValueError(f"「{field}」不能为负数：{value}")
    return number


class SettlementLedgerService:
    """结算台账：列表/详情口径与推进规则共用同一份 store 数据，保证不回退、不串口径。"""

    # ---------- 查询 ----------

    def list_entries(
        self,
        *,
        keyword: str | None = None,
        status: str | None = None,
        period: str | None = None,
        target: str | None = None,
        page: int = 1,
        size: int = 20,
    ) -> tuple[list[dict[str, Any]], int]:
        rows = store.rows(MODULE)
        if keyword:
            rows = [
                row
                for row in rows
                if keyword in str(row.get("结算单号", ""))
                or keyword in str(row.get("结算对象", ""))
            ]
        if status:
            rows = [row for row in rows if row.get("status") == status]
        if period:
            rows = [row for row in rows if str(row.get("结算周期", "")) == period]
        if target:
            rows = [row for row in rows if target in str(row.get("结算对象", ""))]
        total = len(rows)
        start = max(page - 1, 0) * size
        return rows[start:start + size], total

    def get_entry(self, entry_id: int) -> dict[str, Any] | None:
        return store.find(MODULE, entry_id)

    def get_history(self, entry_id: int) -> list[dict[str, Any]] | None:
        entry = store.find(MODULE, entry_id)
        if entry is None:
            return None
        return list(entry.get("history", []))

    def list_periods(self) -> list[str]:
        periods = {str(row.get("结算周期", "")) for row in store.rows(MODULE)}
        return sorted(p for p in periods if p)

    def summary(self) -> dict[str, Any]:
        """台账顶部进度卡片：各状态单数与待付/已付金额，口径直接取自主数据。"""
        rows = store.rows(MODULE)
        counts = {status: 0 for status in LEDGER_STATUSES}
        due_unpaid = 0.0
        paid_total = 0.0
        for row in rows:
            status = str(row.get("status"))
            if status in counts:
                counts[status] += 1
            if status == STATUS_CONFIRMED:
                due_unpaid += _safe_float(row.get("应结金额")) - _safe_float(row.get("已付金额"))
            paid_total += _safe_float(row.get("已付金额"))
        return {
            "counts": counts,
            "待付金额合计": round(due_unpaid, 2),
            "已付金额合计": round(paid_total, 2),
            "total": len(rows),
        }

    # ---------- 登记 ----------

    def create_entry(self, values: dict[str, Any]) -> tuple[dict[str, Any] | None, str]:
        missing = [f for f in REQUIRED_FIELDS if not str(values.get(f) or "").strip()]
        if missing:
            return None, f"缺少必填字段：{'、'.join(missing)}"

        rows = store.rows(MODULE)
        code = str(values.get("结算单号")).strip()
        if any(str(row.get("结算单号")) == code for row in rows):
            return None, f"结算单号 {code} 已存在，不能重复登记"

        entry: dict[str, Any] = {
            "id": max((int(row.get("id", 0)) for row in rows), default=0) + 1,
            "status": STATUS_PENDING,
            "pending": True,
            "abnormal": False,
            "结算单号": code,
            "结算对象": str(values.get("结算对象")).strip(),
            "结算周期": str(values.get("结算周期")).strip(),
            "上网电量": None,
            "电价标准": None,
            "应结金额": None,
            "已付金额": 0.0,
            "结算状态": STATUS_PENDING,
            "history": [],
        }

        # 金额信息可在登记后补齐；但没补齐之前推进将被金额校验拦下
        energy_raw = values.get("上网电量")
        price_raw = values.get("电价标准")
        if energy_raw not in (None, "") or price_raw not in (None, ""):
            try:
                energy = _to_number(energy_raw, "上网电量")
                price = _to_number(price_raw, "电价标准")
            except ValueError as exc:
                return None, str(exc)
            entry["上网电量"] = energy
            entry["电价标准"] = price
            entry["应结金额"] = round(energy * price, 2)
        if values.get("应结金额") not in (None, ""):
            try:
                due = _to_number(values.get("应结金额"), "应结金额")
            except ValueError as exc:
                return None, str(exc)
            if entry["应结金额"] is None:
                entry["应结金额"] = due
            elif abs(due - entry["应结金额"]) >= 0.01:
                return (
                    None,
                    f"应结金额 {due:.2f} 与 上网电量×电价标准 "
                    f"{entry['应结金额']:.2f} 对不上，登记已拦截",
                )

        self._track(entry, "登记结算单", "", STATUS_PENDING, values.get("operator"))
        rows.append(entry)
        return entry, "结算单已登记到台账"

    # ---------- 单张推进 ----------

    def advance(
        self,
        entry_id: int,
        action: str,
        operator: str | None = None,
        remark: str | None = None,
    ) -> tuple[dict[str, Any] | None, str]:
        entry = store.find(MODULE, entry_id)
        if entry is None:
            return None, f"结算单 {entry_id} 不存在或已归档"
        rule = ADVANCE_RULES.get(action)
        if rule is None:
            return None, f"动作「{action}」不属于台账允许的推进动作"

        required_from, target = rule
        current = str(entry.get("status"))
        if current == STATUS_DISPUTED:
            return None, f"结算单处于争议挂起状态，需先恢复核对，不能直接{action}"
        if current == STATUS_PAID:
            return None, "结算单已付清，进度不能回退或重复推进"
        if current != required_from:
            return None, self._out_of_order_message(current, required_from, action)

        message = self._money_blocker(entry, action)
        if message:
            return None, message

        before = dict(entry)
        history_len = len(entry.get("history", []))
        from_status = current
        try:
            if action == "登记付款":
                entry["已付金额"] = _safe_float(entry.get("应结金额"))
            entry["status"] = target
            entry["结算状态"] = target
            entry["pending"] = target != STATUS_PAID
            entry["abnormal"] = False
            self._track(entry, action, from_status, target, operator, remark=remark)
        except Exception:  # pragma: no cover - 落库异常时回滚，保持原状态与原推进记录
            entry.clear()
            entry.update(before)
            if len(entry.get("history", [])) > history_len:
                entry["history"] = entry["history"][:history_len]
            raise
        return entry, f"结算单 {entry['结算单号']} 已{action}，当前状态：{target}"

    # ---------- 争议挂起 / 恢复 ----------

    def mark_disputed(
        self,
        entry_id: int,
        operator: str | None = None,
        remark: str | None = None,
    ) -> tuple[dict[str, Any] | None, str]:
        entry = store.find(MODULE, entry_id)
        if entry is None:
            return None, f"结算单 {entry_id} 不存在或已归档"
        current = str(entry.get("status"))
        if current == STATUS_PAID:
            return None, "结算单已付清，不能再标记争议"
        if current == STATUS_DISPUTED:
            return None, "结算单已是争议挂起状态，无需重复标记"
        if current == STATUS_PENDING:
            return None, "结算单尚未发起核对，不能直接标记争议"
        if current not in DISPUTE_ALLOWED_FROM:
            return None, f"当前状态「{current}」不允许标记争议"
        if not str(remark or "").strip():
            return None, "标记争议必须填写争议原因"

        entry["status"] = STATUS_DISPUTED
        entry["结算状态"] = STATUS_DISPUTED
        entry["pending"] = True
        entry["abnormal"] = True
        self._track(entry, "标记争议", current, STATUS_DISPUTED, operator, remark=remark)
        return entry, f"结算单 {entry['结算单号']} 已挂起，不影响同周期其他结算单推进"

    def resolve_dispute(
        self,
        entry_id: int,
        operator: str | None = None,
        remark: str | None = None,
    ) -> tuple[dict[str, Any] | None, str]:
        entry = store.find(MODULE, entry_id)
        if entry is None:
            return None, f"结算单 {entry_id} 不存在或已归档"
        current = str(entry.get("status"))
        if current != STATUS_DISPUTED:
            return None, "只有争议挂起的结算单才能恢复核对"

        entry["status"] = STATUS_CHECKING
        entry["结算状态"] = STATUS_CHECKING
        entry["pending"] = True
        entry["abnormal"] = False
        self._track(entry, "恢复核对", current, STATUS_CHECKING, operator, remark=remark)
        return entry, f"结算单 {entry['结算单号']} 争议已解除，回到核对中"

    # ---------- 同周期合并付款 ----------

    def merge_payment(
        self,
        entry_ids: list[Any],
        paid_amount: Any,
        operator: str | None = None,
        remark: str | None = None,
    ) -> tuple[list[dict[str, Any]] | None, str, str | None]:
        """同周期多张已确认结算单合并付款：先整批校验，通过后才整体推进。

        任一单不存在、状态不是已确认、周期不一致或金额对不上，整批拒绝，
        所有结算单保持原状态；其中一张处于争议挂起时，只把该单剔除即可，
        不影响同批其他单。
        """
        if not entry_ids:
            return None, "未勾选任何结算单，无法合并付款", None
        try:
            ids = [int(v) for v in entry_ids]
        except (TypeError, ValueError):
            return None, "结算单编号格式不正确", None
        if len(set(ids)) != len(ids):
            return None, "勾选的结算单有重复，请去重后再提交", None
        try:
            paid_total = _to_number(paid_amount, "实付总额")
        except ValueError as exc:
            return None, str(exc), None

        entries: list[dict[str, Any]] = []
        for entry_id in ids:
            entry = store.find(MODULE, entry_id)
            if entry is None:
                return None, f"结算单 {entry_id} 不存在或已归档，整批付款未执行", None
            entries.append(entry)

        periods = {str(e.get("结算周期")) for e in entries}
        if len(periods) != 1:
            return None, f"合并付款要求同一结算周期，当前包含：{'、'.join(sorted(periods))}", None

        for entry in entries:
            current = str(entry.get("status"))
            code = entry.get("结算单号")
            if current == STATUS_DISPUTED:
                return None, f"结算单 {code} 处于争议挂起，仅挂起该单，请从付款批次中剔除后重试", None
            if current == STATUS_PAID:
                return None, f"结算单 {code} 已付清，不能重复付款", None
            if current != STATUS_CONFIRMED:
                return (
                    None,
                    f"结算单 {code} 当前为「{current}」，需推进到已确认才能合并付款",
                    None,
                )
            blocker = self._money_blocker(entry, "登记付款")
            if blocker:
                return None, blocker, None

        due_total = round(sum(_safe_float(e.get("应结金额")) for e in entries), 2)
        if abs(paid_total - due_total) >= 0.01:
            return (
                None,
                f"实付总额 {paid_total:.2f} 与本批应结合计 {due_total:.2f} 对不上，整批付款已拦截",
                None,
            )

        # 校验全部通过，生成同一批次号并整体推进
        batch_no = "PAY-" + datetime.now().strftime("%Y%m%d%H%M%S")
        operator_name = str(operator or "").strip() or DEFAULT_OPERATOR
        note = str(remark or "").strip() or f"同周期合并付款，{len(entries)} 张结算单同批付清"
        for entry in entries:
            entry["已付金额"] = _safe_float(entry.get("应结金额"))
            entry["status"] = STATUS_PAID
            entry["结算状态"] = STATUS_PAID
            entry["pending"] = False
            entry["abnormal"] = False
            self._track(
                entry,
                "登记付款",
                STATUS_CONFIRMED,
                STATUS_PAID,
                operator_name,
                remark=note,
                batch_no=batch_no,
            )
        return entries, f"{len(entries)} 张结算单已合并付清，批次号 {batch_no}", batch_no

    # ---------- 内部工具 ----------

    def _money_blocker(self, entry: dict[str, Any], action: str) -> str:
        """推进前的金额一致性校验：初始态金额不齐、应结对不上、已付越界一律拦截。"""
        code = entry.get("结算单号")
        current = str(entry.get("status"))

        # 进入核对中、确认结算前都重新核对应结 = 上网电量 × 电价标准，
        # 防止金额在台账之外被改动后继续推进
        if action in ("发起核对", "确认结算"):
            try:
                energy = _to_number(entry.get("上网电量"), "上网电量")
                price = _to_number(entry.get("电价标准"), "电价标准")
                due = _to_number(entry.get("应结金额"), "应结金额")
            except ValueError as exc:
                return f"结算单 {code} {exc}，请先补齐金额再{action}"
            if abs(due - round(energy * price, 2)) >= 0.01:
                stage = "发起核对" if action == "发起核对" else "确认结算"
                return (
                    f"结算单 {code} 应结金额 {due:.2f} 与 上网电量×电价标准 "
                    f"{energy * price:.2f} 对不上，{stage}已拦截"
                )
            if action == "发起核对" and _safe_float(entry.get("已付金额")) != 0:
                return f"结算单 {code} 尚未进入付款环节，已付金额应为 0"
            return ""

        # 已确认 → 已付清：金额沿用台账，确认未被外部改坏且不欠付
        try:
            due = _to_number(entry.get("应结金额"), "应结金额")
            paid = _safe_float(entry.get("已付金额"))
        except ValueError as exc:
            return f"结算单 {code} {exc}，推进已拦截"
        if due < 0 or paid < 0:
            return f"结算单 {code} 金额不能为负"
        if current in (STATUS_CHECKING, STATUS_CONFIRMED) and paid != 0:
            return f"结算单 {code} 未付清前不应有已付金额，当前已付 {paid:.2f}"
        return ""

    @staticmethod
    def _out_of_order_message(current: str, required_from: str, action: str) -> str:
        current_index = MAIN_STATUSES.index(current) if current in MAIN_STATUSES else -1
        required_index = MAIN_STATUSES.index(required_from)
        if current_index >= 0 and current_index > required_index:
            return f"结算单当前为「{current}」，台账进度不能回退到「{required_from}」后再{action}"
        return f"结算单当前为「{current}」，需先处于「{required_from}」才能{action}，不能跨级推进"

    def _track(
        self,
        entry: dict[str, Any],
        action: str,
        from_status: str,
        to_status: str,
        operator: Any,
        *,
        remark: str | None = None,
        batch_no: str | None = None,
    ) -> None:
        history = entry.setdefault("history", [])
        history.append({
            "seq": len(history) + 1,
            "time": _now(),
            "action": action,
            "from_status": from_status,
            "to_status": to_status,
            "operator": str(operator or "").strip() or DEFAULT_OPERATOR,
            "remark": str(remark or "").strip(),
            "应结金额": _safe_float(entry.get("应结金额")),
            "已付金额": _safe_float(entry.get("已付金额")),
            "批次号": batch_no,
        })


def _safe_float(value: Any) -> float:
    try:
        return round(float(value), 2)
    except (TypeError, ValueError):
        return 0.0
