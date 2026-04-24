import { request } from './index'

export async function fetchSummaryGroups() {
  return request('/api/summaries-groups')
}

export async function fetchSummaries(groupId: string) {
  return request(`/api/summaries/${groupId}`)
}

export async function fetchSummaryDetail(groupId: string, date: string) {
  return request(`/api/summaries/${groupId}/${date}`)
}

export async function deleteSummary(groupId: string, date: string) {
  return request(`/api/summaries/${groupId}/${date}`, { method: 'DELETE' })
}
