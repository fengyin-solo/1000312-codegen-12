"""结算流转台账业务规则冒烟测试：直接驱动 service，覆盖状态机、金额校验、
争议挂起/恢复、同周期合并付款与刷新不回退等约束。运行：python3 scripts/smoke_ledger.py
"""
from __future__ import annotations

import sys

sys.path.insert(0, ".")

from app.services.settlement_ledger import SettlementLedgerService, MODULE  # noqa: E402
from app.store import store  # noqa: E402

service = SettlementLedgerService()
failures: list[str] = []


def check(name: str, condition: bool, detail: str = "") -> None:
    print(("PASS " if condition else "FAIL ") + name + (f" — {detail}" if detail and not condition else ""))
    if not condition:
        failures.append(name)


def fresh(code: str = "T-001", amount: float = 1000.0, period: str = "2026-09", target: str = "测试对象") -> dict:
    entry, msg = service.create_entry(
        {"结算单号": code, "结算对象": target, "结算周期": period, "应结金额": amount}
    )
    assert entry, msg
    return entry


# 1. 登记后初始状态固定待核对，应结有值、已付为 0，并写入第一条记录
e = fresh("S-1")
check("新单初始为待核对", e["status"] == "待核对")
check("新单已付金额为 0", float(e["已付金额"]) == 0.0)
check("新单有登记记录", len(e["records"]) == 1 and e["records"][0]["action"] == "登记结算单")

# 2. 正常推进：待核对→核对中→已确认→已付清，每步有操作人与时间
entry, _ = service.run_action(e["id"], "开始核对", {"operator": "张三"})
check("推进到核对中", entry["status"] == "核对中")
entry, _ = service.run_action(e["id"], "确认结算", {"operator": "李四"})
check("推进到已确认并锁定应结", entry["status"] == "已确认" and float(entry["应结金额"]) == 1000.0)
entry, msg = service.run_action(e["id"], "登记付款", {"operator": "王五", "已付金额": 1000})
check("付清成功", bool(entry) and entry["status"] == "已付清", msg)
check("已付跟随应结", entry and float(entry["已付金额"]) == 1000.0)
check("每步都有操作人和时间", entry and all(r["operator"] and r["time"] for r in entry["records"]))
check("共 4 条推进记录", entry and len(entry["records"]) == 4)

# 3. 已付清不能再改回核对中（任何推进/争议都拦下，状态不动）
entry, msg = service.run_action(e["id"], "开始核对", {})
check("已付清不能回核对中", entry is None and "已付清" in msg, msg)
entry2 = service.get_entry(e["id"])
check("失败后保持已付清", entry2 is not None and entry2["status"] == "已付清")
entry, msg = service.run_action(e["id"], "标记争议", {})
check("已付清不能挂争议", entry is None)
check("挂争议失败状态不变", service.get_entry(e["id"])["status"] == "已付清")

# 4. 跳步/初始状态直接付款被拦
e2 = fresh("S-2")
entry, msg = service.run_action(e2["id"], "登记付款", {"已付金额": 1000})
check("初始状态直接付款被拦", entry is None and "待核对" in msg, msg)
check("被拦后仍是待核对", service.get_entry(e2["id"])["status"] == "待核对")
entry, msg = service.run_action(e2["id"], "确认结算", {})
check("待核对不能跳到确认", entry is None)
entry, msg = service.run_action(e2["id"], "标记争议", {})
check("待核对不能标记争议", entry is None and "待核对" in msg, msg)

# 5. 金额对不上不能付清；金额字段不被污染
service.run_action(e2["id"], "开始核对", {})
service.run_action(e2["id"], "确认结算", {})
before = service.get_entry(e2["id"])
entry, msg = service.run_action(e2["id"], "登记付款", {"已付金额": 800})
check("金额对不上被拦", entry is None and "金额对不上" in msg, msg)
after = service.get_entry(e2["id"])
check("失败后已付金额保持 0", float(after["已付金额"]) == 0.0)
check("失败后状态保持已确认", after["status"] == "已确认")
check("失败不追加推进记录", len(after["records"]) == len(before["records"]))
entry, msg = service.run_action(e2["id"], "登记付款", {"已付金额": "不是数字"})
check("非数字金额被拦", entry is None and "数字" in msg, msg)
entry, msg = service.run_action(e2["id"], "登记付款", {"已付金额": 1200})
check("超额付款被拦", entry is None and "超过应结金额" in msg, msg)

# 6. 争议只挂起那一张；恢复后回到核对中；争议期间不能推进
e3 = fresh("S-3")
service.run_action(e3["id"], "开始核对", {"operator": "赵六"})
entry, msg = service.run_action(e3["id"], "标记争议", {"operator": "赵六", "remark": "电量口径异议"})
check("标记争议后展示有争议", entry and entry["status"] == "有争议", msg)
check("争议标记 abnormal", entry and entry["abnormal"] is True)
entry, msg = service.run_action(e3["id"], "确认结算", {})
check("争议挂起期间不能推进", entry is None and "争议" in msg, msg)
entry, msg = service.run_action(e3["id"], "恢复争议", {"operator": "钱七"})
check("恢复后回到核对中", entry and entry["status"] == "核对中", msg)
check("恢复后无 abnormal", entry and entry["abnormal"] is False)
check("恢复记录可追溯", entry and entry["records"][-1]["action"] == "恢复争议")
# 恢复后可以继续沿状态机走完
entry, _ = service.run_action(e3["id"], "确认结算", {})
entry, _ = service.run_action(e3["id"], "登记付款", {"已付金额": 1000})
check("恢复后可推进到付清", entry and entry["status"] == "已付清")

