<template>
  <div class="publish-panel">
    <UiCard padding="lg">
      <h3 class="publish-panel__title">当前状态</h3>
      <div class="pipeline">
        <div class="pipeline__node">
          <span class="pipeline__label">草稿</span>
          <span class="pipeline__value">v{{ store.status.value?.draft_revision ?? '—' }}</span>
          <span class="pipeline__note" :class="{ warn: store.dirty.value }">{{ store.dirty.value ? '有未保存修改' : '与页面内容一致' }}</span>
        </div>
        <UiIcon name="ArrowRight" :size="16" class="pipeline__arrow" />
        <div class="pipeline__node">
          <span class="pipeline__label">已发布</span>
          <span class="pipeline__value">v{{ store.status.value?.published_revision ?? '—' }}</span>
          <span class="pipeline__note">{{ store.inSync.value ? '与草稿一致' : '落后于草稿' }}</span>
        </div>
        <UiIcon name="ArrowRight" :size="16" class="pipeline__arrow" />
        <div class="pipeline__node">
          <span class="pipeline__label">Bot 运行中</span>
          <span class="pipeline__value">{{ botLoaded }}</span>
          <span class="pipeline__note" :class="{ warn: botNoteWarn }">{{ botNote }}</span>
        </div>
      </div>
      <div v-if="componentChips.length" class="components-row">
        <span v-for="chip in componentChips" :key="chip.text" class="component-chip" :class="`component-chip--${chip.kind}`">{{ chip.text }}</span>
        <span v-if="store.bot.value?.observed_at" class="observed-at">观察于 {{ time(store.bot.value.observed_at) }}</span>
      </div>
      <div v-if="store.operation.value && !store.isOperationFinished(store.operation.value.status)" class="operation-active" role="status">
        <UiIcon name="Loader2" :size="15" class="spin" />
        <span>{{ OPERATION_KIND_LABELS[store.operation.value.kind] || '配置任务' }} · {{ stageLabel(store.operation.value.stage) }} · 目标版本 v{{ store.operation.value.target_revision }}</span>
        <UiButton v-if="store.operation.value.status === 'queued'" size="sm" @click="store.cancelOperation()">取消排队</UiButton>
      </div>
    </UiCard>

    <UiCard padding="lg">
      <div class="publish-panel__bar">
        <h3 class="publish-panel__title">草稿与运行版本的差异</h3>
        <UiButton size="sm" icon="GitCompareArrows" :disabled="store.busy.value" @click="store.loadDiff()">查看差异</UiButton>
      </div>
      <template v-if="store.diff.value">
        <p v-if="!store.diff.value.changes.length" class="muted">草稿与已发布版本内容一致。</p>
        <template v-else>
          <div v-if="impact.length" class="impact-row">
            <UiTag v-for="item in impact" :key="item" size="sm" variant="warn">{{ item }}</UiTag>
          </div>
          <div class="change-list">
            <details v-for="item in summarizedChanges" :key="item.raw.field_path" class="change-item">
              <summary>{{ item.summary.title }}<span v-if="item.summary.lines.length" class="change-item__count">{{ item.summary.lines.length }} 项</span></summary>
              <div class="change-item__body">
                <ul v-if="item.summary.lines.length" class="change-item__lines">
                  <li v-for="(line, i) in item.summary.lines" :key="i">{{ line }}</li>
                </ul>
                <div><span class="change-item__tag">已发布</span><code>{{ compact(item.raw.before) }}</code></div>
                <div><span class="change-item__tag change-item__tag--new">草稿</span><code>{{ compact(item.raw.after) }}</code></div>
                <details v-if="isTruncated(item.raw.before) || isTruncated(item.raw.after)" class="full-json">
                  <summary>查看完整 JSON</summary>
                  <pre>已发布：{{ fullJson(item.raw.before) }}

