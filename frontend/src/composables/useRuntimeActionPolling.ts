/**
 * 通用运行时 action 轮询（enqueue → poll GET /llm-runtime/actions/{id}）。
 *
 * 从 useConversationDeletion 的轮询循环抽象而来（该模块自身保持不动）：
 * 参数化结果校验与超时，供"发起只读/写操作并等待结果"的多种场景复用
 * （纪元看板快照、诊断健康检查等）。
 *
 * 单次请求自带时限（AbortController）：deadline 只在两次响应之间检查，
 * 没有它一个长挂的 GET 会让轮询永久挂起，自动刷新还会不断叠加新轮询。
 */
import { fetchLlmRuntimeAction } from '../api/llmRuntime'
import type { RuntimeAction, RuntimeActionResult } from '../api/llmRuntime'

/** 单次轮询请求的时限：挂起的 GET 不得活过观察窗口 */
const REQUEST_TIMEOUT_MS = 10_000

export interface RuntimeActionPollOptions<T> {
  /** 轮询间隔（默认 1.5s，与 bot worker 5s 消费节奏匹配） */
  intervalMs?: number
  /** 观察窗口上限（默认 30s，与 action queue 300s 超时相比留足冗余） */
  limitMs?: number
  /** 从 result_json 提取目标数据；形状不符时抛错终止 */
  validate: (result: RuntimeActionResult) => T
  /** 返回 true 时停止轮询（视图卸载守卫） */
  isCancelled?: () => boolean
}

export class RuntimeActionTimeoutError extends Error {
  constructor(message = '尚未确认任务结果') {
    super(message)
    this.name = 'RuntimeActionTimeoutError'
  }
}

export async function pollRuntimeAction<T>(
  actionId: string,
  options: RuntimeActionPollOptions<T>,
): Promise<T> {
  const intervalMs = options.intervalMs ?? 1500
  const limitMs = options.limitMs ?? 30000
  const deadline = Date.now() + limitMs
  const cancelled = options.isCancelled ?? (() => false)

  while (!cancelled() && Date.now() < deadline) {
    const controller = new AbortController()
    const timer = setTimeout(
      () => controller.abort(),
      Math.max(500, Math.min(REQUEST_TIMEOUT_MS, deadline - Date.now())),
    )
    let payload: { action: RuntimeAction }
    try {
      payload = await fetchLlmRuntimeAction(actionId, controller.signal)
    } catch (error) {
      // 超时/卸载中止统一映射为轮询超时；网络错误原样上抛
      if (error instanceof DOMException && error.name === 'AbortError') {
        throw new RuntimeActionTimeoutError()
      }
      throw error
    } finally {
      clearTimeout(timer)
    }
    const { action } = payload
    if (cancelled()) throw new RuntimeActionTimeoutError()
    if (action.id !== actionId) throw new Error('任务响应不匹配')
    if (action.status === 'succeeded') {
      if (action.result == null) throw new Error('任务缺少结果')
      return options.validate(action.result)
    }
    if (action.status === 'failed') {
      throw new Error(action.error || '任务执行失败')
    }
    if (action.status !== 'queued' && action.status !== 'running') {
      throw new Error(`未知任务状态：${action.status}`)
    }
    await new Promise(resolve => setTimeout(resolve, intervalMs))
  }
  throw new RuntimeActionTimeoutError()
}
