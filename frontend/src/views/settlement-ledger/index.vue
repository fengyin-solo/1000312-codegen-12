<template>
  <section class="page" data-module="settlement-ledger">
    <header class="page-head">
      <div>
        <h2>结算流转台账</h2>
        <p class="page-desc">
          结算单按 待核对 → 核对中 → 已确认 → 已付清 推进，每一步记录操作人与时间；
          已付清不可回退，争议只挂起对应单据。
        </p>
      </div>
      <div class="page-actions">
        <RouterLink class="btn ghost" to="/settlement">老的结算列表</RouterLink>
        <button class="btn primary" type="button" @click="openCreate">登记结算单</button>
      </div>
    </header>

    <div class="stat-row">
      <article v-for="item in statCards" :key="item.label" class="stat-card">
        <span class="stat-label">{{ item.label }}</span>
        <strong class="stat-value">{{ item.value }}</strong>
      </article>
    </div>

    <div class="filter-status">
      <button
        v-for="s in statusFilters"
        :key="s"
        type="button"
        :class="{ active: filters.status === s }"
        @click="toggleStatus(s)"
      >
        {{ s }}
      </button>
    </div>

    <form class="filter-bar" @submit.prevent="reload">
      <label class="filter-item">
        <span>结算单号/对象</span>
        <input v-model="filters.keyword" placeholder="按单号或对象检索" />
      </label>
      <label class="filter-item">
        <span>结算周期</span>
        <select v-model="filters.period">
          <option value="">全部周期</option>
          <option v-for="p in periodOptions" :key="p" :value="p">{{ p }}</option>
        </select>
      </label>
      <button class="btn" type="submit">查询</button>
      <button class="btn ghost" type="button" @click="resetFilters">重置条件</button>
    </form>

    <div v-if="selectedRows.length" class="batch-bar">
      <span>已勾选 <strong>{{ selectedRows.length }}</strong> 张（应结合计
        <strong>{{ money(selectedDueTotal) }}</strong>），同周期且全部已确认可合并付款</span>
      <input v-model="mergePaid" type="number" step="0.01" placeholder="实付总额" />
      <button class="btn primary" type="button" @click="openMerge">合并付款</button>
      <button class="btn ghost" type="button" @click="clearSelection">取消勾选</button>
    </div>

    <table class="data-table">
      <thead>
        <tr>
          <th style="width: 36px"></th>
          <th v-for="column in columns" :key="column">{{ column }}</th>
          <th>推进操作</th>
        </tr>
      </thead>
      <tbody>
        <tr v-for="row in rows" :key="String(row.id)">
          <td>
            <input
              type="checkbox"
              :checked="selectedIds.has(Number(row.id))"
              :disabled="row.status !== '已确认'"
              :title="row.status === '已确认' ? '勾选后可合并付款' : '只有已确认的结算单可加入合并付款'"
              @change="toggleSelect(Number(row.id), ($event.target as HTMLInputElement).checked)"
            />
          </td>
          <td>{{ row['结算单号'] ?? '—' }}</td>
          <td>{{ row['结算对象'] ?? '—' }}</td>
          <td>{{ row['结算周期'] ?? '—' }}</td>
          <td class="num">{{ row['上网电量'] == null ? '—' : row['上网电量'] }}</td>
          <td class="num">{{ row['电价标准'] == null ? '—' : row['电价标准'] }}</td>
          <td class="num strong">{{ money(row['应结金额']) }}</td>
          <td class="num">{{ money(row['已付金额']) }}</td>
          <td><span class="status-badge" :class="badgeClass(row.status)">{{ row.status }}</span></td>
          <td class="row-actions">
            <button
              v-for="action in availableActions(row.status)"
              :key="action.name"
              class="link"
              type="button"
              :class="{ danger: action.danger }"
              @click="handleAction(action, row)"
            >
              {{ action.label }}
            </button>
            <button class="link" type="button" @click="openDetail(row)">推进记录</button>
          </td>
        </tr>
        <tr v-if="!rows.length">
          <td :colspan="columns.length + 2" class="empty-state">暂无符合条件的结算台账记录</td>
        </tr>
      </tbody>
    </table>

    <footer class="page-foot">
      <span>共 {{ total }} 张结算单 · 台账列表与老结算列表共用同一份数据</span>
      <span v-if="errorMessage" class="error-text">{{ errorMessage }}</span>
    </footer>

    <!-- 详情抽屉：基础信息 + 推进记录 -->
    <template v-if="detailRow">
      <div class="drawer-mask" @click="closeDetail"></div>
      <aside class="drawer">
        <div class="drawer-head">
          <h3>{{ detailRow['结算单号'] }} · 推进记录</h3>
          <button class="btn ghost" type="button" @click="closeDetail">关闭</button>
        </div>
        <div class="detail-grid">
          <div><span>结算对象</span>{{ detailRow['结算对象'] }}</div>
          <div><span>结算周期</span>{{ detailRow['结算周期'] }}</div>
          <div><span>上网电量</span>{{ detailRow['上网电量'] ?? '—' }}</div>
          <div><span>电价标准</span>{{ detailRow['电价标准'] ?? '—' }}</div>
          <div><span>应结金额</span>{{ money(detailRow['应结金额']) }}</div>
          <div><span>已付金额</span>{{ money(detailRow['已付金额']) }}</div>
          <div>
            <span>当前状态</span>
            <span class="status-badge" :class="badgeClass(detailRow.status)">{{ detailRow.status }}</span>
          </div>
        </div>
        <ol class="timeline">
          <li v-for="t in detailHistory" :key="Number(t.seq)">
            <div><strong>{{ t.action }}</strong>：{{ t.from_status || '初始' }} → {{ t.to_status }}</div>
            <div class="t-meta">
              {{ t.time }} · 操作人：{{ t.operator }}
              · 应结 {{ money(t['应结金额']) }} / 已付 {{ money(t['已付金额']) }}
              <template v-if="t['批次号']"> · 批次 {{ t['批次号'] }}</template>
            </div>
            <div v-if="t.remark" class="t-meta">备注：{{ t.remark }}</div>
          </li>
          <li v-if="!detailHistory.length" class="t-meta">暂无推进记录</li>
        </ol>
      </aside>
    </template>

    <!-- 争议原因 -->
    <template v-if="disputeTarget">
      <div class="modal-mask" @click.self="closeModals">
        <div class="modal">
          <h3>{{ disputeMode === 'mark' ? '标记争议（仅挂起该单）' : '解除争议' }}</h3>
          <div class="form-row">
            <label>说明</label>
            <textarea
              v-model="disputeRemark"
              :placeholder="disputeMode === 'mark' ? '请填写争议原因，必填' : '可填写处理说明'"
            ></textarea>
          </div>
          <div class="modal-foot">
            <button class="btn ghost" type="button" @click="closeModals">取消</button>
            <button class="btn primary" type="button" @click="submitDispute">确认</button>
          </div>
        </div>
      </div>
    </template>

    <!-- 登记结算单 -->
    <template v-if="createOpen">
      <div class="modal-mask" @click.self="closeModals">
        <div class="modal">
          <h3>登记结算单</h3>
          <div class="form-row"><label>结算单号 *</label><input v-model="createForm.code" placeholder="如 SETT-0008" /></div>
          <div class="form-row"><label>结算对象 *</label><input v-model="createForm.target" /></div>
          <div class="form-row"><label>结算周期 *</label><input v-model="createForm.period" placeholder="如 2026-09" /></div>
          <div class="form-row"><label>上网电量（度）</label><input v-model="createForm.energy" type="number" step="0.01" /></div>
          <div class="form-row"><label>电价标准（元/度）</label><input v-model="createForm.price" type="number" step="0.0001" /></div>
          <div v-if="createPreviewDue != null" class="t-meta">系统核算应结金额：{{ money(createPreviewDue) }}</div>
          <div class="modal-foot">
            <button class="btn ghost" type="button" @click="closeModals">取消</button>
            <button class="btn primary" type="button" @click="submitCreate">登记</button>
          </div>
        </div>
      </div>
    </template>

    <div v-if="toast" class="toast" :class="toast.ok ? 'ok' : 'err'">{{ toast.text }}</div>
  </section>
