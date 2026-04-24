import { request } from './index'

export async function listConversations() {
  return request('/api/conversations')
}

export async function fetchMessages(groupKey: string, { beforeId, keyword, limit }: { beforeId?: string; keyword?: string; limit?: number } = {}) {
  const params = new URLSearchParams()
  if (beforeId) params.set('before_id', beforeId)
  if (keyword) params.set('keyword', keyword)
  if (limit != null) params.set('limit', String(limit))
  const qs = params.toString()
  return request(`/api/conversations/${encodeURIComponent(groupKey)}/messages${qs ? `?${qs}` : ''}`)
}

export async function deleteMessage(groupKey: string, msgId: string) {
  return request(
    `/api/conversations/${encodeURIComponent(groupKey)}/messages/${msgId}`,
    { method: 'DELETE' },
  )
}
