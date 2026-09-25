<template>
  <section class="page" data-module="settlement-ledger">
    <header class="page-head">
      <div>
        <h2>结算流转台账</h2>
        <p class="page-desc">
          结算单按 待核对 → 核对中 → 已确认 → 已付清 单向推进，每一步记录操作人与时间；
          争议只挂起本单，恢复后回到核对中；同周期多张可合并付款。进度不能回退，金额对不上会被拦下。
        </p>
      </div>
      <div class="page-actions">
        <button class="btn" type="button" @click="openMerge">同周期合并付款</button>
        <button class="btn primary" type="button" @click="openCreate">登记结算单</button>
      </div>
    </header>

    <div class="stat-row">
      <article v-for="item in statCards" :key="item.label" class="stat-card">
        <span class="stat-label">{{ item.label }}</span>
        <strong class="stat-value" :class="{ warn: item.warn }">{{ item.value }}</strong>
      </article>
    </div>

    <form class="filter-bar" @submit.prevent="reload">
      <label class="filter-item">
        <span>结算单号</span>
        <input v-model="filters.keyword" placeholder="按结算单号检索" />
      </label>
      <label class="filter-item">
        <span>结算周期</span>
        <input v-model="filters.period" placeholder="如 2026-09" />
      </label>
      <label class="filter-item">
        <span>结算状态</span>
        <select v-model="filters.status">
          <option value="">全部状态</option>
          <option v-for="s in statuses" :key="s" :value="s">{{ s }}</option>
        </select>
      </label>
      <button class="btn" type="submit">查询</button>
      <button class="btn ghost" type="button" @click="resetFilters">重置条件</button>
    </form>

    <table class="data-table ledger-table">
      <thead>
        <tr>
          <th v-for="column in columns" :key="column">{{ column }}</th>
          <th>可执行动作</th>
        </tr>
      </thead>
      <tbody>
        <tr v-for="row in rows" :key="String(row.id)">
          <td>
            <button class="link" type="button" @click="openDetail(row)">{{ row['结算单号'] }}</button>
          </td>
          <td>{{ row['结算对象'] ?? '—' }}</td>
          <td>{{ row['结算周期'] ?? '—' }}</td>
          <td>{{ formatAmount(row['应结金额']) }}</td>
          <td>{{ formatAmount(row['已付金额']) }}</td>
          <td>
            <span class="status-tag" :class="statusClass(row['结算状态'])">{{ row['结算状态'] }}</span>
          </td>
          <td class="row-actions">
            <button
              v-for="action in allowedActions(row['结算状态'])"
              :key="action"
              class="link"
              type="button"
              @click="runAction(action, row)"
            >
              {{ action }}
            </button>
            <button class="link" type="button" @click="openDetail(row)">推进记录</button>
          </td>
        </tr>
        <tr v-if="!rows.length">
          <td :colspan="columns.length + 1" class="empty-state">台账暂无符合条件的结算单</td>
        </tr>
      </tbody>
    </table>

    <footer class="page-foot">
      <span>共 {{ total }} 条台账记录，列表与详情状态口径一致</span>
      <span v-if="message" :class="messageOk ? 'ok-text' : 'error-text'">{{ message }}</span>
    </footer>

    <!-- 登记结算单 -->
    <div v-if="createOpen" class="modal-mask" @click.self="createOpen = false">
      <div class="modal">
        <h3>登记结算单</h3>
        <p class="modal-tip">登记后固定为初始状态「待核对」，并记录登记人与时间。</p>
        <label v-for="field in createFields" :key="field.key" class="form-item">
          <span>{{ field.label }}<i v-if="field.required">*</i></span>
          <input v-model="createForm[field.key]" :placeholder="field.placeholder" />
        </label>
        <div class="modal-foot">
          <button class="btn ghost" type="button" @click="createOpen = false">取消</button>
          <button class="btn primary" type="button" @click="submitCreate">登记</button>
        </div>
      </div>
    </div>

    <!-- 登记付款（单张） -->
    <div v-if="payOpen" class="modal-mask" @click.self="payOpen = false">
      <div class="modal">
        <h3>登记付款 · {{ payRow?.['结算单号'] }}</h3>
        <p class="modal-tip">
          应结金额 {{ formatAmount(payRow?.['应结金额']) }} 元；已付金额必须与应结金额一致才能推进到已付清。
        </p>
        <label class="form-item">
          <span>本次已付金额（元）<i>*</i></span>
          <input v-model="payForm.已付金额" placeholder="请输入与应结金额一致的金额" />
        </label>
        <label class="form-item">
          <span>备注</span>
          <input v-model="payForm.remark" placeholder="付款流水、说明（可选）" />
        </label>
        <div class="modal-foot">
          <button class="btn ghost" type="button" @click="payOpen = false">取消</button>
          <button class="btn primary" type="button" @click="submitPay">确认付款</button>
        </div>
      </div>
    </div>

    <!-- 争议标记 / 恢复 的备注弹窗 -->
    <div v-if="noteOpen" class="modal-mask" @click.self="noteOpen = false">
      <div class="modal">
        <h3>{{ noteAction }} · {{ noteRow?.['结算单号'] }}</h3>
        <p class="modal-tip">
          {{ noteAction === '标记争议' ? '仅挂起本张结算单，同周期其他单不受影响；恢复后回到核对中。' : '争议处理完成后，本单回到核对中重新核对。' }}
        </p>
        <label class="form-item">
          <span>争议说明{{ noteAction === '标记争议' ? '（建议填写争议点）' : '（可选）' }}</span>
          <input v-model="noteForm.remark" :placeholder="noteAction === '标记争议' ? '如：上网电量口径待复核' : '处理结果说明'" />
        </label>
        <div class="modal-foot">
          <button class="btn ghost" type="button" @click="noteOpen = false">取消</button>
          <button class="btn primary" type="button" @click="submitNote">确认</button>
        </div>
      </div>
    </div>

    <!-- 同周期合并付款 -->
    <div v-if="mergeOpen" class="modal-mask" @click.self="mergeOpen = false">
      <div class="modal">
        <h3>同周期合并付款</h3>
        <label class="form-item">
          <span>结算周期<i>*</i></span>
          <input v-model="mergeForm.period" placeholder="如 2026-09" @change="loadMergePreview" />
        </label>
        <button class="btn" type="button" @click="loadMergePreview">预览该周期</button>
        <ul v-if="mergePreview" class="merge-groups">
          <li v-for="s in statuses" :key="s">
            <span class="status-tag" :class="statusClass(s)">{{ s }}</span>
            <em>{{ mergeGroups[s]?.length || 0 }} 张</em>
            <span v-if="mergeGroups[s]?.length" class="merge-codes">{{ mergeGroups[s].join('、') }}</span>
          </li>
        </ul>
        <p v-if="mergePreview" class="modal-tip">
          将对 {{ mergePreview['可合并单数'] }} 张「已确认」结算单整体推进，应结合计
          <strong>{{ formatAmount(mergePreview['应结合计']) }}</strong> 元；
          争议单只挂起自身、不参与本次付款。金额对不上整批不付款、各单保持原状态。
        </p>
        <label class="form-item">
          <span>合并付款总额（元）<i>*</i></span>
          <input v-model="mergeForm.amount" :placeholder="mergePreview ? `应填 ${mergePreview['应结合计']}` : '先预览应结合计'" />
        </label>
        <label class="form-item">
          <span>备注</span>
          <input v-model="mergeForm.remark" placeholder="付款批次、流水（可选）" />
        </label>
        <div class="modal-foot">
          <button class="btn ghost" type="button" @click="mergeOpen = false">取消</button>
          <button class="btn primary" type="button" @click="submitMerge">确认合并付款</button>
        </div>
      </div>
    </div>

    <!-- 详情抽屉：推进记录 -->
    <div v-if="detail" class="drawer-mask" @click.self="detail = null">
      <aside class="drawer">
        <header class="drawer-head">
          <h3>{{ detail['结算单号'] }} · 台账详情</h3>
          <button class="btn ghost" type="button" @click="detail = null">关闭</button>
        </header>
        <div class="detail-grid">
          <span>结算对象</span><strong>{{ detail['结算对象'] }}</strong>
          <span>结算周期</span><strong>{{ detail['结算周期'] }}</strong>
          <span>上网电量</span><strong>{{ detail['上网电量'] || '—' }}</strong>
          <span>电价标准</span><strong>{{ detail['电价标准'] || '—' }}</strong>
          <span>应结金额</span><strong>{{ formatAmount(detail['应结金额']) }} 元</strong>
          <span>已付金额</span><strong>{{ formatAmount(detail['已付金额']) }} 元</strong>
          <span>当前状态</span>
          <strong><span class="status-tag" :class="statusClass(detail['结算状态'])">{{ detail['结算状态'] }}</span></strong>
        </div>
        <h4 class="timeline-title">推进记录（操作人与时间）</h4>
        <ol class="timeline">
          <li v-for="rec in detail.records" :key="rec.seq">
            <div class="timeline-dot" />
            <div class="timeline-body">
              <div class="timeline-line">
                <strong>{{ rec.action }}</strong>
                <span>{{ rec.operator }}</span>
                <time>{{ rec.time }}</time>
              </div>
              <p v-if="rec.remark">{{ rec.remark }}</p>
            </div>
          </li>
        </ol>
      </aside>
    </div>
  </section>
