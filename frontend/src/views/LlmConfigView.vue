<template>
  <div class="llm-config-view page-view-fill">
    <UiPageHeader title="LLM 全局配置中心" subtitle="负责渠道、参数、工具策略与版本发布；修改先存为草稿，应用到 Bot 后生效">
      <template #subtitle>
        <UiInfoTip text="所有编辑只影响草稿；应用后 Bot 拉取并编译新配置，进行中的对话继续用完旧配置。密钥始终只填环境变量名。" />
      </template>
      <template #actions>
        <UiButton icon="ShieldCheck" :disabled="!store.document.value || store.busy.value" @click="store.validate()">校验配置</UiButton>
        <UiButton icon="RefreshCw" :disabled="store.busy.value" @click="reload">重新读取</UiButton>
        <UiButton icon="Save" :disabled="!store.document.value || store.busy.value || !store.dirty.value || store.conflict.value" :loading="store.saving.value" @click="save">
          保存草稿<template v-if="store.dirty.value"> ●</template>
        </UiButton>
        <UiButton variant="primary" icon="Rocket" :disabled="!store.document.value || store.busy.value || store.dirty.value || store.conflict.value || store.activeOperation.value" :loading="store.applying.value" @click="apply">应用到 Bot</UiButton>
      </template>
    </UiPageHeader>

    <div v-if="store.status.value" class="pipeline-strip" role="status">
      <div class="pipeline-step-group">
        <button class="pipeline-step" :class="{ warn: store.dirty.value }" title="点击查看发布与历史详情" @click="section = 'publish'">
          <span class="pipeline-step__label">草稿最后修改</span>
          <strong>{{ store.draftLabel.value }}</strong>
          <em v-if="store.dirty.value">有未保存改动</em>
        </button>
        <button
          type="button"
          class="note-trigger"
          title="为当前草稿版本设置自定义备注（Note）"
          @click="toggleQuickNote"
        >
          <UiIcon name="Tag" :size="12" />
          <span>{{ store.status.value.draft_version.note ? '改备注' : '加备注' }}</span>
        </button>
      </div>

      <UiIcon name="ArrowRight" :size="14" class="pipeline-strip__arrow" />

      <button class="pipeline-step" title="点击查看已发布快照" @click="section = 'publish'">
        <span class="pipeline-step__label">已发布版本</span>
        <strong>{{ store.publishedLabel.value }}</strong>
        <em v-if="!store.inSync.value" class="pipeline-step__diff">待发布更新</em>
      </button>

      <UiIcon name="ArrowRight" :size="14" class="pipeline-strip__arrow" />

      <button class="pipeline-step" :class="{ warn: !store.bot.value || store.botStale.value }" title="点击查看 Bot 运行时状态" @click="section = 'publish'">
        <span class="pipeline-step__label">Bot 实际运行</span>
        <strong>{{ store.botLoadedLabel.value }}</strong>
        <em v-if="!store.bot.value">未连接</em>
        <em v-else-if="store.botStale.value">心跳过期</em>
      </button>

      <div v-if="editingQuickNote" class="quick-note-bar">
        <input
          v-model="quickNoteText"
          class="quick-note-bar__input"
          maxlength="120"
          placeholder="输入版本备注，显示为 YYYY-MM-DD HH:mm (备注)"
          @keyup.enter="saveQuickNote"
          @keyup.esc="editingQuickNote = false"
        />
        <UiButton size="sm" variant="primary" :disabled="store.busy.value" @click="saveQuickNote">保存备注</UiButton>
        <UiButton size="sm" variant="ghost" @click="editingQuickNote = false">取消</UiButton>
      </div>

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
      <p v-for="(warning, index) in store.validation.value.warnings" :key="index" class="notice__line">{{ configWarningText(warning) }}</p>
    </div>

    <p v-if="store.pollError.value" class="poll-error">状态刷新失败：{{ store.pollError.value }}；会自动重试。</p>

    <UiLoading v-if="store.loading.value && !store.document.value" />

    <div v-else-if="store.document.value" class="llm-config-layout">
      <aside class="side-nav" aria-label="LLM 配置分类导航">
        <div class="side-nav__scroll">
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
              <span class="side-nav__item-text">{{ item.label }}</span>
              <span v-if="item.badge" class="side-nav__badge">{{ item.badge }}</span>
            </button>
          </template>

          <div class="side-nav__divider" />
          <p class="side-nav__group">LLM 工坊关联页面</p>
          <div class="workshop-links">
            <button
              v-for="link in SIDEBAR_WORKSHOP_LINKS"
              :key="link.path"
              type="button"
              class="workshop-link"
              :title="link.desc"
              @click="router.push(link.path)"
            >
              <UiIcon :name="link.icon" :size="13" />
              <span>{{ link.label }}</span>
              <UiIcon name="ArrowUpRight" :size="12" class="workshop-link__ext" />
            </button>
          </div>
        </div>
      </aside>

      <main class="panel-area" :class="{ 'panel-area--fill': section === 'providers' }">
        <div v-if="currentMeta" class="section-banner">
          <div class="section-banner__text">
            <h2 class="section-banner__title">{{ currentMeta.title }}</h2>
            <p class="section-banner__desc">{{ currentMeta.desc }}</p>
          </div>
          <div class="section-banner__right">
            <div v-if="currentSubTabs.length" class="section-subtabs" role="tablist" aria-label="模块内分节筛选">
              <button
                v-for="tab in currentSubTabs"
                :key="tab.key"
                type="button"
                class="section-subtab"
                :class="{ active: activeSubTab === tab.key }"
                @click="activeSubTab = tab.key"
              >{{ tab.label }}</button>
            </div>
            <div v-if="currentMeta.links?.length" class="section-banner__links">
              <span class="section-banner__links-label">关联页面：</span>
              <UiButton
                v-for="link in currentMeta.links"
                :key="link.path"
                size="sm"
                variant="ghost"
                :icon="link.icon"
                @click="router.push(link.path)"
              >{{ link.label }}</UiButton>
            </div>
          </div>
        </div>

        <div v-if="section === 'providers'" class="panel-area__providers-host">
          <ProvidersPanel />
        </div>

        <div v-else ref="scrollAreaEl" class="panel-area__scroll">
          <template v-if="section === 'conversation'">
            <SettingsGroup v-show="activeSubTab === 'all' || activeSubTab === 'triggers'" :blocks="SETTINGS_BLOCKS.conversation" />
            <EpochPanel v-show="activeSubTab === 'all' || activeSubTab === 'epoch'" />
            <SettingsGroup v-show="activeSubTab === 'all' || activeSubTab === 'memory'" :blocks="SETTINGS_BLOCKS.context" />
            <StylesPanel v-show="activeSubTab === 'all' || activeSubTab === 'styles'" />
          </template>
          <template v-else-if="section === 'tools'">
            <McpPanel v-show="activeSubTab === 'all' || activeSubTab === 'mcp'" />
            <SettingsGroup v-show="activeSubTab === 'all' || activeSubTab === 'tools'" :blocks="SETTINGS_BLOCKS.tools" />
            <SettingsGroup v-show="activeSubTab === 'all' || activeSubTab === 'skills'" :blocks="SETTINGS_BLOCKS.skills" />
          </template>
          <template v-else-if="section === 'reports'">
            <RoutesPanel />
            <ReportsPanel />
          </template>
          <PricingPanel v-else-if="section === 'pricing'" />
          <template v-else-if="section === 'publish'">
            <PublishPanel v-show="activeSubTab === 'all' || activeSubTab === 'publish'" />
            <ExchangePanel v-show="activeSubTab === 'all' || activeSubTab === 'exchange'" />
          </template>
        </div>
      </main>
    </div>
  </div>
