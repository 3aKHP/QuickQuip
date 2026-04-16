import { request } from './index.js'

export async function fetchMemories(groupId, keyword) {
  const qs = keyword ? `?keyword=${encodeURIComponent(keyword)}` : ''
  return request(`/api/memory/${groupId}${qs}`)
}

export async function createMemory(groupId, payload) {
  return request(`/api/memory/${groupId}`, {
    method: 'POST',
    body: JSON.stringify(payload),
  })
}

export async function updateMemory(groupId, id, payload) {
  return request(`/api/memory/${groupId}/${id}`, {
    method: 'PUT',
    body: JSON.stringify(payload),
  })
}

export async function deleteMemory(groupId, id) {
  return request(`/api/memory/${groupId}/${id}`, { method: 'DELETE' })
}

export async function clearAllMemories(groupId) {
  return request(`/api/memory/${groupId}`, { method: 'DELETE' })
}
