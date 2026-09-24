<template>
  <div class="epochs-view">
    <UiPageHeader title="纪元看板" subtitle="锚点推进与上下文窗口运行态：保留条数、驱逐事件与信封成本">
      <template #actions>
        <UiSegmented v-model="range" :options="rangeOptions" aria-label="时间范围" @update:model-value="reloadTimeline" />
        <UiButton :loading="snapshotLoading" icon="RefreshCw" @click="refreshSnapshot()">刷新快照</UiButton>
      </template>
    </UiPageHeader>

    <p v-if="error" class="error">{{ error }}</p>

    <section class="panel">
      <div class="selectors">
        <select v-model="groupKey" aria-label="会话" @change="onGroupChange">
          <option value="" disabled>选择会话…</option>
          <option v-for="item in conversations" :key="item.group_id" :value="item.group_id">
            {{ conversationLabel(item) }}
          </option>
        </select>
        <div v-if="groupKeys.length" class="key-chips">
          <button
            v-for="key in groupKeys"
            :key="`${key.provider_id}/${key.model}`"
            class="key-chip"
            :class="{ active: activeKey && activeKey.provider_id === key.provider_id && activeKey.model === key.model }"
            @click="selectKey(key)"
          >
            {{ key.provider_id }} / {{ key.model }}
          </button>
        </div>
      </div>
      <p v-if="groupKey && !groupKeys.length" class="hint">
        快照中该会话暂无纪元键——bot 进程重启后首轮请求才会懒初始化锚点。
      </p>
      <p v-if="activeKey?.history_limit != null" class="hint warn-hint">
        该会话已设置 context_limit = {{ activeKey.history_limit }} 条，纪元退化为行数滚动窗（水位线仅供参考）。
      </p>
    </section>

    <div class="stat-cards stat-cards--kpi">
      <UiStatCard label="当前保留条数" :value="kpiRows" unit="条" icon="Layers" tip="锚点之后的窗口行数（bot 进程实时快照）。" />
      <UiStatCard label="窗口 tokens" :value="kpiTokens" unit="tokens" icon="Database" tip="窗口纪元预算估算（含每行 speaker 标签开销），与请求计量同口径。" />
      <UiStatCard label="信封 ≈ 每轮" :value="kpiEnvelope" unit="tok/轮" icon="Mail" tip="【轮次上下文】信封的每轮固定输入成本（时间范围内每轮均值）。" />
      <UiStatCard label="本纪元已存活" :value="kpiAge" icon="Hourglass" :tip="epochAgeTip" />
      <div class="kpi ring-card">
        <div class="ring" :class="{ urgent: coldUrgent }">
          <svg viewBox="0 0 44 44">
            <circle class="ring-bg" cx="22" cy="22" r="18" />
            <circle class="ring-fg" cx="22" cy="22" r="18" :style="{ strokeDashoffset: ringOffset }" />
          </svg>
          <span>{{ coldLabel }}</span>
        </div>
        <div>
          <div class="kpi-label">距冷场推进</div>
          <div class="kpi-value">{{ coldText }}</div>
        </div>
      </div>
    </div>

    <section class="panel">
      <div class="panel-heading">
        <h3>窗口呼吸 · 锚点推进时间轴</h3>
        <UiSegmented v-model="mode" :options="modeOptions" aria-label="主图模式" />
      </div>
      <div class="legend">
        <span><i :style="{ background: reasonColor('cold') }" />冷场</span>
        <span><i :style="{ background: reasonColor('hot') }" />触顶</span>
        <span><i :style="{ background: reasonColor('rows') }" />行数兜底</span>
        <span><i :style="{ background: reasonColor('persona') }" />换人格</span>
        <span><i :style="{ background: epochColors.window }" />纪元窗口</span>
        <span v-if="mode === 'stack'"><i :style="{ background: epochColors.envelope }" />信封层</span>
      </div>
      <EChart v-if="hasChartData" :option="chartOption" :height="380" plot-click @plot-click="onScrub" />
      <UiEmpty v-else icon="Activity" title="暂无时间轴数据" description="该会话在时间范围内没有 LLM 请求记录。" />
      <p class="hint">
        <UiIcon name="MousePointerClick" :size="13" /> 点击主图任意位置，把窗口/信封构成条定格到该时刻
        <template v-if="mode === 'rows' && !rowsCovered">；行数计量自本功能上线起记录，更早请求仅有 token 口径</template>
      </p>
    </section>

    <section class="panel">
      <div class="panel-heading">
        <h3>窗口构成 <span class="meta">{{ windowTimeLabel }}</span></h3>
      </div>
      <WindowCompositionBar
        v-if="windowData && groupKey"
        :out="windowData.out"
        :window="windowData.window"
        :anchor-id="currentAnchorId"
        :out-total-rows="windowData.out_total_rows"
        :out-total-tokens="windowData.out_total_tokens"
        :out-tokens-approx="windowData.out_tokens_approx"
      />
      <UiEmpty v-else icon="Layers" title="暂无窗口数据" description="选择会话后显示锚点罩住的对话区间。" />
    </section>

    <section class="panel">
      <div class="panel-heading">
        <h3>信封构成 <span class="meta">{{ envelopeTimeLabel }}</span></h3>
        <div class="legend">
          <span v-for="item in envelopeLegend" :key="item.key">
            <i :style="{ background: `var(--qq-env-${item.key})` }" />{{ item.name }} <b>{{ item.value }}</b>
          </span>
        </div>
      </div>
      <EnvelopeCompositionBar :parts="envelopeParts" />
    </section>

    <section class="panel">
      <div class="panel-heading">
        <h3>推进事件</h3>
        <div class="event-nav">
          <UiButton icon="ChevronLeft" :disabled="!events.length" @click="stepEvent(-1)">上一推进</UiButton>
          <UiButton icon="ChevronRight" :disabled="!events.length" @click="stepEvent(1)">下一推进</UiButton>
          <UiButton :icon="playing ? 'Pause' : 'Play'" :disabled="!events.length" @click="togglePlay">{{ playing ? '暂停' : '回放' }}</UiButton>
        </div>
      </div>
      <div v-if="events.length" class="chips">
        <button
          v-for="(event, index) in events"
          :key="`${event.ts}-${index}`"
          class="chip"
          :class="{ active: activeEventIndex === index }"
          @click="selectEvent(event)"
        >
          <i :style="{ background: reasonColor(event.reason) }" />
          {{ formatTime(eventTs(event), 'MM-dd HH:mm') }} {{ reasonName(event.reason) }}
          <template v-if="event.evicted_rows">· −{{ event.evicted_rows }} 条</template>
        </button>
      </div>
      <UiEmpty v-else icon="History" title="时间范围内没有锚点推进" description="推进事件自本功能上线起记录；冷场/触顶/换人格都会在这里留下刻度。" />
    </section>
  </div>
