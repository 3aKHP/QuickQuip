import { request } from './index'

export interface UsageBucket {
  key: string
  cost: number
  calls: number
}

export interface LlmUsageSummary {
  total_cost: number
  total_tokens: number
  total_calls: number
  by_provider: UsageBucket[]
  by_feature: UsageBucket[]
  by_model: UsageBucket[]
  by_group: UsageBucket[]
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
}

export async function fetchLlmUsageSummary(range = '7d'): Promise<LlmUsageSummary> {
  return request(`/api/llm-usage/summary?range=${encodeURIComponent(range)}`)
}

export async function fetchLlmUsageTimeline(range = '30d'): Promise<TimelinePoint[]> {
  return request(`/api/llm-usage/timeline?range=${encodeURIComponent(range)}`)
}
