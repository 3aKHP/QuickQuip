<template>
  <div>
    <UiPageHeader title="定时消息" subtitle="到点自动向群发送内容，按北京时间（Asia/Shanghai）触发">
      <template #actions>
        <select v-model="groupFilter" class="group-filter" aria-label="按群筛选" @change="loadJobs">
          <option value="">全部群</option>
          <option v-for="g in filterGroups" :key="g" :value="g">{{ g }}</option>
        </select>
        <UiButton icon="RefreshCw" :loading="loading" @click="loadJobs">刷新</UiButton>
        <UiButton variant="primary" icon="Plus" @click="startCreate">新建</UiButton>
      </template>
    </UiPageHeader>
    <p v-if="loadError" class="error">{{ loadError }}</p>
    <UiSkeleton v-if="loading && !jobs.length" variant="table" :rows="5" />
    <UiEmpty v-else-if="!jobs.length" icon="AlarmClock" title="暂无定时消息" />
    <UiCard v-else padding="none" shadow="sm">
      <div class="table-scroll">
        <table class="job-table">
          <thead><tr><th>ID</th><th>触发时间 / cron</th><th>群号</th><th>类型<UiInfoTip text="固定文案 = 到点原样发送；LLM 任务 = 到点把内容作为指令交给 LLM、生成结果再发群。该群 LLM 被关闭时，LLM 任务的当次触发会被跳过。" /></th><th>启用</th><th>来源<UiInfoTip text="任务的创建渠道：命令 = 群内 /schedule 命令；LLM = LLM 的 manage_scheduled_messages 工具（需在 LLM 配置 [tools] 启用）；Web = 本后台创建。" /></th><th>消息</th><th>更新时间</th><th>操作</th></tr></thead>
          <tbody>
            <tr v-for="job in jobs" :key="job.id">
              <td class="mono">{{ job.id }}</td>
              <td>
                <div class="sched-human">{{ describeSchedule(job.cron, job.recurring, job.run_at) }}</div>
                <div class="mono sched-raw">{{ job.run_at ? job.run_at.slice(0, 16).replace('T', ' ') : job.cron }}</div>
              </td>
              <td class="mono">{{ job.group_ids.join(', ') }}</td>
              <td class="kind-cell">
                <UiTag size="sm" :variant="job.kind === 'llm' ? 'cyan' : 'info'">{{ job.kind === 'llm' ? 'LLM 任务' : '固定文案' }}</UiTag>
                <template v-if="!job.recurring"><UiTag size="sm" variant="warn">一次性</UiTag><UiInfoTip text="一次性任务：首次触发成功后自动从列表删除。" /></template>
              </td>
              <td><UiToggle :model-value="job.enabled" :disabled="togglingIds.has(job.id)" :aria-label="`切换任务 ${job.id} 启用状态`" @update:model-value="toggleEnabled(job, $event)" /></td>
              <td><UiTag size="sm" :variant="job.origin === 'web' ? 'info' : 'accent'">{{ originLabel(job.origin) }}</UiTag></td>
              <td class="msg-cell" :title="job.message">{{ job.message }}</td>
              <td class="mono">{{ formatTime(job.updated_at) }}</td>
              <td class="op-cell">
                <UiButton size="sm" icon="Pencil" @click="startEdit(job)">编辑</UiButton>
                <UiButton size="sm" variant="danger" icon="Trash2" @click="onDelete(job)">删除</UiButton>
              </td>
            </tr>
          </tbody>
        </table>
      </div>
    </UiCard>

    <Teleport to="body">
      <Transition name="modal-fade">
        <div
          v-if="editing"
          class="modal-mask"
          role="dialog"
          aria-modal="true"
          :aria-label="editingId ? '编辑定时消息' : '新建定时消息'"
          @click.self="!saving && cancelEdit()"
        >
          <UiCard class="modal-card" padding="md" shadow="lg">
            <h2 class="modal-title">{{ editingId ? '编辑定时消息' : '新建定时消息' }}</h2>
            <div class="field">
              <span class="field-label">设置方式</span>
              <UiSegmented :model-value="mode" :options="modeOptions" aria-label="设置方式" @update:model-value="switchMode" />
            </div>

            <template v-if="mode === 'simple'">
              <label class="field"><span>频次</span>
                <select v-model="simple.frequency">
                  <option value="daily">每天</option>
                  <option value="weekly">每周</option>
                  <option value="monthly">每月</option>
                  <option value="once">仅一次</option>
                </select>
              </label>
              <label v-if="simple.frequency === 'once'" class="field">
                <span>触发日期时间（北京时间）<em class="hint">到点触发一次后自动删除；支持选择任意未来日期（含跨年）</em></span>
                <div class="once-row">
                  <UiDatePicker v-model="onceDate" mode="date" placeholder="选择日期" aria-label="触发日期（北京时间）" />
                  <UiDatePicker v-model="onceTime" mode="time" placeholder="选择时间" aria-label="触发时间（北京时间）" />
                </div>
              </label>
              <template v-else>
                <label class="field"><span>触发时间（北京时间）</span><UiDatePicker v-model="simple.time" mode="time" placeholder="选择时间" /></label>
                <label v-if="simple.frequency === 'weekly'" class="field"><span>星期</span>
                  <select v-model="simple.weekday">
                    <option v-for="(name, i) in weekdayNames" :key="i" :value="i">{{ name }}</option>
                  </select>
                </label>
                <label v-if="simple.frequency === 'monthly'" class="field">
                  <span>每月几号<em class="hint">当月没有该日期（如小月的 31 号）则当月跳过</em></span>
                  <select v-model="simple.dayOfMonth">
                    <option v-for="d in 31" :key="d" :value="d">{{ d }} 号</option>
                  </select>
                </label>
              </template>
            </template>
            <label v-else class="field">
              <span>cron（分 时 日 月 周）<em class="hint">按北京时间触发；周字段 0=周一 … 6=周日</em></span>
              <input v-model="form.cron" placeholder="0 7 * * *" class="mono-input" />
            </label>

            <div class="field">
              <span class="field-label">目标群</span>
              <div v-if="groupOptions.length" class="group-picker">
                <label v-for="g in groupOptions" :key="g" class="group-chip">
                  <input v-model="selectedGroups" type="checkbox" :value="g" /><span class="mono">{{ g }}</span>
                </label>
              </div>
              <p v-else class="hint">暂无可选群：bot 需要先在群里收到消息才会出现在列表中，可在下方手动填写。</p>
              <input v-model="extraGroupIds" placeholder="手动填写其他群号，逗号分隔（可选）" class="mono-input" />
            </div>

            <label class="field"><span>类型</span>
              <select v-model="form.kind">
                <option value="text">固定文案</option>
                <option value="llm">LLM 任务</option>
              </select>
            </label>
            <label class="field">
              <span class="field-head">
                <span>{{ form.kind === 'llm' ? '任务指令（prompt）' : '消息内容' }}</span>
                <span class="char-count">{{ form.message.length }} / 500</span>
              </span>
              <textarea v-model="form.message" rows="4" maxlength="500" :placeholder="form.kind === 'llm' ? '到点交给 LLM 执行的任务指令' : '到点要发送的文本'" />
            </label>
            <div v-if="!isOnce" class="field field--row">
              <span>一次性任务<em class="hint">开启：触发一次后自动删除；关闭：按 cron 周期重复（若钉死月/日，即每年当天重复）</em></span>
              <UiToggle :model-value="!form.recurring" aria-label="一次性任务" @update:model-value="form.recurring = !$event" />
            </div>
            <div class="field field--row"><span>启用</span><UiToggle v-model="form.enabled" aria-label="启用任务" /></div>
            <p v-if="saveError" class="error">{{ saveError }}</p>
            <div class="modal-actions">
              <UiButton :disabled="saving" @click="cancelEdit">取消</UiButton>
              <UiButton variant="primary" icon="Save" :loading="saving" @click="onSave">{{ editingId ? '保存' : '创建' }}</UiButton>
            </div>
          </UiCard>
        </div>
      </Transition>
    </Teleport>
  </div>