</template>

<script setup lang="ts">
/**
 * 纪元看板：会话纪元（只追加锚点窗口）的运行态可视化。
 *
 * - 主图锯齿 = usage 每轮单值（按 agent_loop_id 去重，禁止 SUM 口径），
 *   悬崖/底色分段 = epoch_events 真值事件；
 * - 窗口/信封构成条 = 元数据（id/role/token），不触碰正文；
 * - 实时态（KPI/倒计时/锚点）= epoch_snapshot action 经 bot 进程回传；
 * - 擦洗：点主图任意时刻 → 按 events 锚点重现该时刻窗口（before_ts 截断 head）。
 */
import { computed, onMounted, onUnmounted, ref, watch } from 'vue'
import { format } from 'date-fns'
import EChart from '../components/ui/EChart.vue'
import UiButton from '../components/ui/UiButton.vue'
import UiEmpty from '../components/ui/UiEmpty.vue'
import UiIcon from '../components/ui/UiIcon.vue'
import UiPageHeader from '../components/ui/UiPageHeader.vue'
import UiSegmented from '../components/ui/UiSegmented.vue'
import UiStatCard from '../components/ui/UiStatCard.vue'
import WindowCompositionBar from '../components/epochs/WindowCompositionBar.vue'
import EnvelopeCompositionBar from '../components/epochs/EnvelopeCompositionBar.vue'
import { listConversations, type Conversation } from '../api/conversations'
import {
  fetchEpochTimeline,
  fetchEpochWindow,
  requestEpochSnapshot,
  type EpochEvent,
  type EpochKeySnapshot,
  type EpochMode,
  type EpochSnapshot,
  type EpochTimeline,
  type EpochWindow,
} from '../api/epochs'
import type { RuntimeActionResult } from '../api/llmRuntime'
import type { ECOption } from '../charts/echarts'
import { pollRuntimeAction } from '../composables/useRuntimeActionPolling'
import { useChartTheme } from '../composables/useChartTheme'
import { useTheme } from '../composables/useTheme'

const REASON_NAMES: Record<string, string> = {
  cold: '冷场',
  hot: '触顶',
  rows: '行数兜底',
  persona: '换人格',
  init: '初始化',
  clear: '清空上下文',
}

const SNAPSHOT_AUTO_MS = 60_000
const SCRUB_DEBOUNCE_MS = 250
const PLAY_STEP_MS = 2000
const RING_CIRCUMFERENCE = 113

const conversations = ref<Conversation[]>([])
const groupKey = ref('')
const activeKeyId = ref('')

const range = ref('7d')
const rangeOptions = [
  { value: '1d', label: '1 天' },
  { value: '7d', label: '7 天' },
  { value: '30d', label: '30 天' },
  { value: '90d', label: '90 天' },
]

const mode = ref<EpochMode>('rows')
const modeOptions = [
  { value: 'rows' as EpochMode, label: '保留条数' },
  { value: 'tokens' as EpochMode, label: '窗口 tokens' },
  { value: 'stack' as EpochMode, label: '输入构成' },
]