</template>

<script setup lang="ts">
import { computed, onMounted, reactive, ref } from 'vue'

import { request } from '@/api/client'
import { useSessionStore } from '@/stores/session'

const session = useSessionStore()
const ENDPOINT = '/api/settlement-ledger'

type Row = Record<string, string | number | null>
type HistoryItem = Record<string, string | number | null>

const columns = ['结算单号', '结算对象', '结算周期', '上网电量', '电价标准', '应结金额', '已付金额', '结算状态']
const MAIN_STATUSES = ['待核对', '核对中', '已确认', '已付清']
const statusFilters = ['待核对', '核对中', '已确认', '已付清', '有争议']

const rows = ref<Row[]>([])
const total = ref(0)
const errorMessage = ref('')
const periodOptions = ref<string[]>([])
const summary = ref<Record<string, number | Record<string, number>>>({})
const filters = reactive<{ keyword: string; status: string; period: string }>({
  keyword: '',
  status: '',
  period: '',
})

const selectedIds = ref<Set<number>>(new Set())
const mergePaid = ref('')

const detailRow = ref<Row | null>(null)
const detailHistory = ref<HistoryItem[]>([])

const disputeTarget = ref<Row | null>(null)
const disputeMode = ref<'mark' | 'resolve'>('mark')
const disputeRemark = ref('')