</template>

<script setup lang="ts">
import { computed, nextTick, onMounted, onUnmounted, ref, watch } from 'vue'
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
import { configWarningText } from '../lib/llmConfig'

const store = getLlmConfigStore(api)
provideLlmConfigStore(store)

const scrollAreaEl = ref<HTMLElement | null>(null)

const providerCount = computed(() =>
  Array.isArray(store.document.value?.providers) ? store.document.value.providers.length : 0,
)

/** 精简为 6 个核心配置模块 */
const NAV_GROUPS = computed(() => [
  {
    label: '核心配置（6 大模块）',
    items: [
      { key: 'providers', label: '渠道与模型', icon: 'Server', badge: providerCount.value ? String(providerCount.value) : '' },
      { key: 'conversation', label: '对话与上下文', icon: 'MessageSquare', badge: '' },
      { key: 'tools', label: '工具与技能', icon: 'Wrench', badge: '' },
      { key: 'reports', label: '报告与路由', icon: 'CalendarClock', badge: '' },
      { key: 'pricing', label: '模型价格', icon: 'Coins', badge: '' },
      { key: 'publish', label: '发布与历史', icon: 'Rocket', badge: !store.inSync.value ? '待发布' : '' },
    ],
  },
])

const SECTION_ALIASES: Record<string, { section: string; subTab?: string }> = {
  general: { section: 'conversation', subTab: 'triggers' },
  retry: { section: 'conversation', subTab: 'triggers' },
  epoch: { section: 'conversation', subTab: 'epoch' },
  context: { section: 'conversation', subTab: 'memory' },
  styles: { section: 'conversation', subTab: 'styles' },
  mcp: { section: 'tools', subTab: 'mcp' },
  skills: { section: 'tools', subTab: 'skills' },
  routes: { section: 'reports' },
  exchange: { section: 'publish', subTab: 'exchange' },
}