const timeline = ref<EpochTimeline | null>(null)
const snapshot = ref<EpochSnapshot | null>(null)
const snapshotLoading = ref(false)
const windowData = ref<EpochWindow | null>(null)
const error = ref('')

const selectedTime = ref<number | null>(null)
const nowTick = ref(Date.now())
const playing = ref(false)
const activeEventIndex = ref(-1)

let disposed = false
let scrubTimer: ReturnType<typeof setTimeout> | null = null
let playTimer: ReturnType<typeof setInterval> | null = null
let snapshotTimer: ReturnType<typeof setInterval> | null = null
let tickTimer: ReturnType<typeof setInterval> | null = null

const { chartTheme } = useChartTheme()
const { theme } = useTheme()

const epochColors = computed(() => {
  void theme.value
  const style = getComputedStyle(document.documentElement)
  const get = (name: string, fallback: string) => style.getPropertyValue(name).trim() || fallback
  return {
    cold: get('--qq-epoch-cold', '#38bdf8'),
    hot: get('--qq-epoch-hot', '#fb923c'),
    rows: get('--qq-epoch-rows', '#94a3b8'),
    persona: get('--qq-epoch-persona', '#a78bfa'),
    neutral: get('--qq-epoch-neutral', '#a3adc2'),
    window: chartTheme.value.primary,
    envelope: chartTheme.value.accent,
  }
})

function reasonColor(reason: string): string {
  const colors = epochColors.value as Record<string, string>
  return colors[reason] ?? epochColors.value.neutral
}

function reasonName(reason: string): string {
  return REASON_NAMES[reason] ?? reason
}

// ── 会话与纪元键 ────────────────────────────────────────────────

function conversationLabel(item: Conversation): string {
  const kind = item.type === 'private' ? '私聊' : item.type === 'archive' ? '归档' : '群'
  return `${kind} ${item.group_id}（${item.count} 条）`
}

const groupKeys = computed<EpochKeySnapshot[]>(() => {
  const all = snapshot.value?.keys ?? []
  return all
    .filter(key => key.scope_key === groupKey.value)
    .slice()
    .sort((a, b) => b.last_activity_at - a.last_activity_at)
})

const activeKey = computed<EpochKeySnapshot | null>(
  () => groupKeys.value.find(key => `${key.provider_id}/${key.model}` === activeKeyId.value) ?? null,
)

function defaultKeyForGroup(): EpochKeySnapshot | null {
  return groupKeys.value[0] ?? null
}

/**
 * 默认会话选择：优先快照里最活跃的纪元键；bot 重启后尚无 chat 重新建键时
 * 回退到会话列表第一个（按最近活跃 DESC），让历史锯齿立即可看。
 */
function ensureDefaultGroup() {
  if (groupKey.value) return
  const keys = snapshot.value?.keys ?? []
  const busiest = keys.slice().sort((a, b) => b.last_activity_at - a.last_activity_at)[0]
  if (busiest) {
    groupKey.value = busiest.scope_key
  } else if (conversations.value.length) {
    groupKey.value = conversations.value[0].group_id
  } else {
    return
  }
  const key = defaultKeyForGroup()
  activeKeyId.value = key ? `${key.provider_id}/${key.model}` : ''
  void reloadTimeline()
}

function onGroupChange() {
  const key = defaultKeyForGroup()
  activeKeyId.value = key ? `${key.provider_id}/${key.model}` : ''
  reloadTimeline()
}

function selectKey(key: EpochKeySnapshot) {
  activeKeyId.value = `${key.provider_id}/${key.model}`
  reloadTimeline()
}

// ── 快照（实时态） ─────────────────────────────────────────────

function validateSnapshot(result: RuntimeActionResult): EpochSnapshot {
  if (typeof result !== 'object' || result === null || !Array.isArray(result.keys)) {
    throw new Error('快照结果形状不符')
  }
  return result as unknown as EpochSnapshot
}

async function refreshSnapshot(auto = false) {
  if (!auto) snapshotLoading.value = true
  try {
    const queued = await requestEpochSnapshot()
    const data = await pollRuntimeAction(queued.action.id, {
      validate: validateSnapshot,
      isCancelled: () => disposed,
    })
    if (disposed) return
    snapshot.value = data
    ensureDefaultGroup()
  } catch (caught) {
    if (!disposed && !auto) {
      error.value = caught instanceof Error ? caught.message : '快照获取失败'
    }
  } finally {
    snapshotLoading.value = false
  }
}

// ── 时间轴与窗口 ───────────────────────────────────────────────

async function reloadTimeline() {
  if (!groupKey.value) return
  error.value = ''
  try {
    timeline.value = await fetchEpochTimeline(groupKey.value, {
      provider: activeKey.value?.provider_id,
      model: activeKey.value?.model,
      range: range.value,
    })
    const points = timeline.value.points
    selectedTime.value = points.length ? pointTs(points[points.length - 1]) : null
    activeEventIndex.value = -1
    await loadWindowAt(selectedTime.value)
  } catch (caught) {
    timeline.value = null
    error.value = caught instanceof Error ? caught.message : '时间轴加载失败'
  }
}

