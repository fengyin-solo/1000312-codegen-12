# 光伏电站智能运维平台

面向光伏电站并网、方阵逆变器监测、组件清洗巡检、消缺处理与发电量结算的一体化运维后台。

这是一个前后端分离的管理平台：前端 Vue 3 + Vite + TypeScript，后端 FastAPI（Python）。
两边各自独立启动，前端 dev server 已关掉自动打开页面，启动后按终端打印的地址手工打开。

## 目录结构

```text
.
├── frontend/                 Vue 3 + Vite + TypeScript 前端
│   ├── src/views/            每个业务模块一个页面
│   ├── src/api/              统一请求封装
│   ├── src/stores/           会话与筛选状态
│   └── vite.config.ts        dev server 配置（open: false）
├── backend/                  FastAPI（Python） 后端
│   ├── app/routers/          每个业务模块一组接口
│   ├── app/services/         业务规则与状态流转
│   └── app/store.py          内存数据仓库与示例数据
├── .gitignore
└── docker-compose.yml
```

## 启动

### 后端

```bash
cd backend
python3 -m venv .venv && .venv/bin/pip install -r requirements.txt
./run.sh
```

健康检查：`curl http://127.0.0.1:8000/api/health`

### 前端

```bash
cd frontend
npm install
npm run dev
```

前端默认监听 `http://127.0.0.1:5173/`，dev server 不会自动打开浏览器，
需要自己访问。`/api` 由 vite 代理到后端 `http://127.0.0.1:8000`。

## 业务模块

| 模块 | 目录 | 业务对象 | 主要字段 |
| --- | --- | --- | --- |
| 光伏电站 | `station` | 电站档案 | 电站编码、电站名称、装机容量 |
| 光伏方阵 | `array` | 方阵 | 方阵编号、方阵名称、组件型号 |
| 逆变器管理 | `inverter` | 逆变器 | 设备编号、设备型号、额定功率 |
| 汇流箱管理 | `combiner` | 汇流箱 | 汇流箱编号、接入组串数、直流电压 |
| 组串监测 | `stringmon` | 组串 | 组串编号、所属方阵、实测电流 |
| 辐照监测 | `irradiance` | 辐照测点 | 测点编号、测点位置、总辐照度 |
| 组件清洗 | `cleaning` | 清洗任务 | 任务编号、清洗区域、计划日期 |
| 巡检任务 | `inspection` | 巡检单 | 巡检单号、巡检类型、巡检路线 |
| 缺陷登记 | `defect` | 设备缺陷 | 缺陷编号、所属设备、缺陷类型 |
| 消缺处理 | `repair` | 消缺单 | 消缺单号、关联缺陷、处理措施 |
| 备件领用 | `sparepart` | 备件领用单 | 领用单号、备件名称、备件规格 |
| 发电量核算 | `generation` | 发电记录 | 记录编号、电站名称、统计日期 |
| 限电记录 | `curtail` | 限电事件 | 事件编号、所属电站、限电原因 |
| 告警中心 | `alarm` | 告警事件 | 告警编号、告警类型、告警等级 |
| 作业许可 | `permit` | 作业许可单 | 许可编号、作业类型、作业地点 |
| 运维承包商 | `contractor` | 承包商档案 | 承包商编码、承包商名称、资质等级 |
| 培训考核 | `training` | 培训计划 | 培训编号、培训主题、培训对象 |
| 电量结算 | `settlement` | 结算单 | 结算单号、结算对象、结算周期 |
| 结算流转台账 | `settlement_ledger` | 结算单流转 | 待核对/核对中/已确认/已付清、争议挂起、合并付款批次、推进记录 |

## 约定

- 每个模块的前端页面在 `frontend/src/views/<模块>/index.vue`，后端接口在
  `backend/app/routers/<模块>.py`，业务规则在 `backend/app/services/<模块>.py`。
- 列表接口统一返回 `{ items, total, page, size }`，动作接口统一返回 `{ ok, message }`。
- 状态流转只允许在 `app/services` 里改，路由层不做业务判断。