草稿：{{ fullJson(item.raw.after) }}</pre>
                </details>
              </div>
            </details>
          </div>
        </template>
      </template>
      <p class="muted apply-note">应用后由 Bot 编译并切换到新配置；进行中的任务继续使用旧配置直到完成。</p>
      <UiButton
        variant="primary"
        icon="Rocket"
        :loading="store.applying.value"
        :disabled="store.busy.value || store.dirty.value || store.conflict.value || store.activeOperation.value"
        @click="apply"
      >应用草稿到 Bot</UiButton>
      <p v-if="store.dirty.value" class="muted">先保存草稿，才能应用。</p>
    </UiCard>

    <UiCard padding="lg">
      <div class="publish-panel__bar">
        <h3 class="publish-panel__title">环境变量引用 <UiInfoTip text="配置中的密钥通过变量名引用，这里检查 Bot 环境里是否真的配置了这些变量。" /></h3>
        <UiButton size="sm" icon="RefreshCw" @click="store.loadEnvironment()">重新检查</UiButton>
      </div>
      <template v-if="store.environment.value">
        <p v-if="!store.environment.value.available" class="muted">Bot 尚未回报环境检查结果。</p>
        <p v-else-if="store.environment.value.stale" class="warn-text">Bot 环境检查已过期，结果仅供参考。</p>
        <div v-if="store.environment.value.variables.length" class="env-list">
          <span v-for="variable in store.environment.value.variables" :key="variable.name" class="env-pill" :class="pillClass(variable.configured)">
            <UiIcon :name="variable.configured === true ? 'Check' : variable.configured === false ? 'X' : 'CircleHelp'" :size="12" />
            {{ variable.name }}
          </span>
        </div>
        <p v-else class="muted">当前配置没有引用任何环境变量。</p>
      </template>
      <p v-else class="muted">点击「重新检查」获取 Bot 环境中的变量配置状态。</p>
    </UiCard>

    <UiCard padding="lg">
      <h3 class="publish-panel__title">历史快照</h3>
      <UiEmpty v-if="!store.history.value.length" icon="History" title="暂无历史快照" description="每次应用成功都会留下不可变快照" />
      <div v-for="snapshot in store.history.value" :key="snapshot.revision" class="history-row">
        <span class="history-row__label">v{{ snapshot.revision }}</span>
        <span class="history-row__time">{{ time(snapshot.created_at) }}</span>
        <UiButton size="sm" :disabled="store.busy.value || store.conflict.value" @click="restore(snapshot.revision)">恢复为草稿</UiButton>
      </div>
    </UiCard>

    <UiCard padding="lg">
      <div class="publish-panel__bar">
        <h3 class="publish-panel__title">最近任务</h3>
        <UiButton size="sm" icon="RefreshCw" @click="store.loadOperations()">刷新</UiButton>
      </div>
      <UiEmpty v-if="!store.recentOperations.value.length" icon="ListChecks" title="暂无任务记录" />
      <div v-for="item in store.recentOperations.value" :key="item.id" class="history-row">
        <UiTag size="sm" :variant="statusVariant(item.status)">{{ OPERATION_STATUS_LABELS[item.status] || item.status }}</UiTag>
        <span class="history-row__label">{{ OPERATION_KIND_LABELS[item.kind] || item.kind }} · v{{ item.target_revision }}</span>
        <span class="history-row__time">{{ time(item.created_at) }}</span>
        <UiButton size="sm" variant="ghost" @click="viewing = item">详情</UiButton>
      </div>
      <div v-if="detailOperation" class="operation-result">
        <h4>任务详情 <span v-if="isViewingHistory" class="operation-result__note">（历史任务，不影响当前监控）</span></h4>
        <p v-if="detailOperation.error" class="error-text">{{ errorText(detailOperation.error) }}</p>
        <pre v-if="detailOperation.result !== null && detailOperation.result !== undefined">{{ JSON.stringify(detailOperation.result, null, 2) }}</pre>
      </div>
    </UiCard>
  </div>
</template>

<script setup lang="ts">
import { computed, onMounted, shallowRef } from 'vue'
import UiButton from '../ui/UiButton.vue'
import UiCard from '../ui/UiCard.vue'
import UiEmpty from '../ui/UiEmpty.vue'
import UiIcon from '../ui/UiIcon.vue'
import UiInfoTip from '../ui/UiInfoTip.vue'
import UiTag from '../ui/UiTag.vue'
import { injectLlmConfigStore } from '../../composables/useLlmConfigStore'
import { toast } from '../../toast'
import { OPERATION_KIND_LABELS, OPERATION_STATUS_LABELS, PARAM_LABELS, SETTINGS_FIELD_LABELS, SETTINGS_SECTION_LABELS, ROUTE_LABELS, describeChange, isObject, type JsonValue } from '../../lib/llmConfig'
import type * as apiModule from '../../api/llmConfiguration'

const store = injectLlmConfigStore()