function pointTs(point: { ts: string }): number {
  return Date.parse(point.ts)
}

function eventTs(event: EpochEvent): number {
  return Date.parse(event.ts)
}

const events = computed<EpochEvent[]>(() => timeline.value?.events ?? [])

/** 该时刻生效的锚点（events 真值；clear 事件 new_anchor_id 为 null = 锚点抹除归 0，待重新初始化） */
function anchorAt(timeMs: number): number {
  let anchor = 0
  for (const event of events.value) {
    if (eventTs(event) <= timeMs) anchor = event.new_anchor_id ?? 0
  }
  return anchor
}

const currentAnchorId = computed(() => {
  if (selectedTime.value == null) return activeKey.value?.anchor_id ?? 0
  return anchorAt(selectedTime.value)
})

async function loadWindowAt(timeMs: number | null) {
  if (!groupKey.value) return
  const anchor = timeMs == null ? (activeKey.value?.anchor_id ?? 0) : anchorAt(timeMs)
  const beforeTs = timeMs == null ? undefined : new Date(timeMs).toISOString()
  try {
    windowData.value = await fetchEpochWindow(groupKey.value, anchor, {
      beforeTs,
      before: 26,
      limit: 1024,
    })
  } catch {
    windowData.value = null
  }
}

function scheduleScrub(timeMs: number) {
  if (scrubTimer) clearTimeout(scrubTimer)
  scrubTimer = setTimeout(() => {
    scrubTimer = null
    if (!disposed) void loadWindowAt(timeMs)
  }, SCRUB_DEBOUNCE_MS)
}

function selectTime(timeMs: number) {
  selectedTime.value = timeMs
  scheduleScrub(timeMs)
}

function onScrub(xValue: number) {
  const points = timeline.value?.points ?? []
  if (!points.length) return
  const min = pointTs(points[0])
  const max = pointTs(points[points.length - 1])
  selectTime(Math.min(Math.max(xValue, min), max))
}

function selectEvent(event: EpochEvent) {
  activeEventIndex.value = events.value.indexOf(event)
  selectTime(eventTs(event))
}

function stepEvent(direction: number) {
  if (!events.value.length) return
  const next = (activeEventIndex.value + direction + events.value.length) % events.value.length
  selectEvent(events.value[next])
}

function togglePlay() {
  if (playing.value) {
    stopPlay()
    return
  }
  if (!events.value.length) return
  playing.value = true
  stepEvent(1)
  playTimer = setInterval(() => {
    if (activeEventIndex.value >= events.value.length - 1) {
      stopPlay()
      return
    }
    stepEvent(1)
  }, PLAY_STEP_MS)
}

function stopPlay() {
  playing.value = false
  if (playTimer) {
    clearInterval(playTimer)
    playTimer = null
  }
}

// ── KPI ────────────────────────────────────────────────────────

function fmtTokens(value: number | null | undefined): string {
  if (value == null) return '—'
  return `${(value / 1000).toFixed(1)}k`
}

function fmtDuration(ms: number): string {
  const minutes = Math.round(ms / 60_000)
  if (minutes < 60) return `${minutes} 分钟`
  return `${Math.floor(minutes / 60)} 小时 ${minutes % 60} 分`
}

function formatTime(ms: number, pattern: string): string {
  return format(ms, pattern)
}

const kpiRows = computed(() => activeKey.value?.window_rows != null ? String(activeKey.value.window_rows) : '—')
const kpiTokens = computed(() => fmtTokens(activeKey.value?.window_tokens))

const kpiEnvelope = computed(() => {
  const values = (timeline.value?.points ?? [])
    .map(point => point.envelope_tokens)
    .filter((value): value is number => value != null)
  if (values.length) return String(Math.round(values.reduce((sum, value) => sum + value, 0) / values.length))
  const envelope = envelopeForActiveKey.value
  return envelope ? String(envelope.total_tokens) : '—'
})

const lastEvent = computed<EpochEvent | null>(() => events.value[events.value.length - 1] ?? null)

const epochAgeTip = computed(() =>
  lastEvent.value
    ? `当前纪元始于 ${formatTime(eventTs(lastEvent.value), 'MM-dd HH:mm')} 的${reasonName(lastEvent.value.reason)}推进。`
    : '时间范围内没有推进事件，纪元始于更早（事件自本功能上线起记录）。',
)

const kpiAge = computed(() => {
  if (!lastEvent.value) return '—'
  return fmtDuration(Math.max(0, nowTick.value - eventTs(lastEvent.value)))
})

const coldRemaining = computed(() => {
  const key = activeKey.value
  const params = key?.params
  if (!key || !params || params.cold_idle_seconds <= 0) return null
  const elapsedSinceSnapshot = (nowTick.value - snapshotFetchedAt.value) / 1000
  return Math.max(0, Math.round(params.cold_idle_seconds - key.idle_seconds - elapsedSinceSnapshot))
})

const snapshotFetchedAt = ref(Date.now())
watch(snapshot, () => {
  snapshotFetchedAt.value = Date.now()
})

