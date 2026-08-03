import { request } from './index'

export interface TraceCallSummary {
  id: number
  call_id: string
  agent_loop_id: string
  loop_sequence: number
  event_id?: number
  started_at: string
  completed_at: string | null
  provider_id: string
  protocol: string
  model: string
  stream: boolean
  method: string
  url: string
  request_bytes: number
  response_status: number | null
  response_bytes: number
  response_raw_bytes: number
  duration_ms: number | null
  state: 'pending' | 'success' | 'error'
  error_type: string | null
  error_message: string | null
}

export interface TraceCallDetail extends TraceCallSummary {
  request_headers: string
  request_text: string
  response_headers: string
  response_text: string
  response_raw_text: string
}

export async function fetchLogIndex() {
  return request('/api/logs')
}

export async function fetchLogTail(name: string, lines: number = 200) {
  return request(`/api/logs/files/${encodeURIComponent(name)}/tail?lines=${lines}`)
}

export function buildLogDownloadUrl(name: string) {
  return `/ops/api/logs/files/${encodeURIComponent(name)}/download`
}

export function buildLogStreamUrl(tail: number = 200) {
  return `/ops/api/logs/stream?tail=${tail}`
}

export async function fetchTraceCalls(limit: number = 50, beforeId?: number) {
  const params = new URLSearchParams({ limit: String(limit) })
  if (beforeId != null) params.set('before_id', String(beforeId))
  return request(`/api/logs/trace/calls?${params}`)
}

export async function fetchTraceCall(callId: string) {
  return request(`/api/logs/trace/calls/${encodeURIComponent(callId)}`)
}

export function buildTraceStreamUrl(afterEventId: number = 0) {
  return `/ops/api/logs/trace/stream?after_event_id=${afterEventId}`
}
