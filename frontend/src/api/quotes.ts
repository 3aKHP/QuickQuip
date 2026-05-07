import { request } from './index'

export async function listGroups() {
  return request('/api/quotes/groups')
}

export async function listQuotes(groupId: string, offset: number = 0, limit: number = 50, keyword: string = '') {
  const params = new URLSearchParams({ group_id: groupId, offset: String(offset), limit: String(limit) })
  if (keyword) params.set('keyword', keyword)
  return request(`/api/quotes?${params}`)
}

export async function deleteQuote(id: number) {
  return request(`/api/quotes/${encodeURIComponent(id)}`, { method: 'DELETE' })
}
