import { request } from './index'

export interface Conversation {
  group_id: string
  type: 'group' | 'private' | 'archive'
  count: number
  latest: string
  earliest: string
  loop_count: number
}

export interface ConversationMessage {
  id: number
  user_id: string | null
  sender_name: string | null
  canonical_name: string | null
  role: string
  content: string
  message_id: string | null
  created_at: string
}

export interface QueuedDeletion {
  ok: boolean
  action_id: string
  status: 'queued'
}

export async function listConversations() {
  return request<{ conversations: Conversation[] }>('/api/conversations')
}

export async function fetchMessages(groupKey: string, { beforeId, keyword, limit }: { beforeId?: number; keyword?: string; limit?: number } = {}) {
  const params = new URLSearchParams()
  if (beforeId) params.set('before_id', String(beforeId))
  if (keyword) params.set('keyword', keyword)
  if (limit != null) params.set('limit', String(limit))
  const qs = params.toString()
  return request<{ messages: ConversationMessage[]; has_more: boolean }>(`/api/conversations/${encodeURIComponent(groupKey)}/messages${qs ? `?${qs}` : ''}`)
}

export async function deleteMessage(groupKey: string, msgId: number, signal?: AbortSignal) {
  return request<QueuedDeletion>(
    `/api/conversations/${encodeURIComponent(groupKey)}/messages/${msgId}`,
    { method: 'DELETE', signal },
  )
}
