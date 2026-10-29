import { request } from './index'
import type { RecordBody } from './recordContent'

export interface MemoryEntry {
  id: number
  title: string
  description: string
  content: string
  content_display: string
  content_parts: RecordBody
  version: number
  source: string
  user_id?: string | null
  writer: string
  source_user_id: string | null
  source_message_id: string | null
  source_role: string
  updated_at: string
}
export interface MemoryInput {
  title?: string
  description?: string
  content_parts: RecordBody
}
export interface MemoryStatus { count: number; capacity: number }

export async function fetchMemories(scope: string, keyword: string, offset = 0) {
  const qs = `?keyword=${encodeURIComponent(keyword)}&offset=${offset}&limit=50`
  return request<MemoryEntry[]>(`/api/memory/${scope}${qs}`)
}
export async function fetchMemoryStatus(scope: string) {
  return request<MemoryStatus>(`/api/memory/${scope}/status`)
}
export async function createMemory(scope: string, payload: MemoryInput) {
  return request<{ id: number }>(`/api/memory/${scope}`, {
    method: 'POST', body: JSON.stringify(payload),
  })
}
export async function updateMemory(scope: string, id: number, payload: MemoryInput & { version: number }) {
  return request<MemoryEntry>(`/api/memory/${scope}/${id}`, {
    method: 'PUT', body: JSON.stringify(payload),
  })
}
export async function deleteMemory(scope: string, id: number, version: number) {
  return request<{ ok: boolean }>(`/api/memory/${scope}/${id}?version=${version}`, { method: 'DELETE' })
}
export async function clearAllMemories(scope: string) {
  return request<{ deleted: number }>(`/api/memory/${scope}`, { method: 'DELETE' })
}