# 已确认状态也可以挂争议
e4 = fresh("S-4")
service.run_action(e4["id"], "开始核对", {})
service.run_action(e4["id"], "确认结算", {})
entry, _ = service.run_action(e4["id"], "标记争议", {})
check("已确认也可挂争议", entry and entry["status"] == "有争议")

# 7. 同周期合并付款：整批推进；其中一张争议只挂起自己
m1, _ = service.create_entry({"结算单号": "M-1", "结算对象": "A", "结算周期": "P1", "应结金额": 100})
m2, _ = service.create_entry({"结算单号": "M-2", "结算对象": "A", "结算周期": "P1", "应结金额": 200})
m3, _ = service.create_entry({"结算单号": "M-3", "结算对象": "A", "结算周期": "P1", "应结金额": 300})
m4, _ = service.create_entry({"结算单号": "M-4", "结算对象": "A", "结算周期": "P1", "应结金额": 50})
for mid in (m1["id"], m2["id"], m3["id"], m4["id"]):
    service.run_action(mid, "开始核对", {})
for mid in (m1["id"], m2["id"], m3["id"]):
    service.run_action(mid, "确认结算", {})
# m4 停在核对中：合并付款整批被拦
summary, msg = service.merge_pay({"结算周期": "P1", "已付金额": 600})
check("有核对中单时整批不付", summary is None and "核对中" in msg, msg)
check("被拦时已确认单不付清", service.get_entry(m1["id"])["status"] == "已确认")
# m4 也确认后标记争议：其余三张正常合并，m4 只挂起自己
service.run_action(m4["id"], "确认结算", {})
service.run_action(m4["id"], "标记争议", {})
summary, msg = service.merge_pay({"结算周期": "P1", "已付金额": 600, "operator": "财务-孙"})
check("合并付款成功", summary is not None and summary["count"] == 3 and summary["总金额"] == 600, msg)
for mid in (m1["id"], m2["id"], m3["id"]):
    got = service.get_entry(mid)
    check(f"单 {got['结算单号']} 已付清", got["status"] == "已付清" and float(got["已付金额"]) == float(got["应结金额"]))
    check(f"单 {got['结算单号']} 留痕操作人", got["records"][-1]["operator"] == "财务-孙")
check("争议单不参与付款仍挂起", service.get_entry(m4["id"])["status"] == "有争议")

# 8. 合并付款金额对不上整批不执行
n1, _ = service.create_entry({"结算单号": "N-1", "结算对象": "B", "结算周期": "P2", "应结金额": 100})
n2, _ = service.create_entry({"结算单号": "N-2", "结算对象": "B", "结算周期": "P2", "应结金额": 200})
for mid in (n1["id"], n2["id"]):
    service.run_action(mid, "开始核对", {})
    service.run_action(mid, "确认结算", {})
summary, msg = service.merge_pay({"结算周期": "P2", "已付金额": 250})
check("合并金额对不上被拦", summary is None and "金额对不上" in msg, msg)
check("整批失败保持已确认", all(service.get_entry(x)["status"] == "已确认" for x in (n1["id"], n2["id"])))
check("整批失败金额不变", all(float(service.get_entry(x)["已付金额"]) == 0 for x in (n1["id"], n2["id"])))
summary, msg = service.merge_pay({"结算周期": "不存在", "已付金额": 1})
check("无此周期合并被拦", summary is None and "没有结算单" in msg, msg)

# 9. 台账与列表口径一致、刷新不回退（内存数据再次读取仍为原状态）
items, total = service.list_entries(status="已付清", page=1, size=200)
list_ids = {item["id"] for item in items}
detail_paid = {row["id"] for row in store.rows(MODULE) if service.get_entry(row["id"])["status"] == "已付清"}
check("列表与详情状态口径一致", list_ids == detail_paid, f"{list_ids ^ detail_paid}")
stats = service.stats()
check("统计已付清数一致", stats["by_status"]["已付清"] == len(list_ids))
check("统计各状态之和等于总数", sum(stats["by_status"].values()) == stats["total"])
check("已付合计不超过应结合计", stats["已付合计"] <= stats["应结合计"] + 0.01)

# 10. 登记校验：缺字段、非法金额、重复单号
entry, msg = service.create_entry({"结算单号": "X-1", "结算对象": "", "结算周期": "P"})
check("缺必填被拦", entry is None and "缺少必填字段" in msg, msg)
entry, msg = service.create_entry({"结算单号": "X-2", "结算对象": "A", "结算周期": "P", "应结金额": 0})
check("应结为 0 被拦", entry is None and "大于 0" in msg, msg)
entry, msg = service.create_entry({"结算单号": "S-1", "结算对象": "A", "结算周期": "P", "应结金额": 1})
check("重复单号被拦", entry is None and "已存在" in msg, msg)

# 11. 老结算模块完全不受影响
from app.services.settlement import SettlementService  # noqa: E402
old = SettlementService().list_entries(page=1, size=10)[0]
check("老结算列表仍是 3 条样例", len(old) == 3 and old[0]["status"] == "待核对")

print()
if failures:
    print(f"{len(failures)} 项失败：{failures}")
    sys.exit(1)
print("全部通过")
