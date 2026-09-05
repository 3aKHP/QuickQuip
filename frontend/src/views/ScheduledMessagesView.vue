<template>
  <div>
    <UiPageHeader title="定时消息" subtitle="到点自动向群发送内容，cron 按北京时间（Asia/Shanghai）触发">
      <template #actions>
        <UiButton icon="RefreshCw" :disabled="loading" @click="loadJobs">刷新</UiButton>
        <UiButton variant="primary" icon="Plus" @click="startCreate">新建</UiButton>
      </template>
    </UiPageHeader>
    <p v-if="loadError" class="error">{{ loadError }}</p>
    <UiSkeleton v-if="loading && !jobs.length" variant="table" :rows="5" />
    <UiEmpty v-else-if="!jobs.length" icon="AlarmClock" title="暂无定时消息" />
    <UiCard v-else padding="none" shadow="sm">
      <div class="table-scroll">
        <table class="job-table">
          <thead><tr><th>ID</th><th>cron</th><th>群号</th><th>类型</th><th>启用</th><th>来源</th><th>消息</th><th>更新时间</th><th>操作</th></tr></thead>
          <tbody>
            <tr v-for="job in jobs" :key="job.id">
              <td class="mono">{{ job.id }}</td>
              <td class="mono">{{ job.cron }}</td>
              <td class="mono">{{ job.group_ids.join(', ') }}</td>
              <td class="kind-cell">
                <UiTag size="sm" :variant="job.kind === 'llm' ? 'cyan' : 'info'">{{ job.kind === 'llm' ? 'LLM 任务' : '固定文案' }}</UiTag>
                <UiTag v-if="!job.recurring" size="sm" variant="warn">一次性</UiTag>
              </td>
              <td><UiToggle :model-value="job.enabled" @update:model-value="toggleEnabled(job, $event)" /></td>
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

    <div v-if="editing" class="modal-mask" @click.self="cancelEdit">
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
            <span>触发日期时间（北京时间）<em class="hint">到点触发一次后自动删除；必须选择未来的时间</em></span>
            <div class="once-row">
              <input v-model="onceDate" type="date" aria-label="触发日期（北京时间）" />
              <input v-model="onceTime" type="time" aria-label="触发时间（北京时间）" />
            </div>
          </label>
          <template v-else>
            <label class="field"><span>触发时间（北京时间）</span><input v-model="simple.time" type="time" /></label>
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
        <label class="field"><span>{{ form.kind === 'llm' ? '任务指令（prompt）' : '消息内容' }}</span><textarea v-model="form.message" rows="4" maxlength="500" :placeholder="form.kind === 'llm' ? '到点交给 LLM 执行的任务指令' : '到点要发送的文本'" /></label>
        <label v-if="!isOnce" class="field field--row">
          <span>一次性任务<em class="hint">勾选：触发一次后自动删除；不勾选：按 cron 周期重复（若钉死月/日，即每年当天重复）</em></span>
          <UiToggle :model-value="!form.recurring" @update:model-value="form.recurring = !$event" />
        </label>
        <label class="field field--row"><span>启用</span><UiToggle v-model="form.enabled" /></label>
        <p v-if="saveError" class="error">{{ saveError }}</p>
        <div class="modal-actions">
          <UiButton :disabled="saving" @click="cancelEdit">取消</UiButton>
          <UiButton variant="primary" icon="Save" :loading="saving" @click="onSave">{{ editingId ? '保存' : '创建' }}</UiButton>
        </div>
      </UiCard>
    </div>
  </div>
</template>

<script setup lang="ts">
import { computed, onMounted, ref, watch } from 'vue'
import UiPageHeader from '../components/ui/UiPageHeader.vue'; import UiButton from '../components/ui/UiButton.vue'
import UiCard from '../components/ui/UiCard.vue'; import UiTag from '../components/ui/UiTag.vue'
import UiToggle from '../components/ui/UiToggle.vue'; import UiEmpty from '../components/ui/UiEmpty.vue'
import UiSkeleton from '../components/ui/UiSkeleton.vue'; import UiSegmented from '../components/ui/UiSegmented.vue'
import { fetchScheduledMessages, createScheduledMessage, updateScheduledMessage, deleteScheduledMessage, type ScheduledMessageJob, type ScheduledMessagePatch } from '../api/scheduledMessages'
import { fetchKnownGroups } from '../api/groups'
import { assembleCron, parseCronToSimple, onceAtInFuture, DEFAULT_SIMPLE_FIELDS, WEEKDAY_NAMES, type SimpleFields } from '../lib/scheduledCron'
import { toast } from '../toast'

type FormMode = 'simple' | 'advanced'