const coldUrgent = computed(() => coldRemaining.value != null && coldRemaining.value < 60)

const coldLabel = computed(() => {
  const remaining = coldRemaining.value
  if (remaining == null) return '—'
  if (remaining >= 60) return `${Math.ceil(remaining / 60)}m`
  return `${remaining}s`
})

const coldText = computed(() => {
  const remaining = coldRemaining.value
  if (remaining == null) return '无数据'
  if (remaining >= 60) return `约 ${Math.ceil(remaining / 60)} 分钟`
  return `${remaining} 秒（即将推进）`
})

const ringOffset = computed(() => {
  const key = activeKey.value
  const total = key?.params?.cold_idle_seconds
  const remaining = coldRemaining.value
  if (!total || remaining == null) return RING_CIRCUMFERENCE
  return RING_CIRCUMFERENCE * (1 - remaining / total)
})

// ── 信封（最近一封） ──────────────────────────────────────────

const envelopeForActiveKey = computed(() => {
  const key = activeKey.value
  if (!key) return null
  return (
    snapshot.value?.envelopes.find(
      item => item.scope_key === key.scope_key && item.provider_id === key.provider_id && item.model === key.model,
    ) ?? null
  )
})

const envelopeParts = computed<Record<string, number> | null>(() => envelopeForActiveKey.value?.parts ?? null)

const ENVELOP_META: ReadonlyArray<{ key: string; name: string }> = [
  { key: 'time', name: '时间' },
  { key: 'festival', name: '节日' },
  { key: 'participants', name: '参与成员' },
  { key: 'mentions', name: '艾特档案' },
  { key: 'memories', name: '持久记忆' },
  { key: 'vocab', name: '词表命中' },
]

const envelopeLegend = computed(() => {
  const parts = envelopeParts.value
  if (!parts) return []
  return ENVELOP_META.filter(meta => parts[meta.key]).map(meta => ({ ...meta, value: parts[meta.key] }))
})

const envelopeTimeLabel = computed(() => {
  const envelope = envelopeForActiveKey.value
  if (!envelope) return '· 暂无缓存'
  const note =
    selectedTime.value != null && envelope.recorded_at * 1000 > selectedTime.value
      ? '（晚于所选时刻，显示最近一封）'
      : ''
  return `· 最近一封 ${formatTime(envelope.recorded_at * 1000, 'MM-dd HH:mm')}${note}`
})

const windowTimeLabel = computed(() => {
  if (selectedTime.value == null) return ''
  const event = lastEventAt(selectedTime.value)
  const suffix = event
    ? `（当前纪元始于 ${formatTime(eventTs(event), 'MM-dd HH:mm')} ${reasonName(event.reason)}推进）`
    : '（首个纪元）'
  return `· ${formatTime(selectedTime.value, 'MM-dd HH:mm')}${suffix}`
})

function lastEventAt(timeMs: number): EpochEvent | null {
  let found: EpochEvent | null = null
  for (const event of events.value) {
    if (eventTs(event) <= timeMs) found = event
  }
  return found
}

// ── 主图 ───────────────────────────────────────────────────────

interface SeriesPoint {
  ms: number
  tokens: number | null
  rows: number | null
  envelope: number | null
}

const seriesPoints = computed<SeriesPoint[]>(() =>
  (timeline.value?.points ?? []).map(point => ({
    ms: pointTs(point),
    tokens: point.epoch_tokens,
    rows: point.epoch_rows,
    envelope: point.envelope_tokens,
  })),
)

const rowsCovered = computed(() => seriesPoints.value.some(point => point.rows != null))
const hasChartData = computed(() => seriesPoints.value.length > 0)

function gradient(rgb: string): object {
  // 垂直渐变面积（顶部 30% → 底部 3%）；rgb 形如 "99,102,241"
  return {
    type: 'linear',
    x: 0, y: 0, x2: 0, y2: 1,
    colorStops: [
      { offset: 0, color: `rgba(${rgb},0.30)` },
      { offset: 1, color: `rgba(${rgb},0.03)` },
    ],
  }
}

function hexToRgb(hex: string): string {
  const value = hex.replace('#', '')
  const num = Number.parseInt(value.length === 3 ? value.split('').map(ch => ch + ch).join('') : value, 16)
  return `${(num >> 16) & 255},${(num >> 8) & 255},${num & 255}`
}

/** 悬崖端点：事件时刻前后最近的曲线值（当前模式口径） */
function cliffY(timeMs: number, after: boolean): number | null {
  const key = mode.value === 'rows' ? 'rows' : 'tokens'
  let best: { ms: number; value: number } | null = null
  for (const point of seriesPoints.value) {
    const value = point[key]
    if (value == null) continue
    const beforeOk = !after && point.ms <= timeMs
    const afterOk = after && point.ms >= timeMs
    if (!beforeOk && !afterOk) continue
    if (!best || (after ? point.ms < best.ms : point.ms > best.ms)) best = { ms: point.ms, value }
  }
  return best?.value ?? null
}

