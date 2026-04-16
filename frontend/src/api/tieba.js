import { request } from './index.js'

export async function listTiebaForums() {
  return request('/api/tieba/forums')
}

export async function fetchTiebaThreads(forum, { keyword, limit, offset } = {}) {
  const params = new URLSearchParams({ forum })
  if (keyword) params.set('keyword', keyword)
  if (limit) params.set('limit', limit)
  if (offset) params.set('offset', offset)
  return request(`/api/tieba/threads?${params.toString()}`)
}

export async function fetchTiebaThread(forum, tid) {
  return request(`/api/tieba/threads/${encodeURIComponent(forum)}/${encodeURIComponent(tid)}`)
}