</template>

<script setup lang="ts">
import { computed, onBeforeUnmount, onMounted, reactive, ref, watch } from 'vue'
import UiPageHeader from '../components/ui/UiPageHeader.vue'; import UiButton from '../components/ui/UiButton.vue'
import UiCard from '../components/ui/UiCard.vue'; import UiTag from '../components/ui/UiTag.vue'
import UiToggle from '../components/ui/UiToggle.vue'; import UiEmpty from '../components/ui/UiEmpty.vue'
import UiSkeleton from '../components/ui/UiSkeleton.vue'; import UiSegmented from '../components/ui/UiSegmented.vue'
import UiDatePicker from '../components/ui/UiDatePicker.vue'; import UiInfoTip from '../components/ui/UiInfoTip.vue'
import { fetchScheduledMessages, createScheduledMessage, updateScheduledMessage, deleteScheduledMessage, type ScheduledMessageJob, type ScheduledMessagePatch } from '../api/scheduledMessages'
import { fetchKnownGroups } from '../api/groups'
import { assembleCron, describeSchedule, localInputToRunAt, parseCronToSimple, onceAtInFuture, DEFAULT_SIMPLE_FIELDS, WEEKDAY_NAMES, type SimpleFields } from '../lib/scheduledCron'
import { toast } from '../toast'

