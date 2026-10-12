<template>
  <div class="llm-config-view">
    <UiPageHeader title="LLM 配置" subtitle="修改先保存为草稿，点击「应用到 Bot」后才真正生效">
      <template #subtitle>
        <UiInfoTip text="所有编辑只影响草稿；应用后 Bot 拉取并编译新配置，进行中的对话继续用完旧配置。密钥始终只填环境变量名。" />
      </template>
      <template #actions>
        <UiButton icon="ShieldCheck" :disabled="!store.document.value || store.busy.value" @click="store.validate()">校验</UiButton>
        <UiButton icon="RefreshCw" :disabled="store.busy.value" @click="reload">重新读取</UiButton>
        <UiButton icon="Save" :disabled="!store.document.value || store.busy.value || !store.dirty.value || store.conflict.value" :loading="store.saving.value" @click="save">
          保存草稿<template v-if="store.dirty.value">●</template>
        </UiButton>
        <UiButton variant="primary" icon="Rocket" :disabled="!store.document.value || store.busy.value || store.dirty.value || store.conflict.value || store.activeOperation.value" :loading="store.applying.value" @click="apply">应用到 Bot</UiButton>
      </template>
    </UiPageHeader>

    <div v-if="store.status.value" class="pipeline-strip" role="status">
      <button class="pipeline-step" :class="{ warn: store.dirty.value }" @click="section = 'publish'">
        <span class="pipeline-step__label">草稿</span>
        <strong>v{{ store.status.value.draft_revision }}</strong>
        <em v-if="store.dirty.value">未保存</em>
      </button>
      <UiIcon name="ArrowRight" :size="14" class="pipeline-strip__arrow" />
      <button class="pipeline-step" @click="section = 'publish'">
        <span class="pipeline-step__label">已发布</span>
        <strong>v{{ store.status.value.published_revision }}</strong>
      </button>
      <UiIcon name="ArrowRight" :size="14" class="pipeline-strip__arrow" />
      <button class="pipeline-step" :class="{ warn: !store.bot.value || store.botStale.value }" @click="section = 'publish'">
        <span class="pipeline-step__label">Bot 运行</span>
        <strong>{{ store.bot.value ? `v${store.bot.value.loaded_revision}` : '未报告' }}</strong>
        <em v-if="!store.bot.value">未连接</em>
        <em v-else-if="store.botStale.value">心跳过期</em>
      </button>
      <span v-if="store.operation.value && !store.isOperationFinished(store.operation.value.status)" class="pipeline-strip__active">
        <UiIcon name="Loader2" :size="13" class="spin" /> 配置任务执行中…
      </span>
    </div>

    <div v-if="store.error.value" class="notice notice--error" role="alert">
      <p>{{ store.error.value }}</p>
      <pre v-if="store.errorDetails.value">{{ JSON.stringify(store.errorDetails.value, null, 2) }}</pre>
    </div>

    <div v-if="store.conflict.value" class="notice notice--warn" role="alert">
      <p><strong>草稿已在别处被修改</strong>（另一个窗口或 CLI）。你当前的编辑已保留在页面上。</p>
      <div class="notice__actions">
        <UiButton size="sm" icon="Download" @click="downloadLocal">导出我的修改</UiButton>
        <UiButton size="sm" variant="danger" @click="discardLocal">放弃修改并读取最新</UiButton>
      </div>
    </div>

    <div v-if="store.validation.value" class="notice" :class="store.validation.value.valid ? 'notice--ok' : 'notice--warn'">
      <p>{{ store.validation.value.valid ? '配置校验通过。' : '校验发现以下警告：' }}</p>
      <p v-for="(warning, index) in store.validation.value.warnings" :key="index" class="notice__line">{{ warningText(warning) }}</p>
    </div>

    <p v-if="store.pollError.value" class="poll-error">状态刷新失败：{{ store.pollError.value }}；会自动重试。</p>

    <UiLoading v-if="store.loading.value && !store.document.value" />

    <div v-else-if="store.document.value" class="llm-config-layout">
      <aside class="side-nav">
        <template v-for="group in NAV_GROUPS" :key="group.label">
          <p class="side-nav__group">{{ group.label }}</p>
          <button
            v-for="item in group.items"
            :key="item.key"
            class="side-nav__item qq-selectable"
            :class="{ active: section === item.key }"
            @click="section = item.key"
          >
            <UiIcon :name="item.icon" :size="15" />
            {{ item.label }}
          </button>
        </template>
      </aside>

      <main class="panel-area">
        <ProvidersPanel v-if="section === 'providers'" />
        <RoutesPanel v-else-if="section === 'routes'" />
        <PricingPanel v-else-if="section === 'pricing'" />
        <StylesPanel v-else-if="section === 'styles'" />
        <EpochPanel v-else-if="section === 'epoch'" />
        <McpPanel v-else-if="section === 'mcp'" />
        <ReportsPanel v-else-if="section === 'reports'" />
        <PublishPanel v-else-if="section === 'publish'" />
        <ExchangePanel v-else-if="section === 'exchange'" />
        <SettingsGroup v-else :blocks="currentBlocks" :key="section" />
      </main>
    </div>
  </div>