const createOpen = ref(false)
const createForm = reactive({ code: '', target: '', period: '', energy: '', price: '' })

const toast = ref<{ ok: boolean; text: string } | null>(null)
let toastTimer: ReturnType<typeof setTimeout> | undefined

function showToast(ok: boolean, text: string) {
  toast.value = { ok, text }
  clearTimeout(toastTimer)
  toastTimer = setTimeout(() => {
    toast.value = null
  }, 3200)
}

function money(value: unknown): string {
  if (value === null || value === undefined || value === '') return '—'
  const n = Number(value)
  if (Number.isNaN(n)) return '—'
  return n.toLocaleString('zh-CN', { minimumFractionDigits: 2, maximumFractionDigits: 2 })
}

function badgeClass(status: unknown): string {
  return `s-${String(status ?? '')}`
}

const statCards = computed(() => {
  const counts = (summary.value.counts ?? {}) as Record<string, number>
  return [
    { label: '待核对', value: counts['待核对'] ?? 0 },
    { label: '核对中', value: counts['核对中'] ?? 0 },
    { label: '已确认待付', value: counts['已确认'] ?? 0 },
    { label: '已付清', value: counts['已付清'] ?? 0 },
    { label: '争议挂起', value: counts['有争议'] ?? 0 },
    { label: '待付金额合计', value: money(summary.value['待付金额合计']) },
    { label: '已付金额合计', value: money(summary.value['已付金额合计']) },
  ]
})

const selectedRows = computed(() => rows.value.filter(r => selectedIds.value.has(Number(r.id))))
const selectedDueTotal = computed(() =>
  selectedRows.value.reduce((sum, r) => sum + Number(r['应结金额'] ?? 0), 0),
)

const createPreviewDue = computed(() => {
  const e = Number(createForm.energy)
  const p = Number(createForm.price)
  if (!createForm.energy || !createForm.price || Number.isNaN(e) || Number.isNaN(p)) return null
  return Math.round(e * p * 100) / 100
})

interface ActionDef {
  name: string
  label: string
  danger?: boolean
  endpoint: 'advance' | 'dispute' | 'resolve'
  requireRemark?: boolean
}

