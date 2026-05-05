import { request } from './index'

export async function listGroups() {
  return request('/api/game-economy/groups')
}

export async function getRankings(groupId: string, topN: number = 20) {
  return request(`/api/game-economy/rankings/${encodeURIComponent(groupId)}?top_n=${topN}`)
}

export async function listAccounts(groupId: string, offset: number = 0, limit: number = 50, keyword: string = '') {
  const params = new URLSearchParams({ offset: String(offset), limit: String(limit) })
  if (keyword) params.set('keyword', keyword)
  return request(`/api/game-economy/accounts/${encodeURIComponent(groupId)}?${params}`)
}

export async function getAccount(groupId: string, userId: string) {
  return request(`/api/game-economy/accounts/${encodeURIComponent(groupId)}/${encodeURIComponent(userId)}`)
}

export async function adjustGold(groupId: string, userId: string, amount: number, reason: string = '') {
  return request(`/api/game-economy/accounts/${encodeURIComponent(groupId)}/${encodeURIComponent(userId)}/adjust`, {
    method: 'POST',
    body: JSON.stringify({ amount, reason }),
  })
}