</template>

<script setup lang="ts">
import { computed, onMounted, onUnmounted, ref, watch } from 'vue'
import { onBeforeRouteLeave, useRoute, useRouter } from 'vue-router'
import UiButton from '../components/ui/UiButton.vue'
import UiIcon from '../components/ui/UiIcon.vue'
import UiInfoTip from '../components/ui/UiInfoTip.vue'
import UiLoading from '../components/ui/UiLoading.vue'
import UiPageHeader from '../components/ui/UiPageHeader.vue'
import ProvidersPanel from '../components/llm-config/ProvidersPanel.vue'
import RoutesPanel from '../components/llm-config/RoutesPanel.vue'
import PricingPanel from '../components/llm-config/PricingPanel.vue'
import StylesPanel from '../components/llm-config/StylesPanel.vue'
import SettingsGroup, { type SettingsBlock } from '../components/llm-config/SettingsGroup.vue'
import EpochPanel from '../components/llm-config/EpochPanel.vue'
import McpPanel from '../components/llm-config/McpPanel.vue'
import ReportsPanel from '../components/llm-config/ReportsPanel.vue'
import PublishPanel from '../components/llm-config/PublishPanel.vue'
import ExchangePanel from '../components/llm-config/ExchangePanel.vue'
import * as api from '../api/llmConfiguration'
import { getLlmConfigStore, provideLlmConfigStore } from '../composables/useLlmConfigStore'
import { toast } from '../toast'
import { isObject, type JsonValue } from '../lib/llmConfig'

const store = getLlmConfigStore(api)
provideLlmConfigStore(store)

const NAV_GROUPS = [
  {
    label: '配置',
    items: [
      { key: 'providers', label: '渠道与模型', icon: 'Server' },
      { key: 'routes', label: '功能路由', icon: 'Route' },
      { key: 'pricing', label: '价格', icon: 'Coins' },
      { key: 'styles', label: '回复风格', icon: 'Palette' },
    ],
  },
  {
    label: '行为',
    items: [
      { key: 'general', label: '总开关与默认', icon: 'Power' },
      { key: 'conversation', label: '触发与回复', icon: 'MessageSquare' },
      { key: 'context', label: '上下文与记忆', icon: 'Brain' },
      { key: 'epoch', label: '纪元与代理', icon: 'Hourglass' },
      { key: 'retry', label: '重试', icon: 'RefreshCw' },
      { key: 'tools', label: '工具与搜索', icon: 'Wrench' },
      { key: 'skills', label: 'Skill', icon: 'Sparkles' },
      { key: 'mcp', label: 'MCP 服务', icon: 'Network' },
      { key: 'reports', label: '报告调度', icon: 'CalendarClock' },
    ],
  },
  {
    label: '管理',
    items: [
      { key: 'publish', label: '发布与历史', icon: 'Rocket' },
      { key: 'exchange', label: '导入导出', icon: 'ArrowLeftRight' },
    ],
  },
]

const ALL_SECTIONS = new Set(NAV_GROUPS.flatMap(group => group.items.map(item => item.key)))

