import { request, BASE } from './index'

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

export interface TiebaSyncStream {
  /** 中止同步流（组件卸载时调用）；中止后不再触发 onMessage/onDone；服务端的抓取任务可能继续执行至完成 */
  close: () => void
}

/**
 * 触发贴吧同步并消费其 SSE 进度流。同步有副作用，走 POST + fetch 流式读取
 * （EventSource 只支持 GET），返回的句柄用于主动关闭。
 * 结束语义：收到 [done]、流结束或连接出错即视为完成（不重连），回调 onDone；
 * HTTP 错误先以一行状态文本走 onMessage。主动 close() 后不再有任何回调。
 */
export function startTiebaSync(
  forum: string,
  onMessage: (data: string) => void,
  onDone: () => void,
): TiebaSyncStream {
  const controller = new AbortController()
  const params = forum ? `?forum=${encodeURIComponent(forum)}` : ''
  let aborted = false
  let doneFired = false
  const fireDone = () => {
    if (doneFired || aborted) return
    doneFired = true
    onDone()
  }

  fetch(`${BASE}/api/tieba/sync${params}`, {
    method: 'POST',
    credentials: 'same-origin',
    signal: controller.signal,
  })
    .then(async (res) => {
      if (!res.ok || !res.body) {
        if (!aborted) onMessage(`✕ 同步请求失败（HTTP ${res.status}），请查看服务日志`)
        return
      }
      const reader = res.body.getReader()
      const decoder = new TextDecoder()
      let buffer = ''
      for (;;) {
        const { done, value } = await reader.read()
        if (done) break
        buffer += decoder.decode(value, { stream: true })
        let sep = buffer.indexOf('\n\n')
        while (sep >= 0) {
          const frame = buffer.slice(0, sep)
          buffer = buffer.slice(sep + 2)
          sep = buffer.indexOf('\n\n')
          const data = frame.startsWith('data: ') ? frame.slice(6) : null
          if (data === '[done]') return
          if (data && !aborted) onMessage(data)
        }
      }
    })
    .catch(() => {})
    .finally(fireDone)

  return {
    close: () => {
      aborted = true
      controller.abort()
    },
  }
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
