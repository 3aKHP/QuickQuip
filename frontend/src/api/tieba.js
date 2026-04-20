import { request } from './index.js'

export function tiebaImgProxyUrl(url) {
  if (!url) return ''
  return `/ops/api/tieba/imgproxy?url=${encodeURIComponent(url)}`
}

export function openTiebaSyncStream(forum, onMessage, onDone) {
  const params = forum ? `?forum=${encodeURIComponent(forum)}` : ''
  const es = new EventSource(`/ops/api/tieba/sync${params}`)
  es.onmessage = (e) => {
    if (e.data === '[done]') {
      es.close()
      onDone()
    } else {
      onMessage(e.data)
    }
  }
  es.onerror = () => {
    es.close()
    onDone()
  }
  return es
}

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