type FormMode = 'simple' | 'advanced'

const jobs = ref<ScheduledMessageJob[]>([]); const loading = ref(false); const loadError = ref<string | null>(null)
const groupFilter = ref('')
const togglingIds = reactive(new Set<string>())
const editing = ref(false); const editingId = ref<string | null>(null); const saving = ref(false); const saveError = ref<string | null>(null)
const form = ref({ cron: '', message: '', enabled: true, kind: 'text' as 'text' | 'llm', recurring: true })
const mode = ref<FormMode>('simple')
const simple = ref<SimpleFields>({ ...DEFAULT_SIMPLE_FIELDS })
const knownGroups = ref<string[]>([]); const selectedGroups = ref<string[]>([]); const extraGroupIds = ref('')
// 编辑时记录的原始值：保存补丁只携带实际变动的 cron/recurring/run_at，
// 让存量过期一次性任务的"只改文案"不被后端未来时间校验阻塞。
const originalCron = ref(''); const originalRecurring = ref(true); const originalRunAt = ref(''); const initialOnceAt = ref('')
let jobsSeq = 0

const modeOptions: { value: FormMode; label: string }[] = [{ value: 'simple', label: '简易模式' }, { value: 'advanced', label: '高级模式' }]
const weekdayNames = WEEKDAY_NAMES
const isOnce = computed(() => mode.value === 'simple' && simple.value.frequency === 'once')
const onceDate = ref(''); const onceTime = ref('')
watch([onceDate, onceTime], ([d, t]) => {
  const composed = d && t ? `${d}T${t}` : ''
  if (composed !== simple.value.onceAt) simple.value.onceAt = composed
})
watch(() => simple.value.onceAt, (v) => {
  const [d = '', t = ''] = v.split('T')
  if (d !== onceDate.value || t !== onceTime.value) { onceDate.value = d; onceTime.value = t }
})
const groupOptions = computed(() => [...new Set([...knownGroups.value, ...selectedGroups.value])])
const filterGroups = computed(() => {
  const fromJobs = jobs.value.flatMap(j => j.group_ids)
  return [...new Set([...knownGroups.value, ...fromJobs, ...(groupFilter.value ? [groupFilter.value] : [])])].sort()
})

