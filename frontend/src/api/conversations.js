import { request } from './index.js'

export async function listConversations() {
  return request('/api/conversations')
}

export async function fetchMessages(groupKey, { beforeId, keyword, limit } = {}) {
  const params = new URLSearchParams()
  if (beforeId) params.set('before_id', beforeId)
  if (keyword) params.set('keyword', keyword)
  if (limit) params.set('limit', limit)
  const qs = params.toString()
  return request(`/api/conversations/${encodeURIComponent(groupKey)}/messages${qs ? `?${qs}` : ''}`)
}

export async function deleteMessage(groupKey, msgId) {
  return request(
    `/api/conversations/${encodeURIComponent(groupKey)}/messages/${msgId}`,
    { method: 'DELETE' },
  )
}
