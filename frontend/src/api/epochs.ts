/**
 * 纪元看板 API。
 * - timeline：锯齿曲线（usage.db，每轮单值）+ 推进事件（llm.db epoch_events）；
 * - window：锚点窗口的消息元数据（id/role/token，不含正文）；
 * - snapshot：经 action queue 由 bot 进程回传的实时锚点/信封分解。
 */
import { request } from './index'
import type { RuntimeActionResponse } from './llmRuntime'

export type EpochReason = 'cold' | 'hot' | 'rows' | 'persona' | 'init' | 'clear'

export interface EpochPoint {
  /** UTC ISO 时间戳 */
  ts: string
  epoch_tokens: number | null
  epoch_rows: number | null
  envelope_tokens: number | null
}

export interface EpochEvent {
  ts: string
  provider_id: string
  model: string
  reason: EpochReason
  old_anchor_id: number
  /** clear 事件为 null（锚点已抹除） */
  new_anchor_id: number | null
  epoch_tokens: number | null
  evicted_rows: number | null
  evicted_tokens: number | null
}

export interface EpochTimeline {
  points: EpochPoint[]
  events: EpochEvent[]
}

export interface EpochWindowMessage {
  id: number
  role: 'user' | 'bot' | 'other'
  tokens: number
  ts: string
}

export interface EpochWindow {
  anchor_id: number
  window: EpochWindowMessage[]
  out: EpochWindowMessage[]
  out_total_rows: number
  out_total_tokens: number
  out_tokens_approx: boolean
}

export interface EpochParamsInfo {
  context_tokens: number
  cold_idle_seconds: number
  cold_target_tokens: number
  cold_trigger_tokens: number
  hot_target_tokens: number
  cap_tokens: number
}

export interface EpochKeySnapshot {
  scope_key: string
  provider_id: string
  model: string
  anchor_id: number
  last_activity_at: number
  idle_seconds: number
  params: EpochParamsInfo | null
  /** /llm context_limit 覆盖（行数滚动窗）；null = 纪元自动管理 */
  history_limit: number | null
  window_rows: number | null
  window_tokens: number | null
}

export interface EpochEnvelopeSnapshot {
  scope_key: string
  provider_id: string
  model: string
  /** 六段分解（键序 time/festival/participants/mentions/memories/vocab） */
  parts: Record<string, number>
  total_tokens: number
  recorded_at: number
}

export interface EpochSnapshot {
  generated_at: number
  keys: EpochKeySnapshot[]
  envelopes: EpochEnvelopeSnapshot[]
}

export type EpochMode = 'rows' | 'tokens' | 'stack'

function withQuery(path: string, params: Record<string, string | number | null | undefined>) {
  const query = new URLSearchParams()
  for (const [key, value] of Object.entries(params)) {
    if (value !== null && value !== undefined && value !== '') query.set(key, String(value))
  }
  const suffix = query.toString()
  return suffix ? `${path}?${suffix}` : path
}

export async function fetchEpochTimeline(
  groupKey: string,
  options: { provider?: string; model?: string; range?: string } = {},
): Promise<EpochTimeline> {
  return request(withQuery('/api/epochs/timeline', {
    group_key: groupKey,
    provider: options.provider,
    model: options.model,
    // 后端路由参数名是 range_（range 是 Python 关键字）；拼错会被 FastAPI 静默忽略
    range_: options.range ?? '7d',
  }))
}

export async function fetchEpochWindow(
  groupKey: string,
  anchorId: number,
  options: { beforeTs?: string; before?: number; limit?: number } = {},
): Promise<EpochWindow> {
  return request(withQuery('/api/epochs/window', {
    group_key: groupKey,
    anchor_id: anchorId,
    before_ts: options.beforeTs,
    before: options.before,
    limit: options.limit,
  }))
}

/** 发起实时快照：入队后经 GET /llm-runtime/actions/{id} 轮询取 result */
export async function requestEpochSnapshot(): Promise<RuntimeActionResponse> {
  return request('/api/epochs/snapshot', { method: 'POST' })
}