</template>

<script setup lang="ts">
import { computed, onMounted, reactive, ref } from 'vue'

import { request } from '@/api/client'
import { useSessionStore } from '@/stores/session'

const ENDPOINT = '/api/settlement-ledger'
const session = useSessionStore()

type Row = Record<string, string | number | boolean | null>
type RecordItem = { seq: number; time: string; action: string; operator: string; remark: string }
type DetailRow = Row & { records: RecordItem[] }

const columns = ['结算单号', '结算对象', '结算周期', '应结金额', '已付金额', '结算状态']
const statuses = ['待核对', '核对中', '已确认', '已付清', '有争议']

const rows = ref<Row[]>([])
const total = ref(0)
const message = ref('')
const messageOk = ref(true)
const filters = reactive({ keyword: '', period: '', status: '' })
const stats = ref<{ total: number; by_status: Record<string, number>; 应结合计: number; 已付合计: number } | null>(null)

const statCards = computed(() => [
  { label: '台账总结算单', value: stats.value?.total ?? 0, warn: false },
  { label: '待核对', value: stats.value?.by_status['待核对'] ?? 0, warn: false },
  { label: '核对中', value: stats.value?.by_status['核对中'] ?? 0, warn: false },
  { label: '已确认待付款', value: stats.value?.by_status['已确认'] ?? 0, warn: false },
  { label: '已付清', value: stats.value?.by_status['已付清'] ?? 0, warn: false },
  { label: '争议挂起', value: stats.value?.by_status['有争议'] ?? 0, warn: true },
])

