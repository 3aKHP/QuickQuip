import { request } from './index'

export type UsageMetric = 'cost' | 'tokens' | 'requests' | 'errors' | 'duration'

export interface UsageBucket {
  key: string
  cost: number
  calls: number
  tokens: number
  errors: number
}

export interface LlmUsageSummary {
  total_cost: number
  total_tokens: number
  total_fresh_input_tokens: number
  total_output_tokens: number
  total_cache_read_tokens: number
  total_cache_creation_tokens: number
  request_count: number
  success_count: number
  total_calls: number
  success_rate: number
  average_duration_ms: number
  cache_hit_rate: number
  by_provider: UsageBucket[]
  by_feature: UsageBucket[]
  by_model: UsageBucket[]
  by_group: UsageBucket[]
  by_persona: UsageBucket[]
  unattributed_label: string
  unpriced_calls_count: number
  unpriced_tokens_total: number
  error_count: number
  cancelled_count: number
  bounds_note: string
}

export interface TimelinePoint {
  date: string
  cost: number
  tokens: number
  requests: number
  errors: number
  duration: number
  value: number
}

export interface UsageEvent {
  id: number
  ts: string
  provider_id: string
  protocol: string
  model: string
  feature: string | null
  group_id: string | null
  persona_id: string | null
  agent_loop_id: string | null
  stream: number
  duration_ms: number | null
  input_tokens: number | null
  fresh_input_tokens: number | null
  total_tokens: number | null
  input_token_semantics: string | null
  output_tokens: number | null
  cache_creation_tokens: number | null
  cache_read_tokens: number | null
  thinking_tokens: number | null
  cost_usd: number
  input_cost_usd: number
  output_cost_usd: number
  cache_read_cost_usd: number
  cache_creation_cost_usd: number
  pricing_model: string | null
  pricing_source: string | null
  pricing_confidence: string | null
  priced: number
  state: string
  error_message: string | null
}

export interface UsageFilters {
  provider?: string
  model?: string
  feature?: string
  group?: string
  persona?: string
  state?: string
}

export interface UsageDimensions {
  providers: string[]
  models: string[]
  features: string[]
  groups: string[]
  personas: string[]
  unattributed_label: string
}

function query(filters: UsageFilters = {}): string {
  return Object.entries(filters)
    .filter(([, value]) => value)
    .map(([key, value]) => `${encodeURIComponent(key)}=${encodeURIComponent(value as string)}`)
    .join('&')
}

function withQuery(path: string, params: Record<string, string | undefined>): string {
  const entries = Object.entries(params).filter(([, value]) => value)
  return entries.length ? `${path}?${entries.map(([key, value]) => `${encodeURIComponent(key)}=${encodeURIComponent(value as string)}`).join('&')}` : path
}

export async function fetchLlmUsageSummary(range = '7d', filters: UsageFilters = {}): Promise<LlmUsageSummary> {
  const suffix = query(filters)
  return request(`/api/llm-usage/summary?range=${encodeURIComponent(range)}${suffix ? `&${suffix}` : ''}`)
}

export async function fetchLlmUsageTimeline(range = '30d', metric: UsageMetric = 'cost', filters: UsageFilters = {}): Promise<TimelinePoint[]> {
  const suffix = query(filters)
  return request(`/api/llm-usage/timeline?range=${encodeURIComponent(range)}&metric=${metric}${suffix ? `&${suffix}` : ''}`)
}

export async function fetchLlmUsageEvents(
  range = '7d',
  filters: UsageFilters = {},
  cursor?: string,
  limit = 40,
): Promise<{ items: UsageEvent[]; next_cursor: string | null }> {
  return request(withQuery('/api/llm-usage/events', { range, limit: String(limit), cursor, ...filters }))
}

export async function fetchLlmUsageEvent(id: number): Promise<UsageEvent> {
  return request(`/api/llm-usage/events/${id}`)
}

export async function fetchLlmUsageDimensions(range = '7d'): Promise<UsageDimensions> {
  return request(`/api/llm-usage/dimensions?range=${encodeURIComponent(range)}`)
}