/** 支持 ?section= 深链（路由为 hash 模式，section 走 query）：刷新/分享链接能定位到具体面板 */
const route = useRoute()
const router = useRouter()
function sectionFromQuery(): string {
  const key = String(route.query.section ?? '')
  return ALL_SECTIONS.has(key) ? key : 'providers'
}

const section = ref(sectionFromQuery())
watch(section, value => {
  if (route.query.section !== value) router.replace({ query: { ...route.query, section: value } })
})

const SETTINGS_BLOCKS: Record<string, SettingsBlock[]> = {
  general: [
    { title: '总开关与默认', section: 'runtime', fields: ['enabled', 'memory_enabled', 'default_provider', 'default_persona', 'client_cluster'], tip: 'LLM 功能总开关；默认渠道留空时自动使用第一个启用的渠道。' },
  ],
  conversation: [
    { title: '触发规则', section: 'triggers' },
    { title: '回复拆分与发送', section: 'runtime', fields: ['max_prompt_chars', 'reply_split_threshold_chars', 'reply_chunk_max_chars', 'reply_send_interval_ms', 'reply_max_chunks_per_loop', 'mention_cooldown_seconds'] },
  ],
  context: [
    { title: '上下文与历史', section: 'runtime', fields: ['history_limit', 'history_max_messages_per_group', 'recent_context_token_budget', 'recent_context_floor_seconds', 'request_input_token_budget'] },
    { title: '记忆', section: 'runtime', fields: ['memory_limit', 'memory_max_items_per_group', 'auto_memory_enabled', 'auto_memory_prompt', 'auto_memory_max_tokens'] },
  ],
  retry: [
    { title: '失败重试', section: 'runtime', fields: ['retry_max_attempts', 'retry_base_delay', 'retry_jitter'], tip: '这是全局默认；渠道与模型可以在各自的「参数覆盖」里单独覆盖。' },
  ],
  tools: [
    { title: '工具调用', section: 'runtime', fields: ['tool_calling_enabled', 'tool_max_rounds', 'tool_max_calls_per_round'] },
    { title: '工具白名单与发现', section: 'tools' },
    { title: '自动搜索', section: 'auto_search' },
  ],
  skills: [
    { title: 'Skill', section: 'skills', tip: 'Skill 目录与脚本约束；Skill 文件本身在「Skill」页管理。' },
  ],
}

const currentBlocks = computed(() => SETTINGS_BLOCKS[section.value] || [])

async function save() {
  if (await store.save()) toast('草稿已保存，应用到 Bot 后生效')
}

async function apply() {
  if (await store.apply()) {
    section.value = 'publish'
    toast('配置任务已提交，等待 Bot 执行')
  }
}

async function reload() {
  if (store.dirty.value && !confirm('重新读取会丢弃当前未保存修改。是否继续？')) return
  await store.reload()
}

function downloadLocal() {
  if (!store.document.value) return
  const url = URL.createObjectURL(new Blob([JSON.stringify(store.document.value, null, 2) + '\n'], { type: 'application/json' }))
  const link = window.document.createElement('a')
  link.href = url
  link.download = `llm-local-edit-v${store.revision.value}.json`
  link.click()
  URL.revokeObjectURL(url)
}

async function discardLocal() {
  if (!confirm('放弃当前页面上的全部未保存修改，并读取服务器最新草稿？')) return
  store.conflict.value = false
  await store.reload()
}

function warningText(warning: JsonValue): string {
  if (isObject(warning) && typeof warning.message === 'string') return warning.message
  return String(warning)
}

function beforeUnload(event: BeforeUnloadEvent) {
  if (store.dirty.value) {
    event.preventDefault()
    event.returnValue = ''
  }
}

onBeforeRouteLeave(() => !store.dirty.value || confirm('当前 LLM 配置有未保存修改，是否离开？'))
onMounted(() => { store.start(); window.addEventListener('beforeunload', beforeUnload) })
onUnmounted(() => { store.stop(); window.removeEventListener('beforeunload', beforeUnload) })
</script>