const pad = (n: number) => String(n).padStart(2, '0')

function formatTime(iso: string): string {
  if (!iso) return '—'
  const d = new Date(iso)
  if (Number.isNaN(d.getTime())) return iso
  return `${d.getFullYear()}-${pad(d.getMonth() + 1)}-${pad(d.getDate())} ${pad(d.getHours())}:${pad(d.getMinutes())}`
}
function originLabel(origin: string): string { return { command: '命令', llm: 'LLM', web: 'Web' }[origin] || origin }

async function loadJobs() {
  const seq = ++jobsSeq
  loading.value = true; loadError.value = null
  try {
    const d = await fetchScheduledMessages(groupFilter.value || undefined)
    if (seq !== jobsSeq) return
    jobs.value = d.jobs || []
  } catch (e: unknown) {
    if (seq !== jobsSeq) return
    loadError.value = (e as Error).message
  } finally {
    if (seq === jobsSeq) loading.value = false
  }
}
async function loadKnownGroups() { try { const d = await fetchKnownGroups(); knownGroups.value = d.groups || [] } catch { knownGroups.value = [] } }

/** 两种模式互相切换且内容不丢：简易→高级组装 cron；高级→简易尝试解析，失败则留在高级模式。 */
function switchMode(next: FormMode) {
  if (next === mode.value) return
  saveError.value = null
  if (next === 'advanced') {
    const assembled = assembleCron(simple.value)
    if (assembled !== null) form.value.cron = assembled
    // 简易「仅一次」切到高级模式时保留一次性语义，避免悄悄变成每年重复
    if (isOnce.value) form.value.recurring = false
  } else {
    const trimmedCron = form.value.cron.trim()
    const preservedRunAt = !form.value.recurring
      ? (simple.value.frequency === 'once' && assembleCron(simple.value) === trimmedCron && simple.value.onceAt
          ? localInputToRunAt(simple.value.onceAt)
          : (trimmedCron === originalCron.value ? originalRunAt.value : ''))
      : ''
    const parsed = parseCronToSimple(form.value.cron, form.value.recurring, preservedRunAt || undefined)
    if (!parsed) {
      toast('当前 cron（或"每年重复"语义）无法用简易模式表达，已保留在高级模式', 'error')
      return
    }
    simple.value = parsed
    const [d = '', t = ''] = parsed.onceAt.split('T')
    onceDate.value = d; onceTime.value = t
  }
  mode.value = next
}

function startCreate() {
  editingId.value = null
  form.value = { cron: '', message: '', enabled: true, kind: 'text', recurring: true }
  simple.value = { ...DEFAULT_SIMPLE_FIELDS }
  originalCron.value = ''; originalRecurring.value = true; originalRunAt.value = ''; initialOnceAt.value = ''
  onceDate.value = ''; onceTime.value = ''
  selectedGroups.value = []; extraGroupIds.value = ''; mode.value = 'simple'
  saveError.value = null; editing.value = true
  loadKnownGroups()
}
function startEdit(job: ScheduledMessageJob) {
  editingId.value = job.id
  form.value = { cron: job.cron, message: job.message, enabled: job.enabled, kind: job.kind, recurring: job.recurring }
  originalCron.value = job.cron; originalRecurring.value = job.recurring; originalRunAt.value = job.run_at || ''
  const parsed = parseCronToSimple(job.cron, job.recurring, job.run_at)
  initialOnceAt.value = parsed?.onceAt ?? ''
  if (parsed) {
    simple.value = parsed
    const [d = '', t = ''] = parsed.onceAt.split('T')
    onceDate.value = d; onceTime.value = t
  } else {
    onceDate.value = ''; onceTime.value = ''
  }
  mode.value = parsed ? 'simple' : 'advanced'
  selectedGroups.value = [...job.group_ids]; extraGroupIds.value = ''
  saveError.value = null; editing.value = true
  loadKnownGroups()
}
function cancelEdit() { if (saving.value) return; editing.value = false; editingId.value = null }

