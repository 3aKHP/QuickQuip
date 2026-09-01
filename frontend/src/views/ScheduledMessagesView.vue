<template>
  <div>
    <UiPageHeader title="定时消息" subtitle="到点自动向群发送文本消息，cron 为服务器本地时间">
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
        <label class="field"><span>cron（分 时 日 月 周）</span><input v-model="form.cron" placeholder="0 7 * * *" class="mono-input" /></label>
        <label class="field"><span>群号（逗号分隔）</span><input v-model="form.groupIds" placeholder="10001, 10002" class="mono-input" /></label>
        <label class="field"><span>类型</span>
          <select v-model="form.kind">
            <option value="text">固定文案</option>
            <option value="llm">LLM 任务</option>
          </select>
        </label>
        <label class="field"><span>{{ form.kind === 'llm' ? '任务指令（prompt）' : '消息内容' }}</span><textarea v-model="form.message" rows="4" maxlength="500" :placeholder="form.kind === 'llm' ? '到点交给 LLM 执行的任务指令' : '到点要发送的文本'" /></label>
        <label class="field field--row"><span>一次性任务<em v-if="!form.recurring" class="hint">触发一次后自动删除</em></span><UiToggle :model-value="!form.recurring" @update:model-value="form.recurring = !$event" /></label>
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
import { onMounted, ref } from 'vue'
import UiPageHeader from '../components/ui/UiPageHeader.vue'; import UiButton from '../components/ui/UiButton.vue'
import UiCard from '../components/ui/UiCard.vue'; import UiTag from '../components/ui/UiTag.vue'
import UiToggle from '../components/ui/UiToggle.vue'; import UiEmpty from '../components/ui/UiEmpty.vue'
import UiSkeleton from '../components/ui/UiSkeleton.vue'
import { fetchScheduledMessages, createScheduledMessage, updateScheduledMessage, deleteScheduledMessage, type ScheduledMessageJob } from '../api/scheduledMessages'
import { toast } from '../toast'

const jobs = ref<ScheduledMessageJob[]>([]); const loading = ref(false); const loadError = ref<string | null>(null)
const editing = ref(false); const editingId = ref<string | null>(null); const saving = ref(false); const saveError = ref<string | null>(null)
const form = ref({ cron: '', groupIds: '', message: '', enabled: true, kind: 'text' as 'text' | 'llm', recurring: true })

function formatTime(iso: string): string { if (!iso) return '—'; try { const d = new Date(iso); const pad = (n: number) => String(n).padStart(2, '0'); return `${d.getFullYear()}-${pad(d.getMonth() + 1)}-${pad(d.getDate())} ${pad(d.getHours())}:${pad(d.getMinutes())}` } catch { return iso } }
function originLabel(origin: string): string { return { command: '命令', llm: 'LLM', web: 'Web' }[origin] || origin }

async function loadJobs() { loading.value = true; loadError.value = null; try { const d = await fetchScheduledMessages(); jobs.value = d.jobs || [] } catch (e: unknown) { loadError.value = (e as Error).message } finally { loading.value = false } }

function startCreate() { editingId.value = null; form.value = { cron: '', groupIds: '', message: '', enabled: true, kind: 'text', recurring: true }; saveError.value = null; editing.value = true }
function startEdit(job: ScheduledMessageJob) { editingId.value = job.id; form.value = { cron: job.cron, groupIds: job.group_ids.join(', '), message: job.message, enabled: job.enabled, kind: job.kind, recurring: job.recurring }; saveError.value = null; editing.value = true }
function cancelEdit() { editing.value = false; editingId.value = null }

function parseGroupIds(raw: string): string[] | null { const ids = raw.split(/[,，]/).map(s => s.trim()).filter(Boolean); if (!ids.length || ids.some(g => !/^\d+$/.test(g))) return null; return [...new Set(ids)] }

async function onSave() {
  const groupIds = parseGroupIds(form.value.groupIds)
  if (!form.value.cron.trim()) { saveError.value = '请填写 cron 表达式'; return }
  if (!groupIds) { saveError.value = '群号格式不正确（逗号分隔的全数字群号）'; return }
  if (!form.value.message.trim()) { saveError.value = '消息内容不能为空'; return }
  saving.value = true; saveError.value = null
  try {
    if (editingId.value) {
      await updateScheduledMessage(editingId.value, { cron: form.value.cron.trim(), group_ids: groupIds, message: form.value.message.trim(), enabled: form.value.enabled, kind: form.value.kind, recurring: form.value.recurring })
      toast('已保存')
    } else {
      await createScheduledMessage({ cron: form.value.cron.trim(), group_ids: groupIds, message: form.value.message.trim(), enabled: form.value.enabled, kind: form.value.kind, recurring: form.value.recurring })
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
.hint { font-style: normal; font-size: var(--qq-text-xs); color: var(--qq-text-muted); margin-left: var(--qq-gap-xs); }
.mono-input { font-family: var(--qq-font-mono); }
.field textarea { resize: vertical; }
.modal-actions { display: flex; justify-content: flex-end; gap: var(--qq-gap-sm); }
</style>