const VALID_SECTIONS = new Set([
  'providers',
  'conversation',
  'tools',
  'reports',
  'pricing',
  'publish',
])

const SUB_TABS: Record<string, { key: string; label: string }[]> = {
  conversation: [
    { key: 'all', label: '全部视图' },
    { key: 'triggers', label: '触发与回复' },
    { key: 'epoch', label: '纪元与代理' },
    { key: 'memory', label: '上下文与记忆' },
    { key: 'styles', label: '回复风格' },
  ],
  tools: [
    { key: 'all', label: '全部视图' },
    { key: 'mcp', label: 'MCP 服务与状态' },
    { key: 'tools', label: '工具与搜索' },
    { key: 'skills', label: 'Skill 运行时' },
  ],
  publish: [
    { key: 'all', label: '全部视图' },
    { key: 'publish', label: '版本发布与快照' },
    { key: 'exchange', label: 'JSON 导入导出' },
  ],
}

const SECTION_META: Record<string, { title: string; desc: string; links?: { label: string; path: string; icon: string }[] }> = {
  providers: {
    title: '渠道与模型',
    desc: '管理 LLM 供应商 API 地址、密钥变量名、模型清单、别名及模型级参数覆盖。左栏选渠道、右栏编辑详情，两栏独立滚动。',
    links: [
      { label: '诊断与批量探活', path: '/diagnostics', icon: 'Stethoscope' },
      { label: '按群覆盖模型', path: '/group-settings', icon: 'SlidersHorizontal' },
    ],
  },
  conversation: {
    title: '对话与上下文',
    desc: '统一管理全局总开关、群聊触发与回复节奏、纪元（Epoch）压缩水位、长期记忆提取以及可复用的回复风格档案。',
    links: [
      { label: '群 LLM 覆盖', path: '/group-settings', icon: 'SlidersHorizontal' },
      { label: '人格管理', path: '/personas', icon: 'Drama' },
      { label: '纪元水位看板', path: '/epochs', icon: 'Hourglass' },
      { label: '群记忆管理', path: '/memory', icon: 'Brain' },
    ],
  },
  tools: {
    title: '工具与技能',
    desc: '集中配置外部 MCP 服务（含实时连接状态与工具清单）、内置工具白名单、自动联网搜索，以及 Skill 脚本执行约束。',
    links: [
      { label: 'Skill 文件仓库', path: '/skills', icon: 'Sparkles' },
      { label: '诊断与重载 MCP', path: '/diagnostics', icon: 'Stethoscope' },
    ],
  },
  reports: {
    title: '报告与路由',
    desc: '在同一处配置日/周/月报与早中晚简报所使用的模型级联路由（上方）及定时 Cron 与触发门槛（下方）。',
    links: [
      { label: '群聊总结看板', path: '/summary', icon: 'FileText' },
      { label: '调度器监控', path: '/cron-dashboard', icon: 'Clock' },
    ],
  },
  pricing: {
    title: '模型价格',
    desc: '配置各模型的输入/输出/缓存 Token 单价（美元 / 百万 Token），供用量看板实时估算成本。',
    links: [
      { label: '查看用量与成本看板', path: '/llm-usage', icon: 'Activity' },
    ],
  },
  publish: {
    title: '发布与历史',
    desc: '对比草稿与已发布版本差异、设置「日期时间 (备注)」版本标记、应用到 Bot、回滚历史快照，或进行 JSON 导入导出。',
    links: [
      { label: '运行时诊断与重载', path: '/diagnostics', icon: 'Stethoscope' },
    ],
  },
}

