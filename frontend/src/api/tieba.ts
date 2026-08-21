import { request } from './index'

/** 对应 TiebaThread.to_dict()；peek 接口原样返回此形状 */
export interface TiebaThread {
  tid: string
  title: string
  thread_url: string
  forum_keyword: string
  author_name: string
  main_post_text: string
  cover_image_url: string
  image_urls: string[]
  fetched_at: number
  last_seen_at: number
  is_deleted: boolean
}

/** 对应 GET /api/tieba/forums 的 forums 元素 */
export interface TiebaForumInfo {
  forum_keyword: string
  count: number
  last_sync_started_at: number
  last_sync_completed_at: number
  last_sync_status: string
  last_error: string
  login_required: boolean
  recent_sent_count: number
}

export interface TiebaForumsResponse {
  forums: TiebaForumInfo[]
}

/** 对应 GET /api/tieba/threads 列表元素（preview/image_count 为服务端投影字段） */
export interface TiebaThreadRow {
  tid: string
  title: string
  thread_url: string
  forum_keyword: string
  author_name: string
  preview: string
  cover_image_url: string
  image_count: number
  fetched_at: number
  last_seen_at: number
  is_deleted: boolean
  was_sent: boolean
}

export interface TiebaThreadListResponse {
  threads: TiebaThreadRow[]
  total: number
  has_more: boolean
}

/** 对应 GET /api/tieba/threads/{forum}/{tid}：to_dict() + was_sent */
export interface TiebaThreadDetail extends TiebaThread {
  was_sent: boolean
}

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

export async function listTiebaForums(): Promise<TiebaForumsResponse> {
  return request('/api/tieba/forums')
}

export async function fetchTiebaThreads(
  forum: string,
  { keyword, limit, offset }: { keyword?: string; limit?: number; offset?: number } = {},
): Promise<TiebaThreadListResponse> {
  const params = new URLSearchParams({ forum })
  if (keyword) params.set('keyword', keyword)
  if (limit != null) params.set('limit', String(limit))
  if (offset != null) params.set('offset', String(offset))
  return request(`/api/tieba/threads?${params.toString()}`)
}

export async function fetchTiebaThread(forum: string, tid: string): Promise<TiebaThreadDetail> {
  return request(`/api/tieba/threads/${encodeURIComponent(forum)}/${encodeURIComponent(tid)}`)
}

export async function peekTiebaThread(forum: string): Promise<TiebaThread> {
  return request(`/api/tieba/peek?forum=${encodeURIComponent(forum)}`)
}
