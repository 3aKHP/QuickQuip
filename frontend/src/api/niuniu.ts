import { request } from './index'

export async function getRankings(type: string = 'length', topN: number = 20) {
  return request(`/api/niuniu/rankings?type=${type}&top_n=${topN}`)
}

export async function listUsers(offset: number = 0, limit: number = 50, keyword: string = '') {
  const params = new URLSearchParams({ offset: String(offset), limit: String(limit) })
  if (keyword) params.set('keyword', keyword)
  return request(`/api/niuniu/users?${params}`)
}

export async function getUser(uid: string) {
  return request(`/api/niuniu/users/${encodeURIComponent(uid)}`)
}

export async function adjustLength(uid: string, length: number, reason: string = '') {
  return request(`/api/niuniu/users/${encodeURIComponent(uid)}/adjust`, {
    method: 'POST',
    body: JSON.stringify({ length, reason }),
  })
}

export async function setLuck(uid: string, luck: number) {
  return request(`/api/niuniu/users/${encodeURIComponent(uid)}/luck`, {
    method: 'POST',
    body: JSON.stringify({ luck }),
  })
}

export async function setFenceLuck(uid: string, fence_luck: number) {
  return request(`/api/niuniu/users/${encodeURIComponent(uid)}/fence-luck`, {
    method: 'POST',
    body: JSON.stringify({ fence_luck }),
  })
}

export async function getTextModes() {
  return request('/api/niuniu/text-mode')
}

export async function setGroupTextMode(groupId: string, mode: string) {
  return request(`/api/niuniu/text-mode/${encodeURIComponent(groupId)}`, {
    method: 'POST',
    body: JSON.stringify({ mode }),
  })
}