const SIDEBAR_WORKSHOP_LINKS = [
  { label: '群 LLM 覆盖', path: '/group-settings', icon: 'SlidersHorizontal', desc: '按群开关 LLM、切换模型与人格' },
  { label: '人格管理', path: '/personas', icon: 'Drama', desc: '编辑 config/personas/*.toml 角色设定' },
  { label: 'Skill 仓库', path: '/skills', icon: 'Sparkles', desc: '在线编辑 skills/ 目录下的技能文档与脚本' },
  { label: '资料词表', path: '/llm-about', icon: 'BookUser', desc: '编辑群友身份与群内黑话 YAML' },
  { label: '记忆管理', path: '/memory', icon: 'Brain', desc: '按群查看与编辑长期记忆条目' },
  { label: '纪元看板', path: '/epochs', icon: 'Hourglass', desc: '查看各群上下文压缩水位与锚点时间轴' },
  { label: '用量成本', path: '/llm-usage', icon: 'Activity', desc: '查看 Token 消耗、费用统计与未定价调用' },
  { label: '诊断中心', path: '/diagnostics', icon: 'Stethoscope', desc: '批量探活、样本请求与运行时重载' },
]

/** 支持 ?section= 深链（兼容旧书签别名并自动定位子分节） */
const route = useRoute()
const router = useRouter()
const activeSubTab = ref('all')

function resolveQuerySection(raw: unknown): { section: string; subTab: string } {
  const key = String(raw ?? '')
  const alias = SECTION_ALIASES[key]
  if (alias) return { section: alias.section, subTab: alias.subTab || 'all' }
  return { section: VALID_SECTIONS.has(key) ? key : 'providers', subTab: 'all' }
}

const initialResolved = resolveQuerySection(route.query.section)
const section = ref(initialResolved.section)
activeSubTab.value = initialResolved.subTab

watch(
  () => route.query.section,
  next => {
    const resolved = resolveQuerySection(next)
    if (section.value !== resolved.section) section.value = resolved.section
    if (resolved.subTab !== 'all') activeSubTab.value = resolved.subTab
  },
)
watch(section, value => {
  const validSubs = SUB_TABS[value]?.map(t => t.key) || ['all']
  if (!validSubs.includes(activeSubTab.value)) activeSubTab.value = 'all'
  if (route.query.section !== value) router.replace({ query: { ...route.query, section: value } })
  void nextTick(() => { scrollAreaEl.value?.scrollTo({ top: 0 }) })
})

