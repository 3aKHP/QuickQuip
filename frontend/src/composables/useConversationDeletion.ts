import { onUnmounted, reactive } from 'vue'
import { deleteMessage } from '../api/conversations'
import { fetchLlmRuntimeAction } from '../api/llmRuntime'
import { toast } from '../toast'

interface Deletion {
  scope: string
  rowId: number
  actionId?: string
  state: 'submitting' | 'pending' | 'unknown' | 'failed'
  message: string
}

const POLL_INTERVAL_MS = 1500
const WAIT_LIMIT_MS = 30000

export function useConversationDeletion(refresh: (scope: string) => Promise<void>) {
  const operations = reactive(new Map<string, Deletion>())
  const controllers = new Set<AbortController>()
  const timers = new Map<ReturnType<typeof setTimeout>, () => void>()
  let disposed = false

  const key = (scope: string, rowId: number) => `${scope}/${rowId}`
  const get = (scope: string, rowId: number) => operations.get(key(scope, rowId))

  function delay() {
    return new Promise<void>(resolve => {
      const timer = setTimeout(() => { timers.delete(timer); resolve() }, POLL_INTERVAL_MS)
      timers.set(timer, resolve)
    })
  }

  async function poll(operation: Deletion) {
    const deadline = Date.now() + WAIT_LIMIT_MS
    const controller = new AbortController()
    controllers.add(controller)
    // A stalled fetch must also end the observation window.
    const timeout = setTimeout(() => controller.abort(), WAIT_LIMIT_MS)
    operation.state = 'pending'
    operation.message = '待删除'
    try {
      while (!disposed && Date.now() < deadline) {
        const { action } = await fetchLlmRuntimeAction(operation.actionId!, controller.signal)
        if (disposed) return
        if (action.id !== operation.actionId) throw new Error('任务响应不匹配')
        if (action.status === 'succeeded') {
          if (typeof action.result?.deleted !== 'boolean') throw new Error('任务缺少删除结果')
          operations.delete(key(operation.scope, operation.rowId))
          toast(action.result.deleted ? '已删除' : '未删除，记录状态已变化')
          await refresh(operation.scope)
          return
        }
        if (action.status === 'failed') {
          operation.state = 'failed'
          operation.message = action.error || '删除失败'
          toast(operation.message, 'error')
          return
        }
        if (action.status !== 'queued' && action.status !== 'running') throw new Error('未知任务状态')
        operation.message = action.status === 'running' ? '正在删除' : '待删除'
        await delay()
      }
      if (!disposed) {
        operation.state = 'unknown'
        operation.message = '尚未确认删除结果'
      }
    } catch (error) {
      if (!disposed) {
        operation.state = 'unknown'
        operation.message = '尚未确认删除结果'
        toast(error instanceof Error && error.name !== 'AbortError' ? error.message : operation.message, 'error')
      }
    } finally {
      clearTimeout(timeout)
      controllers.delete(controller)
    }
  }

  async function remove(scope: string, rowId: number) {
    const previous = get(scope, rowId)
    if (previous && previous.state !== 'failed') return
    operations.set(key(scope, rowId), { scope, rowId, state: 'submitting', message: '正在提交删除' })
    const operation = get(scope, rowId)!
    const controller = new AbortController()
    controllers.add(controller)
    const timeout = setTimeout(() => controller.abort(), WAIT_LIMIT_MS)
    try {
      const response = await deleteMessage(scope, rowId, controller.signal)
      if (disposed) return
      if (!response.ok || response.status !== 'queued' || !response.action_id) throw new Error('删除请求结果未知')
      operation.actionId = response.action_id
      await poll(operation)
    } catch (error) {
      if (!disposed) {
        // A lost enqueue response may still have scheduled the deletion.
        operation.state = 'unknown'
        operation.message = '提交结果未知，请刷新会话确认'
        toast(error instanceof Error ? error.message : operation.message, 'error')
      }
    } finally {
      clearTimeout(timeout)
      controllers.delete(controller)
    }
  }

  async function resume(scope: string, rowId: number) {
    const operation = get(scope, rowId)
    if (operation?.state === 'unknown' && operation.actionId) await poll(operation)
  }

  onUnmounted(() => {
    disposed = true
    controllers.forEach(controller => controller.abort())
    timers.forEach((resolve, timer) => { clearTimeout(timer); resolve() })
    timers.clear()
  })

  return { get, remove, resume }
}
