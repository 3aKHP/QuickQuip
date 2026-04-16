import { request } from './index.js'

export async function fetchRules() {
  return request('/api/rules')
}

export async function updateRule(groupId, ruleName, enabled) {
  return request(`/api/rules/${groupId}/${ruleName}`, {
    method: 'POST',
    body: JSON.stringify({ enabled }),
  })
}
