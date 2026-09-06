<template>
  <UiCard padding="md" shadow="sm" class="diag-card">
    <div class="diag-card__head">
      <span class="diag-card__icon"><UiIcon name="Wrench" :size="18" /></span>
      <div>
        <h3>运行时操作<UiInfoTip text="重载类操作只重新读取配置并重建索引，不会清空会话记录。真正的危险操作是「清空上下文」：会同时删除该会话的消息存储、内存缓冲与纪元锚点，不可恢复。" /></h3>
        <p>重载配置、人格、聊天规则和 MCP，并执行一次轻量健康检查。</p>
      </div>
    </div>

    <div class="runtime-actions">
      <UiButton icon="Activity" :loading="healthLoading" @click="loadHealth(false)">健康检查</UiButton>
      <UiButton icon="ListTree" :loading="healthLoadingVerbose" @click="loadHealth(true)">详细健康</UiButton>
      <UiButton icon="Zap" :loading="probeLoading" @click="runProbe">探活 Provider</UiButton>
      <UiButton icon="RefreshCw" :loading="runtimeLoading === 'llm'" @click="runRuntimeAction('llm')">重载 LLM</UiButton>
      <UiButton icon="Network" :loading="runtimeLoading === 'mcp'" @click="runRuntimeAction('mcp')">重载 MCP</UiButton>
      <UiButton icon="Drama" :loading="runtimeLoading === 'personas'" @click="runRuntimeAction('personas')">重载人格</UiButton>
      <UiButton icon="ToggleLeft" :loading="runtimeLoading === 'rules'" @click="runRuntimeAction('rules')">重载规则</UiButton>
    </div>

    <div class="context-tools">
      <label class="inline-field">
        <span>Scope</span>
        <input v-model="contextScope" placeholder="群号或 private:USER_ID" />
      </label>
      <UiButton icon="Eraser" variant="danger" :disabled="!contextScope" :loading="runtimeLoading === 'clear'" @click="clearContext">清空上下文</UiButton>
      <label class="inline-field">
        <span>Message ID</span>
        <input v-model="contextMessageId" placeholder="OneBot message_id" />
      </label>
      <UiButton icon="Trash2" variant="danger" :disabled="!contextScope || !contextMessageId" :loading="runtimeLoading === 'delete-msg'" @click="deleteContextMessage">删除消息</UiButton>
    </div>

    <div v-if="runtimeError" class="error-block">{{ runtimeError }}</div>
    <pre v-if="healthText" class="health-block">{{ healthText }}</pre>
    <pre v-if="probeText" class="health-block">{{ probeText }}</pre>

    <div class="action-panel">
      <div class="action-panel__head">
        <h4>最近动作</h4>
        <UiButton size="sm" icon="RefreshCw" :loading="actionsLoading" @click="loadActions">刷新</UiButton>
      </div>
      <UiEmpty v-if="!actions.length" icon="Activity" title="暂无动作记录" />
      <div v-else class="action-list">
        <div v-for="item in actions" :key="item.id" class="action-item">
          <div class="action-main">
            <span class="mono">{{ actionLabel(item.action_type) }}</span>
            <UiTag size="sm" :variant="actionVariant(item.status)">{{ statusLabel(item.status) }}</UiTag>
            <span class="action-time">{{ formatActionTime(item.updated_at || item.created_at) }}</span>
          </div>
          <div v-if="item.error" class="action-error">{{ item.error }}</div>
          <pre v-else-if="item.result?.text" class="action-result">{{ item.result.text }}</pre>
          <pre v-else-if="item.result" class="action-result">{{ prettyJson(item.result) }}</pre>
        </div>
      </div>
    </div>
  </UiCard>
</template>

<script setup lang="ts">
import { onMounted, ref } from 'vue'
import UiButton from '../ui/UiButton.vue'
import UiCard from '../ui/UiCard.vue'
import UiEmpty from '../ui/UiEmpty.vue'
import UiIcon from '../ui/UiIcon.vue'
import UiInfoTip from '../ui/UiInfoTip.vue'
import UiTag from '../ui/UiTag.vue'
import { probeProviders } from '../../api/diagnostics'
import { clearLlmContext, deleteLlmContextMessage, fetchLlmHealth, fetchLlmRuntimeActions, reloadLlmRuntime, reloadMcpRuntime, reloadPersonas, reloadRules } from '../../api/llmRuntime'
import type { RuntimeAction, RuntimeActionResponse } from '../../api/llmRuntime'
import { toast } from '../../toast'

const healthLoading = ref(false)
const healthLoadingVerbose = ref(false)
const healthText = ref('')
const probeLoading = ref(false)
const probeText = ref('')
const runtimeError = ref<string | null>(null)