function allowedActions(status: string | number | boolean | null | undefined): string[] {
  switch (status) {
    case '待核对':
      return ['开始核对']
    case '核对中':
      return ['确认结算', '标记争议']
    case '已确认':
      return ['登记付款', '标记争议']
    case '有争议':
      return ['恢复争议']
    default:
      return [] // 已付清：终态，无任何可推进/回退动作
  }
}

function statusClass(status: unknown): string {
  return {
    待核对: 'st-init',
    核对中: 'st-checking',
    已确认: 'st-confirmed',
    已付清: 'st-paid',
    有争议: 'st-dispute',
  }[String(status)] ?? ''
}

function formatAmount(value: unknown): string {
  const num = Number(value)
  return Number.isFinite(num) ? num.toFixed(2) : '—'
}

function flash(text: string, ok = false) {
  message.value = text
  messageOk.value = ok
}

// ---------------------------------------------------------------- 列表
async function reload() {
  message.value = ''
  const query = new URLSearchParams()
  if (filters.keyword) query.set('keyword', filters.keyword)
  if (filters.period) query.set('period', filters.period)
  if (filters.status) query.set('status', filters.status)
  query.set('size', '200')
  try {
    const response = await request(`${ENDPOINT}?${query.toString()}`)
    if (!response.ok) throw new Error('台账列表读取失败')
    const payload = await response.json()
    rows.value = payload.items ?? []
    total.value = payload.total ?? rows.value.length
  } catch (error) {
    flash(error instanceof Error ? error.message : '台账列表读取失败')
  }
}

async function reloadStats() {
  try {
    const response = await request(`${ENDPOINT}/stats`)
    if (response.ok) stats.value = await response.json()
  } catch {
    // 统计加载失败不阻塞列表操作
  }
}

function resetFilters() {
  filters.keyword = ''
  filters.period = ''
  filters.status = ''
  void reload()
}

// ---------------------------------------------------------------- 详情
const detail = ref<DetailRow | null>(null)

async function openDetail(row: Row) {
  try {
    const response = await request(`${ENDPOINT}/${row.id}`)
    if (!response.ok) throw new Error('台账详情读取失败')
    detail.value = (await response.json()) as DetailRow
  } catch (error) {
    flash(error instanceof Error ? error.message : '台账详情读取失败')
  }
}

// ---------------------------------------------------------------- 动作
const payOpen = ref(false)
const payRow = ref<Row | null>(null)
const payForm = reactive({ 已付金额: '', remark: '' })

const noteOpen = ref(false)
const noteAction = ref('标记争议')
const noteRow = ref<Row | null>(null)
const noteForm = reactive({ remark: '' })