function onKeydown(e: KeyboardEvent) {
  if (e.key === 'Escape' && editing.value && !saving.value) {
    e.preventDefault()
    cancelEdit()
  }
}

watch(editing, (open) => {
  if (open) window.addEventListener('keydown', onKeydown)
  else window.removeEventListener('keydown', onKeydown)
})

interface Payload { cron: string; groupIds: string[]; message: string; enabled: boolean; kind: 'text' | 'llm'; recurring: boolean; runAt: string }

/** 表单状态 → 提交负载的纯映射；校验失败返回 { error }。"仅一次"强制 recurring=false 并附带 run_at 支持跨年。 */
function buildPayload(): Payload | { error: string } {
  let cron: string | null
  let runAt = ''
  if (mode.value === 'simple') {
    if (simple.value.frequency === 'once') {
      if (!simple.value.onceAt) return { error: '请选择一次性任务的触发日期时间' }
      const unchangedOnce = Boolean(editingId.value)
        && !originalRecurring.value
        && simple.value.onceAt === initialOnceAt.value
        && assembleCron(simple.value) === originalCron.value
      if (!unchangedOnce && !onceAtInFuture(simple.value.onceAt)) {
        return { error: '一次性任务的触发时间必须在未来' }
      }
      runAt = unchangedOnce ? originalRunAt.value : localInputToRunAt(simple.value.onceAt)
    }
    cron = assembleCron(simple.value)
    if (cron === null) return { error: '请补全时间设置' }
  } else {
    cron = form.value.cron.trim()
    if (!cron) return { error: '请填写 cron 表达式' }
  }
  const extra = extraGroupIds.value.split(/[,，]/).map(s => s.trim()).filter(Boolean)
  if (extra.some(g => !/^\d+$/.test(g))) return { error: '手动填写的群号必须是全数字' }
  const groupIds = [...new Set([...selectedGroups.value, ...extra])]
  if (!groupIds.length) return { error: '请至少选择一个群' }
  const message = form.value.message.trim()
  if (!message) return { error: '消息内容不能为空' }
  const recurring = isOnce.value ? false : form.value.recurring
  return { cron, groupIds, message, enabled: form.value.enabled, kind: form.value.kind, recurring, runAt: recurring ? '' : runAt }
}

async function onSave() {
  const r = buildPayload()
  if ('error' in r) { saveError.value = r.error; return }
  saving.value = true; saveError.value = null
  try {
    if (editingId.value) {
      // 未变动的 cron/recurring/run_at 不进补丁：避免存量过期一次性任务的无关编辑被未来时间校验误伤
      const patch: ScheduledMessagePatch = { group_ids: r.groupIds, message: r.message, enabled: r.enabled, kind: r.kind }
      if (r.cron !== originalCron.value) patch.cron = r.cron
      if (r.recurring !== originalRecurring.value) patch.recurring = r.recurring
      if (r.runAt !== originalRunAt.value) patch.run_at = r.runAt
      await updateScheduledMessage(editingId.value, patch)
      toast('已保存')
    } else {
      const body: Parameters<typeof createScheduledMessage>[0] = {
        cron: r.cron, group_ids: r.groupIds, message: r.message,
        enabled: r.enabled, kind: r.kind, recurring: r.recurring,
      }
      if (r.runAt) body.run_at = r.runAt
      await createScheduledMessage(body)
      toast('已创建')
    }
    saving.value = false
    editing.value = false; editingId.value = null
    await loadJobs()
  } catch (e: unknown) { saveError.value = (e as Error).message } finally { saving.value = false }
}