type RuntimeActionKind = 'llm' | 'mcp' | 'personas' | 'rules'
type RuntimeLoading = RuntimeActionKind | 'clear' | 'delete-msg' | ''

const runtimeLoading = ref<RuntimeLoading>('')
const contextScope = ref('')
const contextMessageId = ref('')
const actionsLoading = ref(false)
const actions = ref<RuntimeAction[]>([])

function prettyJson(obj: unknown): string {
  try {
    return JSON.stringify(obj, null, 2)
  } catch {
    return String(obj)
  }
}

function actionLabel(actionType: string): string {
  return ({
    llm_reload: '重载 LLM',
    mcp_reload: '重载 MCP',
    personas_reload: '重载人格',
    rules_reload: '重载规则',
    awakening_reload: '重载唤醒',
    clear_context: '清空上下文',
    delete_context_message: '删除上下文消息',
    health_check: '健康检查',
    summary_now: '立即总结',
    briefing_now: '立即播报',
  } as Record<string, string>)[actionType] || actionType
}

function statusLabel(status: string): string {
  return ({
    queued: '等待',
    running: '执行中',
    succeeded: '成功',
    failed: '失败',
  } as Record<string, string>)[status] || status
}

type TagVariant = 'info' | 'success' | 'warn' | 'danger'

function actionVariant(status: string): TagVariant {
  return ({
    queued: 'info',
    running: 'warn',
    succeeded: 'success',
    failed: 'danger',
  } as Record<string, TagVariant>)[status] || 'info'
}

function formatActionTime(raw: string): string {
  if (!raw) return ''
  const d = new Date(raw)
  if (Number.isNaN(d.getTime())) return raw
  const pad = (n: number) => String(n).padStart(2, '0')
  return `${d.getFullYear()}-${pad(d.getMonth() + 1)}-${pad(d.getDate())} ${pad(d.getHours())}:${pad(d.getMinutes())}:${pad(d.getSeconds())}`
}

async function loadActions() {
  actionsLoading.value = true
  try {
    const data = await fetchLlmRuntimeActions(20)
    actions.value = data.actions || []
  } catch (e: unknown) {
    runtimeError.value = (e as Error).message
  } finally {
    actionsLoading.value = false
  }
}

async function loadHealth(verbose: boolean) {
  if (verbose) healthLoadingVerbose.value = true
  else healthLoading.value = true
  runtimeError.value = null
  try {
    const data = await fetchLlmHealth(verbose)
    if (data?.queued) {
      healthText.value = '健康检查已入队，请稍后查看最近动作。'
      await loadActions()
      toast('健康检查已入队')
    } else {
      healthText.value = data.text || ''
    }
  } catch (e: unknown) {
    runtimeError.value = (e as Error).message
  } finally {
    healthLoading.value = false
    healthLoadingVerbose.value = false
  }
}

async function runProbe() {
  probeLoading.value = true
  runtimeError.value = null
  try {
    const data = await probeProviders()
    probeText.value = data?.text || '没有已配置的 provider。'
  } catch (e: unknown) {
    runtimeError.value = (e as Error).message
  } finally {
    probeLoading.value = false
  }
}

async function runRuntimeAction(action: RuntimeActionKind) {
  runtimeLoading.value = action
  runtimeError.value = null
  try {
    let data: RuntimeActionResponse
    if (action === 'llm') data = await reloadLlmRuntime()
    else if (action === 'mcp') data = await reloadMcpRuntime()
    else if (action === 'personas') data = await reloadPersonas()
    else data = await reloadRules()
    if (data?.load_error || data?.error) {
      runtimeError.value = data.load_error || data.error
      toast('操作完成但存在错误', 'error')
    } else {
      toast(data?.queued ? '操作已入队' : '操作已完成')
    }
    if (data?.queued) await loadActions()
    if (data?.status) healthText.value = data.status
    if (data?.summary) healthText.value = JSON.stringify(data.summary, null, 2)
  } catch (e: unknown) {
    runtimeError.value = (e as Error).message
    toast('操作失败', 'error')
  } finally {
    runtimeLoading.value = ''
  }
}

async function clearContext() {
  if (!contextScope.value.trim()) return
  if (!confirm(`清空 ${contextScope.value.trim()} 的 LLM 短期上下文？`)) return
  runtimeLoading.value = 'clear'
  runtimeError.value = null
  try {
    const data = await clearLlmContext(contextScope.value.trim())
    toast(data?.queued ? '清空上下文已入队' : `已删除 ${data.deleted || 0} 条`)
    if (data?.queued) await loadActions()
  } catch (e: unknown) {
    runtimeError.value = (e as Error).message
    toast('清空失败', 'error')
  } finally {
    runtimeLoading.value = ''
  }
}