const jobs = ref<ScheduledMessageJob[]>([]); const loading = ref(false); const loadError = ref<string | null>(null)
const editing = ref(false); const editingId = ref<string | null>(null); const saving = ref(false); const saveError = ref<string | null>(null)
const form = ref({ cron: '', message: '', enabled: true, kind: 'text' as 'text' | 'llm', recurring: true })
const mode = ref<FormMode>('simple')
const simple = ref<SimpleFields>({ ...DEFAULT_SIMPLE_FIELDS })
const knownGroups = ref<string[]>([]); const selectedGroups = ref<string[]>([]); const extraGroupIds = ref('')
// 编辑时记录的原始值：保存补丁只携带实际变动的 cron/recurring，
// 让存量过期一次性任务的"只改文案"不被后端未来时间校验阻塞。
const originalCron = ref(''); const originalRecurring = ref(true)

const modeOptions: { value: FormMode; label: string }[] = [{ value: 'simple', label: '简易模式' }, { value: 'advanced', label: '高级模式' }]
const weekdayNames = WEEKDAY_NAMES
const isOnce = computed(() => mode.value === 'simple' && simple.value.frequency === 'once')
// 「仅一次」触发时间拆为日期+时间两个原生选择器（#198）：datetime-local 在中文
// 环境的空值占位符是「yyyy/mm/日 --:--」混合格式。simple.onceAt 契约不变——
// 恒为 '' 或完整 "YYYY-MM-DDTHH:MM"，部分填写归一为空，交给「请选择」校验兜底。
// 不用裸 computed 拆装：先选时间再选日期时 setter 互踩会丢已选部分。
const onceDate = ref(''); const onceTime = ref('')
watch([onceDate, onceTime], ([d, t]) => {
  const composed = d && t ? `${d}T${t}` : ''
  if (composed !== simple.value.onceAt) simple.value.onceAt = composed
})
watch(() => simple.value.onceAt, (v) => {
  const [d = '', t = ''] = v.split('T')
  if (d !== onceDate.value || t !== onceTime.value) { onceDate.value = d; onceTime.value = t }
})
// 候选群 = 已知群 ∪ 当前已选群（编辑存量任务时其群可能不在已知列表里）
const groupOptions = computed(() => [...new Set([...knownGroups.value, ...selectedGroups.value])])

const pad = (n: number) => String(n).padStart(2, '0')

function formatTime(iso: string): string { if (!iso) return '—'; try { const d = new Date(iso); return `${d.getFullYear()}-${pad(d.getMonth() + 1)}-${pad(d.getDate())} ${pad(d.getHours())}:${pad(d.getMinutes())}` } catch { return iso } }
function originLabel(origin: string): string { return { command: '命令', llm: 'LLM', web: 'Web' }[origin] || origin }

async function loadJobs() { loading.value = true; loadError.value = null; try { const d = await fetchScheduledMessages(); jobs.value = d.jobs || [] } catch (e: unknown) { loadError.value = (e as Error).message } finally { loading.value = false } }
async function loadKnownGroups() { try { const d = await fetchKnownGroups(); knownGroups.value = d.groups || [] } catch { knownGroups.value = [] } }

/** 两种模式互相切换且内容不丢：简易→高级组装 cron；高级→简易尝试解析，失败则留在高级模式。 */
function switchMode(next: FormMode) {
  if (next === mode.value) return
  saveError.value = null
  if (next === 'advanced') {
    const assembled = assembleCron(simple.value)
    if (assembled !== null) form.value.cron = assembled  // 选择器未填完整时保留现状
  } else {
    const parsed = parseCronToSimple(form.value.cron, form.value.recurring)
    if (!parsed) {
      toast('当前 cron（或"每年重复"语义）无法用简易模式表达，已保留在高级模式', 'error')
      return
    }
    simple.value = parsed
  }
  mode.value = next
}

function startCreate() {
  editingId.value = null
  form.value = { cron: '', message: '', enabled: true, kind: 'text', recurring: true }
  simple.value = { ...DEFAULT_SIMPLE_FIELDS }
  // 半填态（只选了日期或时间）下 onceAt 维持 ''，重置的 ''→'' 不触发反向
  // watch——双 ref 必须显式清，否则废弃会话的半填值泄漏进下一个任务
  onceDate.value = ''; onceTime.value = ''
  selectedGroups.value = []; extraGroupIds.value = ''; mode.value = 'simple'
  saveError.value = null; editing.value = true
  loadKnownGroups()
}
function startEdit(job: ScheduledMessageJob) {
  editingId.value = job.id
  form.value = { cron: job.cron, message: job.message, enabled: job.enabled, kind: job.kind, recurring: job.recurring }
  originalCron.value = job.cron; originalRecurring.value = job.recurring
  const parsed = parseCronToSimple(job.cron, job.recurring)
  if (parsed) simple.value = parsed
  // 同 startCreate：daily/weekly/monthly 回填的 onceAt='' 不触发反向 watch
  onceDate.value = ''; onceTime.value = ''
  mode.value = parsed ? 'simple' : 'advanced'
  selectedGroups.value = [...job.group_ids]; extraGroupIds.value = ''
  saveError.value = null; editing.value = true
  loadKnownGroups()
}
function cancelEdit() { editing.value = false; editingId.value = null }