function eventStory(event: EpochEvent): string {
  const reason = reasonName(event.reason)
  if (event.reason === 'init') {
    return `<b style="color:${reasonColor('init')}">${formatTime(eventTs(event), 'HH:mm')} ${reason}</b><br>锚点初始化于 #${event.new_anchor_id ?? 0}`
  }
  if (event.reason === 'clear') {
    return `<b>${formatTime(eventTs(event), 'HH:mm')} 清空上下文</b><br>纪元键全部抹除，下轮请求重新初始化`
  }
  const evictedRows = event.evicted_rows ?? 0
  const evictedTokens = event.evicted_tokens ?? 0
  const before = cliffY(eventTs(event), false)
  const after = cliffY(eventTs(event), true)
  const dropNote =
    before != null && after != null ? `<br>窗口 ${fmtTokens(before)} → ${fmtTokens(after)}` : ''
  return `<b style="color:${reasonColor(event.reason)}">${formatTime(eventTs(event), 'HH:mm')} ${reason}推进</b><br>` +
    `${evictedRows} 条出窗 · 释放 ${fmtTokens(evictedTokens)}${dropNote}`
}

/** 纪元分段：每段以其"死因"着色（末段 = 当前纪元，主色） */
function epochSpans(): Array<{ from: number; to: number; color: string; index: number }> {
  const points = seriesPoints.value
  if (!points.length) return []
  const start = points[0].ms
  const end = points[points.length - 1].ms
  const spans: Array<{ from: number; to: number; color: string; index: number }> = []
  let prev = start
  let index = 1
  for (const event of events.value) {
    const at = eventTs(event)
    if (at <= prev || at > end) continue
    spans.push({ from: prev, to: at, color: reasonColor(event.reason), index })
    prev = at
    index += 1
  }
  spans.push({ from: prev, to: end, color: epochColors.value.window, index })
  return spans
}