<style scoped>
.llm-config-view {
  display: grid;
  gap: 14px;
  align-content: start;
}

.pipeline-strip {
  display: flex;
  align-items: center;
  gap: 10px;
  flex-wrap: wrap;
  padding: 10px 14px;
  border: 1px solid var(--qq-border);
  border-radius: var(--qq-radius-card);
  background: var(--qq-surface);
}

.pipeline-step {
  display: inline-flex;
  align-items: baseline;
  gap: 6px;
  border: 0;
  background: transparent;
  padding: 4px 8px;
  border-radius: var(--qq-radius-md);
  cursor: pointer;
  font: inherit;
  color: var(--qq-text);
}

.pipeline-step:hover {
  background: var(--qq-surface-hover);
}

.pipeline-step__label {
  color: var(--qq-text-muted);
  font-size: var(--qq-text-xs);
}

.pipeline-step strong {
  font-family: var(--qq-font-mono);
  font-size: var(--qq-text-sm);
}

.pipeline-step em {
  font-style: normal;
  font-size: var(--qq-text-xs);
  color: var(--qq-text-quiet);
}

.pipeline-step.warn em {
  color: var(--qq-warn);
}

.pipeline-strip__arrow {
  color: var(--qq-text-quiet);
}

.pipeline-strip__active {
  margin-left: auto;
  display: inline-flex;
  align-items: center;
  gap: 6px;
  color: var(--qq-primary-deep);
  font-size: var(--qq-text-sm);
}

.spin {
  animation: llm-config-spin 1s linear infinite;
}

@keyframes llm-config-spin {
  to { transform: rotate(360deg); }
}

.notice {
  padding: 12px 14px;
  border-radius: var(--qq-radius-md);
  display: grid;
  gap: 8px;
  font-size: var(--qq-text-sm);
}

.notice p { margin: 0; }

.notice--error {
  background: var(--qq-danger-soft);
  color: var(--qq-danger);
}

.notice--warn {
  background: var(--qq-warn-soft);
  color: var(--qq-text);
}

.notice--ok {
  background: var(--qq-success-soft);
  color: var(--qq-success);
}

.notice pre {
  overflow: auto;
  max-height: 220px;
  font-size: var(--qq-text-xs);
  color: inherit;
}

.notice__actions {
  display: flex;
  gap: 8px;
  flex-wrap: wrap;
}

.notice__line {
  color: var(--qq-text-muted);
}

.poll-error {
  margin: 0;
  color: var(--qq-warn);
  font-size: var(--qq-text-sm);
}

.llm-config-layout {
  display: grid;
  grid-template-columns: 200px minmax(0, 1fr);
  gap: 18px;
  align-items: start;
}

.side-nav {
  display: grid;
  gap: 2px;
  position: sticky;
  top: 10px;
}

.side-nav__group {
  margin: 10px 10px 4px;
  color: var(--qq-text-quiet);
  font-size: var(--qq-text-xs);
  font-weight: 600;
  letter-spacing: 0.04em;
}

.side-nav__group:first-child {
  margin-top: 0;
}

.side-nav__item {
  display: flex;
  align-items: center;
  gap: 8px;
  width: 100%;
  padding: 8px 10px;
  border: 1px solid transparent;
  border-radius: var(--qq-radius-md);
  background: transparent;
  color: var(--qq-text);
  cursor: pointer;
  font: inherit;
  font-size: var(--qq-text-sm);
  text-align: left;
}

.side-nav__item.active {
  background: var(--qq-primary-soft);
  border-color: var(--qq-primary-border);
  color: var(--qq-primary-deep);
  font-weight: 600;
}

.panel-area {
  min-width: 0;
  display: grid;
  gap: var(--qq-gap-md);
}

@media (max-width: 860px) {
  .llm-config-layout {
    grid-template-columns: 1fr;
  }

  .side-nav {
    position: static;
    display: flex;
    overflow-x: auto;
    gap: 6px;
    padding-bottom: 4px;
  }

  .side-nav__group {
    display: none;
  }

  .side-nav__item {
    width: auto;
    flex-shrink: 0;
    white-space: nowrap;
  }
}
</style>
