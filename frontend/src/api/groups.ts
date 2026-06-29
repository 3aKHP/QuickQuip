import { request } from './index'

export async function fetchGroups() {
  return request('/api/groups')
}

export async function fetchKnownGroups() {
  return request('/api/groups/known').catch(() => ({ groups: [] }))
}

export async function updateGroup(type: string, gid: string | number, enabled: boolean) {
  return request(`/api/groups/${type}/${encodeURIComponent(String(gid))}`, {
    method: 'POST',
    body: JSON.stringify({ enabled }),
  })
}

export async function runSummaryNow(gid: string | number) {
  return request(`/api/groups/summary/${encodeURIComponent(String(gid))}/now`, { method: 'POST' })
}

export async function runBriefingNow(gid: string | number, period?: string) {
  return request(`/api/groups/briefing/${encodeURIComponent(String(gid))}/now`, {
    method: 'POST',
    body: JSON.stringify({ period: period || null }),
  })
}

export async function runPeriodReportNow(type: 'weekly' | 'monthly', gid: string | number) {
  return request(`/api/groups/${type}/${encodeURIComponent(String(gid))}/now`, { method: 'POST' })
}