const chartOption = computed(() => {
  const t = chartTheme.value
  const colors = epochColors.value
  const isRows = mode.value === 'rows'
  const isStack = mode.value === 'stack'
  const points = seriesPoints.value

  const windowSeriesData = isStack
    ? points.filter(point => point.tokens != null).map(point => [point.ms, point.tokens] as [number, number])
    : points
        .filter(point => (isRows ? point.rows != null : point.tokens != null))
        .map(point => [point.ms, (isRows ? point.rows : point.tokens) as number] as [number, number])
  const envelopeSeriesData = isStack
    ? points.filter(point => point.envelope != null).map(point => [point.ms, point.envelope] as [number, number])
    : []

  // 水位线：tokens 模式取快照参数（provider 覆盖合并后的生效值）
  const params = activeKey.value?.params
  const waterlines: Array<{ yAxis: number; name: string }> = []
  if (!isStack) {
    if (isRows) {
      waterlines.push({ yAxis: 1024, name: '行数兜底 1024' })
    } else if (params) {
      waterlines.push({ yAxis: params.cap_tokens, name: `cap ${fmtTokens(params.cap_tokens)}` })
      waterlines.push({ yAxis: params.hot_target_tokens, name: `hot_target ${fmtTokens(params.hot_target_tokens)}` })
      waterlines.push({ yAxis: params.cold_target_tokens, name: `cold_target ${fmtTokens(params.cold_target_tokens)}` })
    }
  }

  const markArea = {
    silent: true,
    data: epochSpans().map(span => [
      {
        xAxis: span.from,
        itemStyle: { color: `${span.color}12` },
        label: { show: true, formatter: `E${span.index}`, position: 'insideTop', color: t.textMuted, fontSize: 10.5 },
      },
      { xAxis: span.to },
    ]),
  }
  const markLine = {
    silent: true,
    symbol: 'none',
    data: waterlines.map(line => ({
      yAxis: line.yAxis,
      label: { formatter: line.name, position: 'insideEndTop', color: t.textMuted, fontSize: 10.5 },
      lineStyle: { color: t.border, type: 'dashed' as const },
    })),
  }

  const mainSeries = isStack
    ? [
        {
          id: 'main',
          name: '纪元窗口',
          type: 'line' as const,
          step: 'end' as const,
          symbol: 'none' as const,
          stack: 'in',
          z: 3,
          markArea,
          lineStyle: { width: 1.5, color: colors.window },
          areaStyle: { color: gradient(hexToRgb(colors.window)) },
          data: windowSeriesData,
        },
        {
          id: 'env',
          name: '信封',
          type: 'line' as const,
          step: 'end' as const,
          symbol: 'none' as const,
          stack: 'in',
          z: 4,
          lineStyle: { width: 1.5, color: colors.envelope },
          areaStyle: { color: gradient(hexToRgb(colors.envelope)) },
          data: envelopeSeriesData,
        },
      ]
    : [
        {
          id: 'main',
          name: '窗口水位',
          type: 'line' as const,
          step: 'end' as const,
          symbol: 'none' as const,
          z: 3,
          markArea,
          markLine,
          lineStyle: { width: 2, color: colors.window },
          areaStyle: { color: gradient(hexToRgb(colors.window)) },
          data: windowSeriesData,
        },
      ]

  const cliffEvents = events.value
  const cliffSeries = cliffEvents
    .filter(event => event.reason !== 'init' && event.reason !== 'clear')
    .map(event => {
      const before = cliffY(eventTs(event), false)
      const after = cliffY(eventTs(event), true)
      const data: Array<[number, number]> =
        before != null && after != null ? [[eventTs(event), before], [eventTs(event), after]] : []
      return {
        name: '推进',
        type: 'line' as const,
        z: 5,
        symbol: 'none' as const,
        lineStyle: { color: reasonColor(event.reason), width: 2.5 },
        data,
        tooltip: { formatter: () => eventStory(event) },
      }
    })
    .filter(series => series.data.length > 0)

  const markerEvents = cliffEvents
    .map(event => ({ event, after: cliffY(eventTs(event), true) }))
    .filter((item): item is { event: EpochEvent; after: number } => item.after != null)
  const markerSeries = {
    id: 'markers',
    name: '推进',
    type: 'scatter' as const,
    z: 6,
    symbolSize: 11,
    data: markerEvents.map(item => ({
      value: [eventTs(item.event), item.after] as [number, number],
      itemStyle: { color: reasonColor(item.event.reason), borderColor: t.surface, borderWidth: 2 },
    })),
    tooltip: { formatter: (params: { dataIndex: number }) => eventStory(markerEvents[params.dataIndex].event) },
  }

  const cursorSeries = {
    id: 'cursor',
    name: 'cursor',
    type: 'line' as const,
    data: [] as unknown[],
    z: 7,
    silent: true,
    markLine: {
      symbol: 'none',
      silent: true,
      animation: false,
      data: selectedTime.value != null ? [{ xAxis: selectedTime.value }] : [],
      lineStyle: { color: t.textMuted, type: 'dashed' as const, width: 1.2 },
      label: { show: false },
    },
  }

  return {
    animationDuration: 500,
    grid: { left: 58, right: 26, top: 34, bottom: 66 },
    tooltip: {
      trigger: 'axis',
      axisPointer: { type: 'line', lineStyle: { color: t.border } },
      backgroundColor: t.tooltip.backgroundColor,
      borderColor: t.tooltip.borderColor,
      textStyle: { color: t.text, fontSize: 12.5 },
      formatter(params: unknown) {
        const list = Array.isArray(params) ? params : [params]
        const first = list.find(item => item.seriesId === 'main' || item.seriesName === '纪元窗口')
        if (!first) return ''
        const [ms, value] = first.value as [number, number]
        let html = `<b>${formatTime(ms, 'MM-dd HH:mm')}</b>　窗口 <b>${isRows ? `${value} 条` : fmtTokens(value)}</b>`
        if (isStack) {
          const envItem = list.find(item => item.seriesName === '信封')
          const envValue = envItem ? (envItem.value as [number, number])[1] : 0
          html = `<b>${formatTime(ms, 'MM-dd HH:mm')}</b>　纪元窗口 <b>${fmtTokens(value)}</b> + 信封 <b>${envValue}</b> = 输入 <b>${fmtTokens(value + envValue)}</b>`
        }
        const near = events.value.find(event => Math.abs(eventTs(event) - ms) < 60_000)
        if (near) html += `<br>${eventStory(near)}`
        return html
      },
    },
    xAxis: {
      type: 'time',
      axisLabel: { formatter: (value: number) => formatTime(value, 'MM-dd HH:mm'), color: t.textMuted },
      axisLine: t.axisLine,
      splitLine: { show: false },
    },
    yAxis: {
      type: 'value',
      name: isRows ? '保留条数' : isStack ? '输入 tokens（估算）' : '窗口 tokens',
      nameTextStyle: { color: t.textMuted },
      axisLabel: { color: t.textMuted, formatter: (value: number) => (isRows ? String(value) : fmtTokens(value)) },
      splitLine: t.splitLine,
    },
    dataZoom: [
      { type: 'inside' },
      {
        type: 'slider',
        height: 26,
        bottom: 12,
        borderColor: 'transparent',
        backgroundColor: t.surfaceElevated,
        fillerColor: `rgba(${hexToRgb(colors.window)},0.12)`,
        handleStyle: { color: colors.window },
        textStyle: { color: t.textMuted },
      },
    ],
    series: [...mainSeries, ...cliffSeries, markerSeries, cursorSeries],
    // markArea 段对是运行期构造的二元组，字面量推断不满足 ECOption 的
    // 固定元组约束（LlmUsageView 同款情形）；对象形状与 ECOption 对齐，断言之。
  } as ECOption
})

// ── 生命周期 ───────────────────────────────────────────────────