const currentMeta = computed(() => SECTION_META[section.value] || null)
const currentSubTabs = computed(() => SUB_TABS[section.value] || [])

const SETTINGS_BLOCKS: Record<string, SettingsBlock[]> = {
  conversation: [
    { title: '总开关与全局默认', section: 'runtime', fields: ['enabled', 'memory_enabled', 'default_provider', 'default_persona', 'client_cluster', 'claude_code_device_id', 'gemini_cli_install_id'], tip: 'LLM 功能总开关；默认渠道留空时自动使用第一个启用的渠道。' },
    { title: '群聊触发规则', section: 'triggers' },
    { title: '回复拆分与发送节奏', section: 'runtime', fields: ['max_prompt_chars', 'reply_split_threshold_chars', 'reply_chunk_max_chars', 'reply_send_interval_ms', 'reply_max_chunks_per_loop', 'mention_cooldown_seconds'] },
    { title: '全局失败重试策略', section: 'runtime', fields: ['retry_max_attempts', 'retry_base_delay', 'retry_jitter'], tip: '这是全局默认；渠道与模型可以在各自的「参数覆盖」里单独覆盖。' },
  ],
  context: [
    { title: '上下文与历史窗口', section: 'runtime', fields: ['history_limit', 'history_max_messages_per_group', 'recent_context_token_budget', 'recent_context_floor_seconds', 'request_input_token_budget'] },
    { title: '长期记忆与自动提取', section: 'runtime', fields: ['memory_limit', 'memory_max_items_per_group', 'auto_memory_enabled', 'auto_memory_prompt', 'auto_memory_max_tokens'] },
  ],
  tools: [
    { title: '工具调用轮次与上限', section: 'runtime', fields: ['tool_calling_enabled', 'tool_max_rounds', 'tool_max_calls_per_round'] },
    { title: '内置工具白名单与发现', section: 'tools' },
    { title: '自动联网搜索', section: 'auto_search' },
  ],
  skills: [
    { title: 'Skill 运行时约束', section: 'skills', tip: 'Skill 目录与脚本超时约束；具体 Skill 文件内容在「Skill 仓库」页管理。' },
  ],
}

const editingQuickNote = ref(false)
const quickNoteText = ref('')

function toggleQuickNote() {
  editingQuickNote.value = !editingQuickNote.value
  if (editingQuickNote.value) {
    quickNoteText.value = store.status.value?.draft_version.note || ''
  }
}

async function saveQuickNote() {
  if (await store.saveNote('draft', quickNoteText.value.trim())) {
    editingQuickNote.value = false
    toast('当前草稿备注已更新')
  }
}

async function save() {
  const note = editingQuickNote.value ? quickNoteText.value.trim() : undefined
  if (await store.save(note)) {
    editingQuickNote.value = false
    toast('草稿已保存，应用到 Bot 后生效')
  }
}

