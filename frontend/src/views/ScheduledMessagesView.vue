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
            <span>触发日期时间<em class="hint">到点触发一次后自动删除；必须选择未来的时间</em></span>
            <input v-model="simple.onceAt" type="datetime-local" />
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
import { computed, onMounted, ref } from 'vue'
import UiPageHeader from '../components/ui/UiPageHeader.vue'; import UiButton from '../components/ui/UiButton.vue'
import UiCard from '../components/ui/UiCard.vue'; import UiTag from '../components/ui/UiTag.vue'
import UiToggle from '../components/ui/UiToggle.vue'; import UiEmpty from '../components/ui/UiEmpty.vue'
import UiSkeleton from '../components/ui/UiSkeleton.vue'; import UiSegmented from '../components/ui/UiSegmented.vue'
import { fetchScheduledMessages, createScheduledMessage, updateScheduledMessage, deleteScheduledMessage, type ScheduledMessageJob, type ScheduledMessagePatch } from '../api/scheduledMessages'
import { fetchKnownGroups } from '../api/groups'
import { toast } from '../toast'

type Frequency = 'daily' | 'weekly' | 'monthly' | 'once'
type FormMode = 'simple' | 'advanced'

const jobs = ref<ScheduledMessageJob[]>([]); const loading = ref(false); const loadError = ref<string | null>(null)
const editing = ref(false); const editingId = ref<string | null>(null); const saving = ref(false); const saveError = ref<string | null>(null)
const form = ref({ cron: '', message: '', enabled: true, kind: 'text' as 'text' | 'llm', recurring: true })
const mode = ref<FormMode>('simple')
const simple = ref({ frequency: 'daily' as Frequency, time: '08:00', weekday: 0, dayOfMonth: 1, onceAt: '' })
const knownGroups = ref<string[]>([]); const selectedGroups = ref<string[]>([]); const extraGroupIds = ref('')
// 编辑时记录的原始值：保存补丁只携带实际变动的 cron/recurring，
// 让存量过期一次性任务的"只改文案"不被后端未来时间校验阻塞。
const originalCron = ref(''); const originalRecurring = ref(true)

const modeOptions: { value: FormMode; label: string }[] = [{ value: 'simple', label: '简易模式' }, { value: 'advanced', label: '高级模式' }]
const weekdayNames = ['周一', '周二', '周三', '周四', '周五', '周六', '周日']
const isOnce = computed(() => mode.value === 'simple' && simple.value.frequency === 'once')
// 候选群 = 已知群 ∪ 当前已选群（编辑存量任务时其群可能不在已知列表里）
const groupOptions = computed(() => [...new Set([...knownGroups.value, ...selectedGroups.value])])

const pad = (n: number) => String(n).padStart(2, '0')

function formatTime(iso: string): string { if (!iso) return '—'; try { const d = new Date(iso); return `${d.getFullYear()}-${pad(d.getMonth() + 1)}-${pad(d.getDate())} ${pad(d.getHours())}:${pad(d.getMinutes())}` } catch { return iso } }
function originLabel(origin: string): string { return { command: '命令', llm: 'LLM', web: 'Web' }[origin] || origin }

async function loadJobs() { loading.value = true; loadError.value = null; try { const d = await fetchScheduledMessages(); jobs.value = d.jobs || [] } catch (e: unknown) { loadError.value = (e as Error).message } finally { loading.value = false } }
async function loadKnownGroups() { try { const d = await fetchKnownGroups(); knownGroups.value = d.groups || [] } catch { knownGroups.value = [] } }

/** 简易模式字段 → 5 段 cron。once 钉死 分/时/日/月，周字段恒为 *。
 *  选择器还没填完整（如仅一次未选日期）时返回当前 cron，避免组装出 NaN。 */
function assembleCron(): string {
  const s = simple.value
  if (s.frequency === 'once') {
    const dt = new Date(s.onceAt)
    if (Number.isNaN(dt.getTime())) return form.value.cron
    return `${dt.getMinutes()} ${dt.getHours()} ${dt.getDate()} ${dt.getMonth() + 1} *`
  }
  if (!s.time) return form.value.cron
  const [h, m] = s.time.split(':').map(Number)
  if (s.frequency === 'daily') return `${m} ${h} * * *`
  if (s.frequency === 'weekly') return `${m} ${h} * * ${s.weekday}`
  return `${m} ${h} ${s.dayOfMonth} * *`
}

/** 5 段 cron → 简易模式字段；无法用简易模式表达时返回 false。
 *  钉死月/日的 cron 只有在一次性（recurring=false）时才解析为"仅一次"；
 *  recurring=true 的同款 cron 是"每年重复"，简易模式表达不了，保持高级模式。 */
