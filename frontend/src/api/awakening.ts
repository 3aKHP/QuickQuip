import { request } from './index'

export async function fetchAwakening() {
  return request('/api/awakening')
}

export async function fetchAwakeningGroup(groupId: string) {
  return request(`/api/awakening/${encodeURIComponent(groupId)}`)
}

export async function setAwakeningRule(groupId: string, ruleName: string, enabled: boolean) {
  return request(`/api/awakening/${encodeURIComponent(groupId)}/rules/${encodeURIComponent(ruleName)}`, {
    method: 'POST',
    body: JSON.stringify({ enabled }),
  })
}

export async function setAwakeningBoredom(groupId: string, enabled: boolean) {
  return request(`/api/awakening/${encodeURIComponent(groupId)}/boredom`, {
    method: 'POST',
    body: JSON.stringify({ enabled }),
  })
}

export async function updateAwakeningSettings(groupId: string, payload: Record<string, unknown>) {
  return request(`/api/awakening/${encodeURIComponent(groupId)}/settings`, {
    method: 'PUT',
    body: JSON.stringify(payload),
  })
}