const ACTIONS: Record<string, ActionDef[]> = {
  待核对: [{ name: '发起核对', label: '发起核对', endpoint: 'advance' }],
  核对中: [
    { name: '确认结算', label: '确认结算', endpoint: 'advance' },
    { name: '标记争议', label: '标记争议', endpoint: 'dispute', danger: true, requireRemark: true },
  ],
  已确认: [
    { name: '登记付款', label: '登记付款', endpoint: 'advance' },
    { name: '标记争议', label: '标记争议', endpoint: 'dispute', danger: true, requireRemark: true },
  ],
  有争议: [{ name: '恢复核对', label: '恢复核对', endpoint: 'resolve' }],
  已付清: [],
}

function availableActions(status: unknown): ActionDef[] {
  return ACTIONS[String(status)] ?? []
}

function toggleStatus(status: string) {
  filters.status = filters.status === status ? '' : status
  void reload()
}

function resetFilters() {
  filters.keyword = ''
  filters.status = ''
  filters.period = ''
  void reload()
}

function toggleSelect(id: number, checked: boolean) {
  const next = new Set(selectedIds.value)
  if (checked) next.add(id)
  else next.delete(id)
  selectedIds.value = next
}

function clearSelection() {
  selectedIds.value = new Set()
  mergePaid.value = ''
}

async function postJson(path: string, body: Record<string, unknown>): Promise<{ ok: boolean; message: string; entry?: unknown }> {
  const response = await request(path, {
    method: 'POST',
    body: JSON.stringify(body),
  })
  if (!response.ok) {
    const detail = await response.json().catch(() => null)
    throw new Error(detail?.detail ?? `接口返回 ${response.status}`)
  }
  return response.json()
}

async function reload() {
  errorMessage.value = ''
  const query = new URLSearchParams()
  if (filters.keyword) query.set('keyword', filters.keyword)
  if (filters.status) query.set('status', filters.status)
  if (filters.period) query.set('period', filters.period)
  try {
    const response = await request(`${ENDPOINT}?${query.toString()}`)
    if (!response.ok) throw new Error('结算台账读取失败')
    const payload = await response.json()
    rows.value = payload.items ?? []
    total.value = payload.total ?? rows.value.length
    // 刷新后清理已不在列表或已不是已确认的勾选项，进度口径以服务端为准
    const validIds = new Set(
      rows.value.filter(r => r.status === '已确认').map(r => Number(r.id)),
    )
    selectedIds.value = new Set([...selectedIds.value].filter(id => validIds.has(id)))
  } catch (error) {
    errorMessage.value = error instanceof Error ? error.message : '结算台账读取失败'
  }
}

async function loadSummary() {
  try {
    const [s, p] = await Promise.all([
      request(`${ENDPOINT}/summary`).then(r => r.json()),
      request(`${ENDPOINT}/periods`).then(r => r.json()),
    ])
    summary.value = s
    periodOptions.value = p.items ?? []
  } catch {
    // 卡片不影响主列表，静默即可
  }
}

function handleAction(action: ActionDef, row: Row) {
  if (action.endpoint === 'dispute' || action.endpoint === 'resolve') {
    disputeTarget.value = row
    disputeMode.value = action.endpoint === 'dispute' ? 'mark' : 'resolve'
    disputeRemark.value = ''
    return
  }
  void doAdvance(action.name, Number(row.id))
}

async function doAdvance(action: string, id: number) {
  try {
    const result = await postJson(`${ENDPOINT}/${id}/advance`, {
      values: { action, operator: session.operator },
    })
    if (!result.ok) {
      showToast(false, result.message)
      return
    }
    showToast(true, result.message)
    await Promise.all([reload(), loadSummary()])
  } catch (error) {
    showToast(false, error instanceof Error ? error.message : '推进失败，状态未改变')
  }
}

async function submitDispute() {
  if (!disputeTarget.value) return
  const id = Number(disputeTarget.value.id)
  if (disputeMode.value === 'mark' && !disputeRemark.value.trim()) {
    showToast(false, '标记争议必须填写争议原因')
    return
  }
  const path = disputeMode.value === 'mark' ? 'dispute' : 'resolve'
  try {
    const result = await postJson(`${ENDPOINT}/${id}/${path}`, {
      values: { operator: session.operator },
      remark: disputeRemark.value.trim(),
    })
    if (!result.ok) {
      showToast(false, result.message)
      return
    }
    showToast(true, result.message)
    closeModals()
    await Promise.all([reload(), loadSummary()])
    if (detailRow.value && Number(detailRow.value.id) === id) {
      await openDetail(rows.value.find(r => Number(r.id) === id) ?? detailRow.value)
    }
  } catch (error) {
    showToast(false, error instanceof Error ? error.message : '操作失败，状态未改变')
  }
}

