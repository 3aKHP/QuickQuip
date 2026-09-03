import { request } from './index'

export interface ScheduledMessageJob {
  id: string
  cron: string
  group_ids: string[]
  message: string
  enabled: boolean
  kind: 'text' | 'llm'
  recurring: boolean
  origin: string
  created_at: string
  updated_at: string
}

export interface ScheduledMessageCreateBody {
  cron: string
  group_ids: string[]
  message: string
  enabled?: boolean
  kind?: 'text' | 'llm'
  recurring?: boolean
}

export type ScheduledMessagePatch = Partial<ScheduledMessageCreateBody>

export async function fetchScheduledMessages(groupId?: string) {
  const query = groupId ? `?group_id=${encodeURIComponent(groupId)}` : ''
  return request<{ jobs: ScheduledMessageJob[] }>(`/api/scheduled-messages${query}`)
}

export async function createScheduledMessage(body: ScheduledMessageCreateBody) {
  return request<ScheduledMessageJob>('/api/scheduled-messages', {
    method: 'POST',
    body: JSON.stringify(body),
  })
}

export async function updateScheduledMessage(id: string, patch: ScheduledMessagePatch) {
  return request<ScheduledMessageJob>(`/api/scheduled-messages/${id}`, {
    method: 'PUT',
    body: JSON.stringify(patch),
  })
}

export async function deleteScheduledMessage(id: string) {
  return request<{ ok: boolean }>(`/api/scheduled-messages/${id}`, {
    method: 'DELETE',
  })
}