function runAction(action: string, row: Row) {
  if (action === '登记付款') {
    payRow.value = row
    payForm.已付金额 = String(row['应结金额'] ?? '')
    payForm.remark = ''
    payOpen.value = true
    return
  }
  if (action === '标记争议' || action === '恢复争议') {
    noteAction.value = action
    noteRow.value = row
    noteForm.remark = ''
    noteOpen.value = true
    return
  }
  void submitSimple(action, row)
}

async function submitSimple(action: string, row: Row) {
  const body = { values: { action, operator: session.operator } }
  const response = await request(`${ENDPOINT}/${row.id}/actions`, {
    method: 'POST',
    body: JSON.stringify(body),
  })
  await handleActionResult(response)
}

async function submitPay() {
  if (!payRow.value) return
  const response = await request(`${ENDPOINT}/${payRow.value.id}/actions`, {
    method: 'POST',
    body: JSON.stringify({
      values: {
        action: '登记付款',
        已付金额: payForm.已付金额,
        remark: payForm.remark,
        operator: session.operator,
      },
    }),
  })
  await handleActionResult(response, () => {
    payOpen.value = false
  })
}

async function submitNote() {
  if (!noteRow.value) return
  const response = await request(`${ENDPOINT}/${noteRow.value.id}/actions`, {
    method: 'POST',
    body: JSON.stringify({
      values: { action: noteAction.value, remark: noteForm.remark, operator: session.operator },
    }),
  })
  await handleActionResult(response, () => {
    noteOpen.value = false
  })
}

async function handleActionResult(response: Response, onSuccess?: () => void) {
  try {
    if (!response.ok) throw new Error('操作未生效，请稍后重试')
    const result = await response.json()
    if (!result.ok) {
      // 推进失败：后端保持原状态，页面原样提示原因
      flash(result.message || '操作未生效', false)
      return
    }
    flash(result.message || '状态已推进', true)
    onSuccess?.()
    await Promise.all([reload(), reloadStats()])
  } catch (error) {
    flash(error instanceof Error ? error.message : '操作请求失败')
  }
}

// ---------------------------------------------------------------- 登记
const createOpen = ref(false)
const createFields = [
  { key: '结算单号', label: '结算单号', required: true, placeholder: '如 SETT-202609-01' },
  { key: '结算对象', label: '结算对象', required: true, placeholder: '如 国网西北分公司' },
  { key: '结算周期', label: '结算周期', required: true, placeholder: '如 2026-09' },
  { key: '应结金额', label: '应结金额（元）', required: true, placeholder: '大于 0 的数字' },
  { key: '上网电量', label: '上网电量（kWh）', required: false, placeholder: '可选' },
  { key: '电价标准', label: '电价标准（元/kWh）', required: false, placeholder: '可选' },
] as const
const createForm = reactive<Record<string, string>>({})

function openCreate() {
  createFields.forEach((field) => {
    createForm[field.key] = ''
  })
  createOpen.value = true
}

async function submitCreate() {
  const response = await request(ENDPOINT, {
    method: 'POST',
    body: JSON.stringify({ values: { ...createForm, operator: session.operator } }),
  })
  try {
    const result = await response.json()
    if (!result.ok) {
      flash(result.message || '登记失败', false)
      return
    }
    flash(result.message, true)
    createOpen.value = false
    await Promise.all([reload(), reloadStats()])
  } catch {
    flash('登记请求失败')
  }
}

// ---------------------------------------------------------------- 合并付款
const mergeOpen = ref(false)
const mergeForm = reactive({ period: '', amount: '', remark: '' })
const mergePreview = ref<Record<string, unknown> | null>(null)
const mergeGroups = computed<Record<string, string[]>>(() =>
  (mergePreview.value?.['分组'] as Record<string, string[]>) ?? {}
)

function openMerge() {
  mergeForm.period = ''
  mergeForm.amount = ''
  mergeForm.remark = ''
  mergePreview.value = null
  mergeOpen.value = true
}

async function loadMergePreview() {
  mergePreview.value = null
  if (!mergeForm.period) return
  try {
    const response = await request(`${ENDPOINT}/merge/preview?period=${encodeURIComponent(mergeForm.period)}`)
    if (response.ok) {
      mergePreview.value = await response.json()
      mergeForm.amount = String(mergePreview.value?.['应结合计'] ?? '')
    }
  } catch {
    // 预览失败不影响直接提交（提交时后端还会整批校验）
  }
}

