import { request } from './index.js'

export async function fetchSummaryGroups() {
  return request('/api/summaries-groups')
}

export async function fetchSummaries(groupId) {
  return request(`/api/summaries/${groupId}`)
}

export async function fetchSummaryDetail(groupId, date) {
  return request(`/api/summaries/${groupId}/${date}`)
}

export async function deleteSummary(groupId, date) {
  return request(`/api/summaries/${groupId}/${date}`, { method: 'DELETE' })
}