interface Payload { cron: string; groupIds: string[]; message: string; enabled: boolean; kind: 'text' | 'llm'; recurring: boolean }

/** 表单状态 → 提交负载的纯映射；校验失败返回 { error }。"仅一次"强制 recurring=false 的策略集中在此。 */
function buildPayload(): Payload | { error: string } {
  let cron: string | null
  if (mode.value === 'simple') {
    if (simple.value.frequency === 'once') {
      if (!simple.value.onceAt) return { error: '请选择一次性任务的触发日期时间' }
      if (!onceAtInFuture(simple.value.onceAt)) return { error: '一次性任务的触发时间必须在未来' }
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
  return { cron, groupIds, message, enabled: form.value.enabled, kind: form.value.kind, recurring: isOnce.value ? false : form.value.recurring }
}

async function onSave() {
  const r = buildPayload()
  if ('error' in r) { saveError.value = r.error; return }
  saving.value = true; saveError.value = null
  try {
    if (editingId.value) {
      // 未变动的 cron/recurring 不进补丁：避免存量过期一次性任务的无关编辑被未来时间校验误伤
      const patch: ScheduledMessagePatch = { group_ids: r.groupIds, message: r.message, enabled: r.enabled, kind: r.kind }
      if (r.cron !== originalCron.value) patch.cron = r.cron
      if (r.recurring !== originalRecurring.value) patch.recurring = r.recurring
      await updateScheduledMessage(editingId.value, patch)
      toast('已保存')
    } else {
      await createScheduledMessage({ cron: r.cron, group_ids: r.groupIds, message: r.message, enabled: r.enabled, kind: r.kind, recurring: r.recurring })
      toast('已创建')
    }
    cancelEdit(); await loadJobs()
  } catch (e: unknown) { saveError.value = (e as Error).message } finally { saving.value = false }
}

async function toggleEnabled(job: ScheduledMessageJob, enabled: boolean) { try { await updateScheduledMessage(job.id, { enabled }); job.enabled = enabled; toast(enabled ? '已启用' : '已禁用') } catch (e: unknown) { toast(`操作失败：${(e as Error).message}`, 'error') } }
async function onDelete(job: ScheduledMessageJob) { if (!confirm(`确定删除定时消息 ${job.id}？`)) return; try { await deleteScheduledMessage(job.id); toast('已删除'); await loadJobs() } catch (e: unknown) { toast((e as Error).message, 'error') } }

onMounted(loadJobs)
</script>

<style scoped>
.error { color: var(--qq-danger); font-size: var(--qq-text-sm); }
.job-table { background: var(--qq-surface); }
.mono { font-family: var(--qq-font-mono); font-size: 12px; color: var(--qq-text-muted); }
.msg-cell { max-width: 220px; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; font-size: var(--qq-text-sm); }
.kind-cell { display: flex; gap: var(--qq-gap-xs); align-items: center; }
.op-cell { display: flex; gap: var(--qq-gap-xs); }

.modal-mask { position: fixed; inset: 0; z-index: 100; background: rgba(0, 0, 0, 0.35); display: flex; align-items: center; justify-content: center; padding: var(--qq-gap-lg); }
.modal-card { width: 100%; max-width: 480px; display: flex; flex-direction: column; gap: var(--qq-gap-md); }
.modal-title { font-size: var(--qq-text-lg); font-weight: 600; color: var(--qq-text); }
.field { display: flex; flex-direction: column; gap: var(--qq-gap-xs); font-size: var(--qq-text-sm); color: var(--qq-text-muted); }
.field--row { flex-direction: row; align-items: center; justify-content: space-between; }
.once-row { display: flex; gap: var(--qq-gap-xs); }
.once-row input { flex: 1; }
.field input, .field textarea, .field select { background: var(--qq-surface-strong); color: var(--qq-text); border: 1px solid var(--qq-border); border-radius: var(--qq-radius-sm); padding: var(--qq-gap-xs) var(--qq-gap-sm); font-family: var(--qq-font-base); font-size: var(--qq-text-sm); outline: none; }
.field input:focus, .field textarea:focus, .field select:focus { border-color: var(--qq-primary); }
.field-label { font-size: var(--qq-text-sm); color: var(--qq-text-muted); }
.hint { font-style: normal; font-size: var(--qq-text-xs); color: var(--qq-text-muted); margin-left: var(--qq-gap-xs); }
.mono-input { font-family: var(--qq-font-mono); }
.field textarea { resize: vertical; }
.group-picker { display: flex; flex-wrap: wrap; gap: var(--qq-gap-xs); }
.group-chip { display: inline-flex; align-items: center; gap: var(--qq-gap-xs); padding: 2px var(--qq-gap-sm); border: 1px solid var(--qq-border); border-radius: var(--qq-radius-sm); background: var(--qq-surface-strong); cursor: pointer; }
.modal-actions { display: flex; justify-content: flex-end; gap: var(--qq-gap-sm); }
</style>