async function submitMerge() {
  const response = await request(`${ENDPOINT}/merge`, {
    method: 'POST',
    body: JSON.stringify({
      values: {
        结算周期: mergeForm.period,
        已付金额: mergeForm.amount,
        remark: mergeForm.remark,
        operator: session.operator,
      },
    }),
  })
  try {
    const result = await response.json()
    if (!result.ok) {
      flash(result.message || '合并付款未执行', false)
      return
    }
    flash(result.message, true)
    mergeOpen.value = false
    await Promise.all([reload(), reloadStats()])
  } catch {
    flash('合并付款请求失败')
  }
}

onMounted(() => {
  void reload()
  void reloadStats()
})
</script>

<style scoped>
.ledger-table td:nth-child(4),
.ledger-table td:nth-child(5) {
  text-align: right;
  font-variant-numeric: tabular-nums;
}
.warn {
  color: #b42318;
}
.ok-text {
  color: #067647;
}
.filter-item select,
.filter-item input {
  padding: 5px 8px;
  border: 1px solid var(--border);
  border-radius: 6px;
  font-size: 13px;
}
.status-tag {
  display: inline-block;
  padding: 2px 8px;
  border-radius: 10px;
  font-size: 12px;
  border: 1px solid transparent;
}
.st-init { background: #f2f4f7; color: #475467; border-color: #d0d5dd; }
.st-checking { background: #eff4ff; color: #1d4ed8; border-color: #bfdbfe; }
.st-confirmed { background: #fffaeb; color: #b54708; border-color: #fedf89; }
.st-paid { background: #ecfdf3; color: #067647; border-color: #abefc6; }
.st-dispute { background: #fef3f2; color: #b42318; border-color: #fda29b; }
.modal-mask,
.drawer-mask {
  position: fixed;
  inset: 0;
  background: rgba(16, 24, 40, 0.45);
  display: flex;
  align-items: center;
  justify-content: center;
  z-index: 50;
}
.modal {
  width: 480px;
  max-height: 86vh;
  overflow: auto;
  background: #fff;
  border-radius: 10px;
  padding: 18px 20px;
}
.modal h3 { margin: 0 0 6px; font-size: 15px; }
.modal-tip { color: var(--muted); font-size: 12px; margin: 0 0 12px; line-height: 1.6; }
.form-item { display: block; margin-bottom: 10px; font-size: 12px; color: var(--muted); }
.form-item i { color: #b42318; font-style: normal; margin-left: 2px; }
.form-item input {
  display: block;
  width: 100%;
  margin-top: 4px;
  padding: 6px 8px;
  border: 1px solid var(--border);
  border-radius: 6px;
  font-size: 13px;
  color: #1f2937;
}
.modal-foot { display: flex; justify-content: flex-end; gap: 8px; margin-top: 12px; }
.merge-groups { list-style: none; margin: 0 0 10px; padding: 10px; background: #f8fafc; border-radius: 8px; }
.merge-groups li { display: flex; align-items: center; gap: 8px; font-size: 12px; padding: 3px 0; }
.merge-groups em { font-style: normal; color: var(--muted); min-width: 44px; }
.merge-codes { color: var(--muted); }
.drawer-mask { justify-content: flex-end; }
.drawer {
  width: 460px;
  height: 100%;
  background: #fff;
  padding: 18px 20px;
  overflow: auto;
}
.drawer-head { display: flex; justify-content: space-between; align-items: center; }
.drawer-head h3 { font-size: 15px; margin: 0; }
.detail-grid {
  display: grid;
  grid-template-columns: 88px 1fr;
  gap: 8px 12px;
  margin: 14px 0;
  padding: 12px;
  background: #f8fafc;
  border-radius: 8px;
  font-size: 13px;
}
.detail-grid span { color: var(--muted); }
.timeline-title { font-size: 13px; margin: 16px 0 8px; }
.timeline { list-style: none; margin: 0; padding: 0 0 0 6px; }
.timeline li { position: relative; padding: 0 0 16px 18px; border-left: 2px solid #e4e7ec; }
.timeline-dot {
  position: absolute;
  left: -6px;
  top: 2px;
  width: 10px;
  height: 10px;
  border-radius: 50%;
  background: var(--brand);
}
.timeline-line { display: flex; gap: 8px; align-items: baseline; font-size: 13px; flex-wrap: wrap; }
.timeline-line span { color: var(--muted); font-size: 12px; }
.timeline-line time { color: #98a2b3; font-size: 12px; margin-left: auto; }
.timeline-body p { margin: 4px 0 0; font-size: 12px; color: var(--muted); line-height: 1.5; }
</style>