/** 用户在历史列表里点「详情」查看的任务：只读展示，不接管活动任务监控 */
const viewing = shallowRef<apiModule.ConfigOperation | null>(null)
const detailOperation = computed(() => {
  if (viewing.value) return viewing.value
  const monitored = store.operation.value
  return monitored && store.isOperationFinished(monitored.status) ? monitored : null
})
const isViewingHistory = computed(() => viewing.value !== null && viewing.value.id !== store.operation.value?.id)

const botLoaded = computed(() => {
  const bot = store.bot.value
  return bot ? `v${bot.loaded_revision}` : '未报告'
})
const botNote = computed(() => {
  if (!store.bot.value) return 'Bot 未连接或未开启心跳'
  return store.botStale.value ? '心跳过期，状态可能不准' : '心跳正常'
})
const botNoteWarn = computed(() => !store.bot.value || store.botStale.value)

/** Bot 回报的组件状态：核心、MCP 及各服务连接 */
const componentChips = computed(() => {
  const bot = store.bot.value
  if (!bot || !isObject(bot.components)) return []
  const chips: { text: string; kind: 'ok' | 'warn' | 'bad' }[] = []
  const components = bot.components
  if (isObject(components.core)) {
    chips.push({ text: components.core.state === 'failed' ? '核心配置加载失败' : '核心正常', kind: components.core.state === 'failed' ? 'bad' : 'ok' })
  }
  if (isObject(components.mcp)) {
    const mcp = components.mcp
    const state = String(mcp.state ?? '')
    chips.push({
      text: state === 'preparing' ? 'MCP 准备中' : state === 'degraded' ? 'MCP 部分不可用' : state === 'ready' ? 'MCP 正常' : 'MCP 状态未知',
      kind: state === 'ready' ? 'ok' : 'warn',
    })
    for (const server of Array.isArray(mcp.servers) ? mcp.servers : []) {
      if (!isObject(server)) continue
      if (server.connected === true) chips.push({ text: `${server.id} 已连接`, kind: 'ok' })
      else chips.push({ text: `${server.id} 连接失败${server.failure_code ? `（${server.failure_code}）` : ''}`, kind: 'bad' })
    }
  }
  return chips
})

const impact = computed(() => {
  const diff = store.diff.value
  if (!diff || !isObject(diff.components)) return []
  const result: string[] = []
  const components = diff.components as Record<string, JsonValue>
  if (components.mcp_reconnect === true) result.push('MCP 服务将重连')
  if (Array.isArray(components.reschedule) && components.reschedule.length) {
    result.push(`将重新调度：${components.reschedule.map(name => SETTINGS_SECTION_LABELS[String(name)] || String(name)).join('、')}`)
  }
  return result
})

/** 差异条目的人话摘要：数组段按身份整理增删改；无结构的回退到原始 JSON */
const summarizedChanges = computed(() => (store.diff.value?.changes ?? []).map(change => {
  const summary = describeChange(change.field_path, change.before, change.after)
  return { raw: change, summary: { ...summary, title: summary.lines.length ? summary.title : humanPath(change.field_path) } }
}))

function humanPath(path: string): string {
  if (path === 'providers') return '渠道（整段变更）'
  if (path === 'pricing') return '价格（整段变更）'
  if (path === 'style_profiles') return '回复风格（整段变更）'
  const settingsMatch = path.match(/^settings\.([a-z_]+)\.([a-z_]+)(?:\[\d+\])?$/)
  if (settingsMatch) {
    const [, section, field] = settingsMatch
    const sectionLabel = SETTINGS_SECTION_LABELS[section!] || section
    const fieldLabel = SETTINGS_FIELD_LABELS[section!]?.[field!]?.label || field
    return `${sectionLabel} · ${fieldLabel}`
  }
  const routeMatch = path.match(/^routes\.([a-z_]+)/)
  if (routeMatch) return `功能路由 · ${ROUTE_LABELS[routeMatch[1]!]?.label || routeMatch[1]}`
  const paramMatch = path.match(/parameters\.([a-z_]+)/)
  if (paramMatch) return `参数 · ${PARAM_LABELS[paramMatch[1]!]?.label || paramMatch[1]}`
  return path
}

const JSON_PREVIEW_LIMIT = 200