function openMerge() {
  const ids = [...selectedIds.value]
  if (!ids.length) {
    showToast(false, '请先勾选要合并付款的结算单')
    return
  }
  const periods = new Set(selectedRows.value.map(r => String(r['结算周期'])))
  if (periods.size !== 1) {
    showToast(false, `合并付款要求同一结算周期，当前包含：${[...periods].join('、')}`)
    return
  }
  if (selectedRows.value.some(r => r.status !== '已确认')) {
    showToast(false, '只有已确认的结算单才能合并付款')
    return
  }
  const paid = Number(mergePaid.value)
  if (!mergePaid.value || Number.isNaN(paid) || paid < 0) {
    showToast(false, '请填写实付总额')
    return
  }
  const due = Math.round(selectedDueTotal.value * 100) / 100
  if (Math.abs(paid - due) >= 0.01) {
    showToast(false, `实付总额 ${paid.toFixed(2)} 与应结合计 ${due.toFixed(2)} 对不上，已拦截`)
    return
  }
  void doMerge(ids, paid)
}

async function doMerge(ids: number[], paid: number) {
  try {
    const result = await postJson(`${ENDPOINT}/merge-payment`, {
      values: { entry_ids: ids, paid_amount: paid, operator: session.operator },
      remark: `台账页合并付款，${ids.length} 张同批`,
    })
    if (!result.ok) {
      showToast(false, result.message)
      return
    }
    showToast(true, result.message)
    clearSelection()
    await Promise.all([reload(), loadSummary()])
  } catch (error) {
    showToast(false, error instanceof Error ? error.message : '合并付款失败，全部结算单保持原状态')
  }
}

function openCreate() {
  Object.assign(createForm, { code: '', target: '', period: '', energy: '', price: '' })
  createOpen.value = true
}

async function submitCreate() {
  if (!createForm.code.trim() || !createForm.target.trim() || !createForm.period.trim()) {
    showToast(false, '请填写结算单号、结算对象、结算周期')
    return
  }
  const values: Record<string, string> = {
    结算单号: createForm.code.trim(),
    结算对象: createForm.target.trim(),
    结算周期: createForm.period.trim(),
    operator: session.operator,
  }
  if (createForm.energy) values['上网电量'] = createForm.energy
  if (createForm.price) values['电价标准'] = createForm.price
  try {
    const result = await postJson(ENDPOINT, { values })
    if (!result.ok) {
      showToast(false, result.message)
      return
    }
    showToast(true, result.message)
    closeModals()
    await Promise.all([reload(), loadSummary()])
  } catch (error) {
    showToast(false, error instanceof Error ? error.message : '登记失败')
  }
}

async function openDetail(row: Row) {
  detailRow.value = row
  detailHistory.value = []
  try {
    const response = await request(`${ENDPOINT}/${row.id}/history`)
    if (!response.ok) throw new Error('推进记录读取失败')
    const payload = await response.json()
    detailHistory.value = payload.items ?? []
  } catch (error) {
    showToast(false, error instanceof Error ? error.message : '推进记录读取失败')
  }
}

function closeDetail() {
  detailRow.value = null
  detailHistory.value = []
}

function closeModals() {
  disputeTarget.value = null
  createOpen.value = false
}

onMounted(() => {
  void reload()
  void loadSummary()
})
</script>

<style scoped>
.num { text-align: right; font-variant-numeric: tabular-nums; }
.strong { font-weight: 600; }
.link.danger { color: #b42318; }
select { padding: 4px 8px; border: 1px solid var(--border); border-radius: 6px; background: #fff; }
</style>