onMounted(async () => {
  tickTimer = setInterval(() => {
    nowTick.value = Date.now()
  }, 1000)
  snapshotTimer = setInterval(() => {
    void refreshSnapshot(true)
  }, SNAPSHOT_AUTO_MS)
  try {
    conversations.value = (await listConversations()).conversations
    // 快照先到但键空（重启后无 chat）时，靠会话列表回退选中
    ensureDefaultGroup()
  } catch {
    // 会话列表失败不阻断快照流；选择器保持空态
  }
  await refreshSnapshot()
})

onUnmounted(() => {
  disposed = true
  stopPlay()
  if (scrubTimer) clearTimeout(scrubTimer)
  if (snapshotTimer) clearInterval(snapshotTimer)
  if (tickTimer) clearInterval(tickTimer)
})
</script>

<style scoped>
.epochs-view {
  display: flex;
  flex-direction: column;
  gap: 16px;
}
.error {
  color: var(--qq-danger);
  font-size: 13px;
}
.panel {
  background: var(--qq-surface);
  border: 1px solid var(--qq-border);
  border-radius: 14px;
  padding: 16px 18px;
}
.panel-heading {
  display: flex;
  align-items: center;
  gap: 12px;
  flex-wrap: wrap;
  margin-bottom: 10px;
}
.panel-heading h3 {
  font-size: 15px;
  font-weight: 700;
  margin: 0;
}
.panel-heading .meta {
  font-size: 12.5px;
  color: var(--qq-text-muted);
  font-weight: 400;
}
.panel-heading .spacer,
.legend + .spacer {
  flex: 1;
}
.legend {
  display: flex;
  gap: 12px;
  flex-wrap: wrap;
  font-size: 12.5px;
  color: var(--qq-text-muted);
  font-variant-numeric: tabular-nums;
  margin-left: auto;
}
.legend i {
  display: inline-block;
  width: 9px;
  height: 9px;
  border-radius: 3px;
  margin-right: 5px;
  vertical-align: -1px;
}
.legend b {
  color: var(--qq-text);
  font-weight: 600;
}
.selectors {
  display: flex;
  align-items: center;
  gap: 12px;
  flex-wrap: wrap;
}
.selectors select {
  padding: 6px 10px;
  border-radius: 8px;
  border: 1px solid var(--qq-border);
  background: var(--qq-surface);
  color: var(--qq-text);
  font-size: 13px;
}
.key-chips {
  display: flex;
  gap: 8px;
  flex-wrap: wrap;
}
.key-chip {
  border: 1px solid var(--qq-border);
  background: var(--qq-surface);
  border-radius: 999px;
  padding: 4px 12px;
  font-size: 12.5px;
  color: var(--qq-text-muted);
  cursor: pointer;
  transition: all 0.2s;
  font-variant-numeric: tabular-nums;
}
.key-chip:hover,
.key-chip.active {
  border-color: var(--qq-primary);
  color: var(--qq-text);
}
.hint {
  font-size: 12.5px;
  color: var(--qq-text-muted);
  margin: 8px 0 0;
  display: flex;
  align-items: center;
  gap: 5px;
}
.warn-hint {
  color: var(--qq-warn);
}
.kpi.ring-card {
  display: flex;
  align-items: center;
  gap: 14px;
  background: var(--qq-surface);
  border: 1px solid var(--qq-border);
  border-radius: 14px;
  padding: 14px 18px;
}
.kpi-label {
  font-size: 12.5px;
  color: var(--qq-text-muted);
}
.kpi-value {
  font-size: 15px;
  font-weight: 700;
  font-variant-numeric: tabular-nums;
}
.ring {
  position: relative;
  width: 52px;
  height: 52px;
  flex: none;
}
.ring svg {
  width: 100%;
  height: 100%;
  transform: rotate(-90deg);
}
.ring circle {
  fill: none;
  stroke-width: 4.5;
}
.ring-bg {
  stroke: var(--qq-surface-elevated);
}
.ring-fg {
  stroke: var(--qq-primary);
  stroke-linecap: round;
  stroke-dasharray: 113;
  transition: stroke-dashoffset 1s linear, stroke 0.3s;
}
.ring.urgent .ring-fg {
  stroke: var(--qq-warn);
}
.ring span {
  position: absolute;
  inset: 0;
  display: flex;
  align-items: center;
  justify-content: center;
  font-size: 12px;
  font-weight: 700;
  font-variant-numeric: tabular-nums;
}
.event-nav {
  display: flex;
  gap: 8px;
  margin-left: auto;
}
.chips {
  display: flex;
  gap: 8px;
  flex-wrap: wrap;
}
.chip {
  border: 1px solid var(--qq-border);
  background: var(--qq-surface);
  border-radius: 999px;
  padding: 4px 12px;
  font-size: 12.5px;
  cursor: pointer;
  transition: all 0.2s;
  color: var(--qq-text-muted);
  font-variant-numeric: tabular-nums;
}
.chip i {
  display: inline-block;
  width: 8px;
  height: 8px;
  border-radius: 50%;
  margin-right: 6px;
}
.chip:hover,
.chip.active {
  border-color: currentColor;
  color: var(--qq-text);
  background: var(--qq-surface-elevated);
}
</style>