function compact(value: JsonValue): string {
  const text = typeof value === 'string' ? value : JSON.stringify(value)
  if (text === undefined) return '（空）'
  return text.length > JSON_PREVIEW_LIMIT ? `${text.slice(0, JSON_PREVIEW_LIMIT)}…` : text
}

function rawText(value: JsonValue): string {
  return typeof value === 'string' ? value : JSON.stringify(value) ?? ''
}

function isTruncated(value: JsonValue): boolean {
  return rawText(value).length > JSON_PREVIEW_LIMIT
}

function fullJson(value: JsonValue): string {
  return JSON.stringify(value, null, 2)
}

function time(value: number | string) {
  return new Date(typeof value === 'number' ? value * 1000 : value).toLocaleString()
}

function stageLabel(stage: string) {
  return ({ queued: '排队中', preparing: '准备中', switching: '切换中', published: '已发布', finished: '完成' } as Record<string, string>)[stage] || stage
}

function statusVariant(status: string): 'info' | 'success' | 'warn' | 'danger' {
  if (status === 'succeeded') return 'success'
  if (status === 'failed') return 'danger'
  if (status === 'cancelled') return 'warn'
  return 'info'
}

function errorText(error: JsonValue): string {
  if (isObject(error) && typeof error.message === 'string') return error.message
  return JSON.stringify(error)
}

function pillClass(configured: boolean | null) {
  if (configured === true) return 'env-pill--ok'
  if (configured === false) return 'env-pill--missing'
  return 'env-pill--unknown'
}

async function apply() {
  if (await store.apply()) toast('配置任务已提交，等待 Bot 执行')
}

async function restore(target: number) {
  if (!confirm(`将快照 v${target} 恢复为新草稿${store.dirty.value ? '，并覆盖当前未保存修改' : ''}。是否继续？`)) return
  if (await store.restore(target)) toast('已恢复为新草稿，需要单独应用')
}

onMounted(() => {
  void store.loadOperations()
  if (!store.environment.value) void store.loadEnvironment()
})
</script>

<style scoped>
.publish-panel {
  display: grid;
  gap: var(--qq-gap-md);
}

.publish-panel__title {
  margin: 0;
  font-size: var(--qq-text-md);
  display: flex;
  align-items: center;
  gap: 6px;
}

.publish-panel__bar {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: var(--qq-gap-sm);
  margin-bottom: var(--qq-gap-sm);
}

.pipeline {
  display: flex;
  align-items: stretch;
  gap: var(--qq-gap-sm);
  margin-top: var(--qq-gap-sm);
}

.pipeline__node {
  flex: 1;
  min-width: 0;
  display: grid;
  gap: 2px;
  padding: 10px 12px;
  border: 1px solid var(--qq-border);
  border-radius: var(--qq-radius-md);
  background: var(--qq-surface-elevated);
}

.pipeline__label {
  color: var(--qq-text-muted);
  font-size: var(--qq-text-xs);
}

.pipeline__value {
  color: var(--qq-text);
  font-size: var(--qq-text-lg);
  font-weight: 700;
  font-family: var(--qq-font-mono);
}

.pipeline__note {
  color: var(--qq-text-quiet);
  font-size: var(--qq-text-xs);
}

.pipeline__note.warn {
  color: var(--qq-warn);
}

.pipeline__arrow {
  align-self: center;
  color: var(--qq-text-quiet);
  flex-shrink: 0;
}

.operation-active {
  margin-top: var(--qq-gap-sm);
  display: flex;
  align-items: center;
  gap: 8px;
  padding: 8px 12px;
  border-radius: var(--qq-radius-md);
  background: var(--qq-primary-soft);
  color: var(--qq-primary-deep);
  font-size: var(--qq-text-sm);
}

.spin {
  animation: publish-spin 1s linear infinite;
}

@keyframes publish-spin {
  to { transform: rotate(360deg); }
}

.muted {
  margin: 0;
  color: var(--qq-text-muted);
  font-size: var(--qq-text-sm);
}

.apply-note {
  margin: var(--qq-gap-sm) 0;
}

.impact-row {
  display: flex;
  gap: 6px;
  flex-wrap: wrap;
  margin-bottom: 8px;
}

.change-list {
  display: grid;
  gap: 4px;
  max-height: 320px;
  overflow-y: auto;
}

.change-item {
  border: 1px solid var(--qq-border-soft);
  border-radius: var(--qq-radius-md);
  padding: 6px 10px;
}