async function apply() {
  const note = editingQuickNote.value ? quickNoteText.value.trim() : undefined
  if (await store.apply(note)) {
    editingQuickNote.value = false
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
  const stamp = new Date().toISOString().slice(0, 16).replace('T', '-').replace(':', '')
  const url = URL.createObjectURL(new Blob([JSON.stringify(store.document.value, null, 2) + '\n'], { type: 'application/json' }))
  const link = window.document.createElement('a')
  link.href = url
  link.download = `llm-local-edit-${stamp}.json`
  link.click()
  URL.revokeObjectURL(url)
}

async function discardLocal() {
  if (!confirm('放弃当前页面上的全部未保存修改，并读取服务器最新草稿？')) return
  store.conflict.value = false
  await store.reload()
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
  display: flex;
  flex-direction: column;
  gap: 12px;
  flex: 1;
  min-height: 0;
  overflow: hidden;
}

.pipeline-strip {
  display: flex;
  align-items: center;
  gap: 10px;
  flex-wrap: wrap;
  padding: 8px 14px;
  border: 1px solid var(--qq-border);
  border-radius: var(--qq-radius-card);
  background: var(--qq-surface);
  flex-shrink: 0;
}

.pipeline-step-group {
  display: inline-flex;
  align-items: center;
  gap: 4px;
  flex-wrap: wrap;
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

.pipeline-step__diff {
  color: var(--qq-primary) !important;
  font-weight: 500;
}

.pipeline-step.warn em {
  color: var(--qq-warn);
}

.note-trigger {
  display: inline-flex;
  align-items: center;
  gap: 4px;
  padding: 3px 8px;
  border: 1px dashed var(--qq-border);
  border-radius: var(--qq-radius-full);
  background: var(--qq-surface-elevated);
  color: var(--qq-text-muted);
  font: inherit;
  font-size: var(--qq-text-xs);
  cursor: pointer;
  transition: all var(--qq-transition-fast);
}

.note-trigger:hover {
  border-color: var(--qq-primary-border);
  color: var(--qq-primary);
}

.quick-note-bar {
  display: flex;
  align-items: center;
  gap: 6px;
  flex: 1 1 100%;
  padding-top: 6px;
  border-top: 1px solid var(--qq-border-soft);
}

.quick-note-bar__input {
  flex: 1;
  min-width: 200px;
  height: 30px;
  padding: 0 10px;
  border: 1px solid var(--qq-border);
  border-radius: var(--qq-radius-sm);
  background: var(--qq-bg);
  color: var(--qq-text);
  font-size: var(--qq-text-xs);
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
  padding: 10px 14px;
  border-radius: var(--qq-radius-md);
  display: grid;
  gap: 6px;
  font-size: var(--qq-text-sm);
  flex-shrink: 0;
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
  max-height: 160px;
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
  flex-shrink: 0;
}

.llm-config-layout {
  display: grid;
  grid-template-columns: 224px minmax(0, 1fr);
  gap: 16px;
  flex: 1;
  min-height: 0;
  overflow: hidden;
}

.side-nav {
  display: flex;
  flex-direction: column;
  height: 100%;
  min-height: 0;
  background: var(--qq-surface);
  border: 1px solid var(--qq-border);
  border-radius: var(--qq-radius-card);
  padding: 10px;
  overflow: hidden;
}

.side-nav__scroll {
  display: flex;
  flex-direction: column;
  gap: 2px;
  flex: 1;
  min-height: 0;
  overflow-y: auto;
  padding-right: 2px;
}

.side-nav__group {
  margin: 10px 8px 4px;
  color: var(--qq-text-quiet);
  font-size: var(--qq-text-xs);
  font-weight: 600;
  letter-spacing: 0.04em;
}

.side-nav__group:first-child {
  margin-top: 2px;
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
  flex-shrink: 0;
}

.side-nav__item-text {
  flex: 1;
  min-width: 0;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.side-nav__badge {
  padding: 1px 6px;
  border-radius: var(--qq-radius-full);
  background: var(--qq-surface-strong);
  color: var(--qq-text-muted);
  font-size: 11px;
  font-weight: 600;
}

.side-nav__item.active {
  background: var(--qq-primary-soft);
  border-color: var(--qq-primary-border);
  color: var(--qq-primary-deep);
  font-weight: 600;
}

.side-nav__item.active .side-nav__badge {
  background: var(--qq-primary);
  color: var(--qq-text-on-primary);
}

.side-nav__divider {
  height: 1px;
  background: var(--qq-border-soft);
  margin: 10px 4px 2px;
  flex-shrink: 0;
}

.workshop-links {
  display: grid;
  grid-template-columns: repeat(2, minmax(0, 1fr));
  gap: 4px;
  padding: 2px 2px 4px;
}

.workshop-link {
  display: inline-flex;
  align-items: center;
  gap: 5px;
  padding: 6px 8px;
  border: 1px solid var(--qq-border-soft);
  border-radius: var(--qq-radius-sm);
  background: var(--qq-surface-elevated);
  color: var(--qq-text-muted);
  font: inherit;
  font-size: var(--qq-text-xs);
  cursor: pointer;
  text-align: left;
  transition: all var(--qq-transition-fast);
}

.workshop-link span {
  flex: 1;
  min-width: 0;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.workshop-link__ext {
  opacity: 0.55;
  flex-shrink: 0;
}

.workshop-link:hover {
  border-color: var(--qq-primary-border);
  color: var(--qq-primary);
}

.panel-area {
  min-width: 0;
  height: 100%;
  min-height: 0;
  display: flex;
  flex-direction: column;
  gap: var(--qq-gap-sm);
  overflow: hidden;
}

.section-banner {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: var(--qq-gap-md);
  padding: 10px 14px;
  background: var(--qq-surface);
  border: 1px solid var(--qq-border);
  border-radius: var(--qq-radius-card);
  flex-wrap: wrap;
  flex-shrink: 0;
}

.section-banner__text {
  display: grid;
  gap: 2px;
  min-width: 220px;
  flex: 1;
}

.section-banner__title {
  margin: 0;
  font-size: var(--qq-text-base);
  font-weight: 600;
  color: var(--qq-text);
}

.section-banner__desc {
  margin: 0;
  font-size: var(--qq-text-xs);
  color: var(--qq-text-muted);
  line-height: 1.5;
}

.section-banner__right {
  display: flex;
  align-items: center;
  gap: 10px;
  flex-wrap: wrap;
}

.section-subtabs {
  display: flex;
  gap: 4px;
  background: var(--qq-surface-elevated);
  padding: 3px;
  border-radius: var(--qq-radius-md);
  border: 1px solid var(--qq-border-soft);
}

.section-subtab {
  border: 0;
  background: transparent;
  color: var(--qq-text-muted);
  font: inherit;
  font-size: var(--qq-text-xs);
  padding: 4px 10px;
  border-radius: var(--qq-radius-sm);
  cursor: pointer;
  white-space: nowrap;
  transition: all var(--qq-transition-fast);
}

.section-subtab:hover {
  color: var(--qq-text);
}

.section-subtab.active {
  background: var(--qq-primary-soft);
  color: var(--qq-primary-deep);
  font-weight: 600;
}

.section-banner__links {
  display: flex;
  align-items: center;
  gap: 6px;
  flex-wrap: wrap;
}

.section-banner__links-label {
  font-size: var(--qq-text-xs);
  color: var(--qq-text-quiet);
}

.panel-area__providers-host {
  flex: 1;
  min-height: 0;
  overflow: hidden;
}

.panel-area__scroll {
  flex: 1;
  min-height: 0;
  overflow-y: auto;
  display: flex;
  flex-direction: column;
  gap: var(--qq-gap-md);
  padding-right: 4px;
  padding-bottom: var(--qq-gap-md);
}

@media (max-width: 900px) {
  .llm-config-view {
    overflow: visible;
    height: auto;
  }

  .llm-config-layout {
    grid-template-columns: 1fr;
    overflow: visible;
    height: auto;
  }

  .side-nav {
    height: auto;
    padding: 8px;
  }

  .side-nav__scroll {
    flex-direction: row;
    overflow-x: auto;
    overflow-y: hidden;
    gap: 6px;
    padding-bottom: 2px;
  }

  .side-nav__group,
  .side-nav__divider,
  .workshop-links {
    display: none;
  }

  .side-nav__item {
    width: auto;
    flex-shrink: 0;
    white-space: nowrap;
  }

  .panel-area,
  .panel-area__providers-host,
  .panel-area__scroll {
    height: auto;
    overflow: visible;
  }
}
</style>