async function toggleEnabled(job: ScheduledMessageJob, enabled: boolean) {
  if (togglingIds.has(job.id)) return
  togglingIds.add(job.id)
  try {
    await updateScheduledMessage(job.id, { enabled })
    job.enabled = enabled
    toast(enabled ? '已启用' : '已禁用')
  } catch (e: unknown) {
    toast(`操作失败：${(e as Error).message}`, 'error')
  } finally {
    togglingIds.delete(job.id)
  }
}
async function onDelete(job: ScheduledMessageJob) { if (!confirm(`确定删除定时消息 ${job.id}？`)) return; try { await deleteScheduledMessage(job.id); toast('已删除'); await loadJobs() } catch (e: unknown) { toast((e as Error).message, 'error') } }

onMounted(() => { loadJobs(); loadKnownGroups() })
onBeforeUnmount(() => { window.removeEventListener('keydown', onKeydown) })
</script>

<style scoped>
.error { color: var(--qq-danger); font-size: var(--qq-text-sm); }
.group-filter { min-width: 130px; font-size: var(--qq-text-sm); }
.job-table { background: var(--qq-surface); }
.mono { font-family: var(--qq-font-mono); font-size: 12px; color: var(--qq-text-muted); }
.sched-human { font-size: var(--qq-text-sm); color: var(--qq-text); font-weight: 500; white-space: nowrap; }
.sched-raw { font-size: 11px; color: var(--qq-text-quiet); }
.msg-cell { max-width: 220px; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; font-size: var(--qq-text-sm); }
.kind-cell { display: flex; gap: var(--qq-gap-xs); align-items: center; }
.op-cell { display: flex; gap: var(--qq-gap-xs); }

.modal-mask { position: fixed; inset: 0; z-index: var(--qq-z-modal); background: var(--qq-overlay-strong); display: flex; align-items: center; justify-content: center; padding: var(--qq-gap-lg); }
.modal-card { width: 100%; max-width: 500px; max-height: calc(100vh - 48px); overflow-y: auto; display: flex; flex-direction: column; gap: var(--qq-gap-md); }
.modal-title { font-size: var(--qq-text-lg); font-weight: 600; color: var(--qq-text); }
.field { display: flex; flex-direction: column; gap: var(--qq-gap-xs); font-size: var(--qq-text-sm); color: var(--qq-text-muted); }
.field-head { display: flex; align-items: center; justify-content: space-between; gap: var(--qq-gap-sm); }
.char-count { font-family: var(--qq-font-mono); font-size: var(--qq-text-xs); color: var(--qq-text-quiet); }
.field--row { flex-direction: row; align-items: center; justify-content: space-between; gap: var(--qq-gap-sm); }
.once-row { display: flex; gap: var(--qq-gap-xs); }
.once-row .ui-date-picker { flex: 1; min-width: 0; }
.field input:not([type="checkbox"]), .field textarea, .field select { background: var(--qq-surface-strong); color: var(--qq-text); border: 1px solid var(--qq-border); border-radius: var(--qq-radius-sm); padding: var(--qq-gap-xs) var(--qq-gap-sm); font-family: var(--qq-font-base); font-size: var(--qq-text-sm); outline: none; }
.field input:not([type="checkbox"]):focus, .field textarea:focus, .field select:focus { border-color: var(--qq-primary); }
.field-label { font-size: var(--qq-text-sm); color: var(--qq-text-muted); }
.hint { font-style: normal; font-size: var(--qq-text-xs); color: var(--qq-text-muted); margin-left: var(--qq-gap-xs); }
.mono-input { font-family: var(--qq-font-mono); }
.field textarea { resize: vertical; }
.group-picker { display: flex; flex-wrap: wrap; gap: var(--qq-gap-xs); max-height: 140px; overflow-y: auto; padding: 2px 0; }
.group-chip { display: inline-flex; align-items: center; gap: 6px; padding: 4px var(--qq-gap-sm); border: 1px solid var(--qq-border); border-radius: var(--qq-radius-sm); background: var(--qq-surface-strong); cursor: pointer; }
.modal-actions { display: flex; justify-content: flex-end; gap: var(--qq-gap-sm); }
</style>