async function deleteContextMessage() {
  const scope = contextScope.value.trim()
  const messageId = contextMessageId.value.trim()
  if (!scope || !messageId) return
  runtimeLoading.value = 'delete-msg'
  runtimeError.value = null
  try {
    const data = await deleteLlmContextMessage(scope, messageId)
    toast(data?.queued ? '删除消息已入队' : (data.deleted ? '已删除消息' : '未找到消息'))
    if (data?.queued) await loadActions()
  } catch (e: unknown) {
    runtimeError.value = (e as Error).message
    toast('删除失败', 'error')
  } finally {
    runtimeLoading.value = ''
  }
}

onMounted(() => {
  loadActions()
})
</script>

<style scoped>
.diag-card {
  display: flex;
  min-width: 0;
  flex-direction: column;
  gap: var(--qq-gap-md);
  background: linear-gradient(180deg, var(--qq-surface), var(--qq-surface-elevated));
}

.diag-card__head {
  display: grid;
  grid-template-columns: 38px minmax(0, 1fr);
  gap: var(--qq-gap-sm);
  align-items: center;
}

.diag-card__icon {
  width: 38px;
  height: 38px;
  display: grid;
  place-items: center;
  border-radius: var(--qq-radius-sm);
  background: var(--qq-primary-soft);
  color: var(--qq-primary);
}

.diag-card__head h3 {
  display: inline-flex;
  align-items: center;
  gap: 4px;
  margin: 0 0 2px;
  color: var(--qq-text);
  font-size: var(--qq-text-base);
  line-height: 1.3;
}

.diag-card__head p {
  margin: 0;
  color: var(--qq-text-muted);
  font-size: var(--qq-text-xs);
  line-height: 1.5;
}

.runtime-actions,
.context-tools {
  display: flex;
  align-items: center;
  gap: var(--qq-gap-sm);
  flex-wrap: wrap;
}

.action-panel {
  display: flex;
  flex-direction: column;
  gap: var(--qq-gap-sm);
  border-top: 1px solid var(--qq-border);
  padding-top: var(--qq-gap-sm);
}

.action-panel__head,
.action-main {
  display: flex;
  align-items: center;
  gap: var(--qq-gap-sm);
  flex-wrap: wrap;
}

.action-panel__head {
  justify-content: space-between;
}

.action-panel__head h4 {
  margin: 0;
  color: var(--qq-text);
  font-size: var(--qq-text-sm);
}

.action-list {
  display: flex;
  flex-direction: column;
  gap: var(--qq-gap-xs);
}

.action-item {
  padding: var(--qq-gap-xs) var(--qq-gap-sm);
  border: 1px solid var(--qq-border);
  border-radius: var(--qq-radius-sm);
  background: var(--qq-surface-strong);
}

.action-main {
  justify-content: space-between;
}

.action-time,
.mono {
  color: var(--qq-text-muted);
  font-family: var(--qq-font-mono);
  font-size: var(--qq-text-xs);
}

.action-error {
  margin-top: 4px;
  color: var(--qq-danger);
  font-size: var(--qq-text-xs);
  word-break: break-word;
}

.action-result {
  margin: 4px 0 0;
  color: var(--qq-text-muted);
  font-family: var(--qq-font-mono);
  font-size: var(--qq-text-xs);
  white-space: pre-wrap;
  word-break: break-word;
}

.inline-field {
  display: inline-flex;
  align-items: center;
  gap: 6px;
  color: var(--qq-text-muted);
  font-size: var(--qq-text-xs);
}

.inline-field input {
  width: 190px;
}

.error-block {
  padding: var(--qq-gap-sm);
  background: var(--qq-danger-soft);
  border: 1px solid var(--qq-danger-border);
  border-radius: var(--qq-radius-sm);
  color: var(--qq-danger);
  font-size: var(--qq-text-sm);
}

.health-block {
  margin: 0;
  padding: var(--qq-gap-sm);
  color: var(--qq-text);
  font-family: var(--qq-font-mono);
  font-size: var(--qq-text-xs);
  line-height: 1.55;
  white-space: pre-wrap;
  word-break: break-word;
  border: 1px solid var(--qq-border);
  border-radius: var(--qq-radius-sm);
  background: var(--qq-surface-strong);
}

@media (max-width: 640px) {
  .diag-card__head {
    grid-template-columns: 32px minmax(0, 1fr);
  }

  .diag-card__icon {
    width: 32px;
    height: 32px;
  }
}
</style>
