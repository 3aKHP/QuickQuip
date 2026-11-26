import { request } from './index'

export async function fetchRules() {
  return request('/api/rules')
}

export async function updateRule(groupId: string, ruleName: string, enabled: boolean) {
  return request(`/api/rules/${encodeURIComponent(groupId)}/${encodeURIComponent(ruleName)}`, {
    method: 'POST',
    body: JSON.stringify({ enabled }),
  })
}
