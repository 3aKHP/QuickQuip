import { request } from './index'

export async function fetchMemories(groupId: string, keyword: string) {
  const qs = keyword ? `?keyword=${encodeURIComponent(keyword)}` : ''
  return request(`/api/memory/${groupId}${qs}`)
}

export async function createMemory(groupId: string, payload: Record<string, unknown>) {
  return request(`/api/memory/${groupId}`, {
    method: 'POST',
    body: JSON.stringify(payload),
  })
}

export async function updateMemory(groupId: string, id: string | number, payload: Record<string, unknown>) {
  return request(`/api/memory/${groupId}/${id}`, {
    method: 'PUT',
    body: JSON.stringify(payload),
  })
}

export async function deleteMemory(groupId: string, id: string | number) {
  return request(`/api/memory/${groupId}/${id}`, { method: 'DELETE' })
}

export async function clearAllMemories(groupId: string) {
  return request(`/api/memory/${groupId}`, { method: 'DELETE' })
}