.change-item summary {
  cursor: pointer;
  font-size: var(--qq-text-sm);
  color: var(--qq-text);
  display: flex;
  align-items: center;
  gap: 8px;
}

.change-item__count {
  color: var(--qq-text-quiet);
  font-size: var(--qq-text-xs);
}

.change-item__lines {
  margin: 0 0 8px;
  padding-left: 18px;
  color: var(--qq-text);
  font-size: var(--qq-text-sm);
  line-height: 1.7;
}

.components-row {
  display: flex;
  flex-wrap: wrap;
  align-items: center;
  gap: 6px;
  margin-top: var(--qq-gap-sm);
}

.component-chip {
  padding: 3px 10px;
  border-radius: var(--qq-radius-full);
  font-size: var(--qq-text-xs);
}

.component-chip--ok { background: var(--qq-success-soft); color: var(--qq-success); }
.component-chip--warn { background: var(--qq-warn-soft); color: var(--qq-warn); }
.component-chip--bad { background: var(--qq-danger-soft); color: var(--qq-danger); }

.observed-at {
  margin-left: auto;
  color: var(--qq-text-quiet);
  font-size: var(--qq-text-xs);
}

.full-json {
  margin-top: 6px;
}

.full-json summary {
  cursor: pointer;
  font-size: var(--qq-text-xs);
  color: var(--qq-text-quiet);
}

.full-json pre {
  overflow: auto;
  max-height: 360px;
  padding: 10px;
  border-radius: var(--qq-radius-md);
  background: var(--qq-bg);
  font-size: var(--qq-text-xs);
  white-space: pre-wrap;
  overflow-wrap: anywhere;
}

.operation-result__note {
  color: var(--qq-text-quiet);
  font-size: var(--qq-text-xs);
  font-weight: 400;
}

.change-item__body {
  display: grid;
  gap: 6px;
  padding-top: 8px;
}

.change-item__body > div {
  display: flex;
  gap: 8px;
  align-items: baseline;
  min-width: 0;
}

.change-item__tag {
  flex-shrink: 0;
  font-size: var(--qq-text-xs);
  color: var(--qq-text-quiet);
}

.change-item__tag--new {
  color: var(--qq-primary);
}

.change-item code {
  font-family: var(--qq-font-mono);
  font-size: var(--qq-text-xs);
  color: var(--qq-text-muted);
  overflow-wrap: anywhere;
  white-space: pre-wrap;
}

.env-list {
  display: flex;
  flex-wrap: wrap;
  gap: 6px;
  margin-top: 8px;
}

.env-pill {
  display: inline-flex;
  align-items: center;
  gap: 4px;
  padding: 3px 10px;
  border-radius: var(--qq-radius-full);
  font-family: var(--qq-font-mono);
  font-size: var(--qq-text-xs);
}

.env-pill--ok { background: var(--qq-success-soft); color: var(--qq-success); }
.env-pill--missing { background: var(--qq-danger-soft); color: var(--qq-danger); }
.env-pill--unknown { background: var(--qq-surface-strong); color: var(--qq-text-muted); }

.warn-text {
  margin: 0;
  color: var(--qq-warn);
  font-size: var(--qq-text-sm);
}

.history-row {
  display: flex;
  align-items: center;
  gap: 10px;
  padding: 8px 0;
  border-bottom: 1px solid var(--qq-border-soft);
}

.history-row:last-child {
  border-bottom: 0;
}

.history-row__label {
  font-weight: 600;
  font-size: var(--qq-text-sm);
  color: var(--qq-text);
}

.history-row__time {
  flex: 1;
  color: var(--qq-text-muted);
  font-size: var(--qq-text-xs);
}

.operation-result {
  margin-top: var(--qq-gap-sm);
  border-top: 1px solid var(--qq-border);
  padding-top: var(--qq-gap-sm);
}

.operation-result h4 {
  margin: 0 0 8px;
  font-size: var(--qq-text-sm);
}

.operation-result pre {
  overflow: auto;
  padding: 10px;
  border-radius: var(--qq-radius-md);
  background: var(--qq-bg);
  font-size: var(--qq-text-xs);
  max-height: 320px;
}

.error-text {
  color: var(--qq-danger);
  font-size: var(--qq-text-sm);
}

@media (max-width: 700px) {
  .pipeline { flex-direction: column; }
  .pipeline__arrow { transform: rotate(90deg); }
}
</style>