function parseCronToSimple(cron: string, recurring: boolean): boolean {
  const parts = cron.trim().split(/\s+/)
  if (parts.length !== 5) return false
  const [mi, h, d, mo, w] = parts
  const isInt = (v: string) => /^\d+$/.test(v)
  if (!isInt(mi) || !isInt(h)) return false
  const s = simple.value
  s.time = `${pad(Number(h))}:${pad(Number(mi))}`
  if (d === '*' && mo === '*' && w === '*') { s.frequency = 'daily'; return true }
  if (d === '*' && mo === '*' && isInt(w) && Number(w) <= 6) { s.frequency = 'weekly'; s.weekday = Number(w); return true }
  if (isInt(d) && mo === '*' && w === '*') { s.frequency = 'monthly'; s.dayOfMonth = Number(d); return true }
  if (isInt(d) && isInt(mo) && w === '*') {
    if (recurring) return false  // 钉死月/日的周期任务 = 每年重复，简易模式无此选项
    // cron 不含年份：默认填今年，今年已过则取明年
    s.frequency = 'once'
    const now = new Date()
    let year = now.getFullYear()
    if (new Date(year, Number(mo) - 1, Number(d), Number(h), Number(mi)) <= now) year += 1
    s.onceAt = `${year}-${pad(Number(mo))}-${pad(Number(d))}T${pad(Number(h))}:${pad(Number(mi))}`
    return true
  }
  return false
}

/** 两种模式互相切换且内容不丢：简易→高级组装 cron；高级→简易尝试解析，失败则留在高级模式。 */
function switchMode(next: FormMode) {
  if (next === mode.value) return
  saveError.value = null
  if (next === 'advanced') {
    form.value.cron = assembleCron()
  } else if (!parseCronToSimple(form.value.cron, form.value.recurring)) {
    toast('当前 cron（或"每年重复"语义）无法用简易模式表达，已保留在高级模式', 'error')
    return
  }
  mode.value = next
}

function startCreate() {
  editingId.value = null
  form.value = { cron: '', message: '', enabled: true, kind: 'text', recurring: true }
  simple.value = { frequency: 'daily', time: '08:00', weekday: 0, dayOfMonth: 1, onceAt: '' }
  selectedGroups.value = []; extraGroupIds.value = ''; mode.value = 'simple'
  saveError.value = null; editing.value = true
  loadKnownGroups()
}
function startEdit(job: ScheduledMessageJob) {
  editingId.value = job.id
  form.value = { cron: job.cron, message: job.message, enabled: job.enabled, kind: job.kind, recurring: job.recurring }
  originalCron.value = job.cron; originalRecurring.value = job.recurring
  mode.value = parseCronToSimple(job.cron, job.recurring) ? 'simple' : 'advanced'
  selectedGroups.value = [...job.group_ids]; extraGroupIds.value = ''
  saveError.value = null; editing.value = true
  loadKnownGroups()
}
function cancelEdit() { editing.value = false; editingId.value = null }

async function onSave() {
  let cron: string
  if (mode.value === 'simple') {
    if (simple.value.frequency === 'once') {
      if (!simple.value.onceAt) { saveError.value = '请选择一次性任务的触发日期时间'; return }
      if (new Date(simple.value.onceAt) <= new Date()) { saveError.value = '一次性任务的触发时间必须在未来'; return }
    }
    cron = assembleCron()
  } else {
    cron = form.value.cron.trim()
    if (!cron) { saveError.value = '请填写 cron 表达式'; return }
  }
  const extra = extraGroupIds.value.split(/[,，]/).map(s => s.trim()).filter(Boolean)
  if (extra.some(g => !/^\d+$/.test(g))) { saveError.value = '手动填写的群号必须是全数字'; return }
  const groupIds = [...new Set([...selectedGroups.value, ...extra])]
  if (!groupIds.length) { saveError.value = '请至少选择一个群'; return }
  if (!form.value.message.trim()) { saveError.value = '消息内容不能为空'; return }
  const recurring = isOnce.value ? false : form.value.recurring
  saving.value = true; saveError.value = null
  try {
    if (editingId.value) {
      // 未变动的 cron/recurring 不进补丁：避免存量过期一次性任务的无关编辑被未来时间校验误伤
      const patch: ScheduledMessagePatch = { group_ids: groupIds, message: form.value.message.trim(), enabled: form.value.enabled, kind: form.value.kind }
      if (cron !== originalCron.value) patch.cron = cron
      if (recurring !== originalRecurring.value) patch.recurring = recurring
      await updateScheduledMessage(editingId.value, patch)
      toast('已保存')
    } else {
      await createScheduledMessage({ cron, group_ids: groupIds, message: form.value.message.trim(), enabled: form.value.enabled, kind: form.value.kind, recurring })
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
