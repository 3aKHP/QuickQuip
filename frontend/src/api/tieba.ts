import { request } from './index'

export function tiebaImgProxyUrl(url: string) {
  if (!url) return ''
  return `/ops/api/tieba/imgproxy?url=${encodeURIComponent(url)}`
}

export function openTiebaSyncStream(forum: string, onMessage: (data: string) => void, onDone: () => void) {
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

export async function fetchTiebaThreads(forum: string, { keyword, limit, offset }: { keyword?: string; limit?: number; offset?: number } = {}) {
  const params = new URLSearchParams({ forum })
  if (keyword) params.set('keyword', keyword)
  if (limit != null) params.set('limit', String(limit))
  if (offset != null) params.set('offset', String(offset))
  return request(`/api/tieba/threads?${params.toString()}`)
}

export async function fetchTiebaThread(forum: string, tid: number) {
  return request(`/api/tieba/threads/${encodeURIComponent(forum)}/${encodeURIComponent(tid)}`)
}
