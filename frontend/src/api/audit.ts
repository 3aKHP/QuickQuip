import { request } from './index'

export interface AuditEntry {
  id: number
  timestamp: string
  operator: string
  action: string
  target_type: string
  target_id: string
  summary_before: Record<string, unknown> | null
  summary_after: Record<string, unknown> | null
}

export interface AuditQueryResult {
  items: AuditEntry[]
  total: number
}

export interface AuditQueryParams {
  page?: number
  limit?: number
  action?: string
  target_type?: string
  operator?: string
  since?: string
  until?: string
}

export async function fetchAuditEntries(params: AuditQueryParams = {}): Promise<AuditQueryResult> {
  const query = new URLSearchParams()
  if (params.page) query.set('page', String(params.page))
  if (params.limit) query.set('limit', String(params.limit))
  if (params.action) query.set('action', params.action)
  if (params.target_type) query.set('target_type', params.target_type)
  if (params.operator) query.set('operator', params.operator)
  if (params.since) query.set('since', params.since)
  if (params.until) query.set('until', params.until)

  const qs = query.toString()
  return request(`/api/audit${qs ? '?' + qs : ''}`)
}
