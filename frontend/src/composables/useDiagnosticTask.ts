import { computed, onUnmounted, ref, shallowRef } from 'vue'
import { fetchDiagnosticOperation } from '../api/diagnostics'
import type { DiagnosticOperation } from '../api/diagnostics'

const finished = (status: string) => ['succeeded', 'failed', 'cancelled'].includes(status)

/** 连续读失败的退避上限：读间隔逐次翻倍，封顶 10s，成功复位 */
const READ_BACKOFF_CAP_MS = 10_000

function failureMessage(error: unknown): string {
  if (error && typeof error === 'object' && 'message' in error) return String(error.message)
  return '诊断请求失败'
}

function isAbortError(error: unknown): boolean {
  return error instanceof Error && error.name === 'AbortError'
}

/** One billable submission, with explicit recovery and bounded read-only observation. */
export function useDiagnosticTask<T>(
  read: (id: string, signal?: AbortSignal) => Promise<DiagnosticOperation<T>> = fetchDiagnosticOperation<T>,
  observation = { intervalMs: 1000, timeoutMs: 60_000 },
) {
  const operation = shallowRef<DiagnosticOperation<T> | null>(null)
  const result = shallowRef<T | null>(null)
  const loading = ref(false)
  const cancelling = ref(false)
  const error = ref('')
  const submission = shallowRef<(() => Promise<DiagnosticOperation<T>>) | null>(null)
  const pending = computed(() => submission.value !== null && !finished(operation.value?.status || ''))
  const statusText = computed(() => operation.value
    ? ({ queued: '排队中', running: '执行中', succeeded: '已完成', failed: '失败', cancelled: '已取消' }[operation.value.status])
    : pending.value ? '提交结果尚未确认' : '')
  let disposed = false
  let runToken = 0
  let sleepTimer: ReturnType<typeof setTimeout> | null = null
  let sleepResolve: (() => void) | null = null
  let activeController: AbortController | null = null

  function cancelWait() {
    if (sleepTimer !== null) {
      if (typeof clearTimeout === 'function') clearTimeout(sleepTimer)
      sleepTimer = null
    }
    if (sleepResolve) {
      const done = sleepResolve
      sleepResolve = null
      done()
    }
    if (activeController) {
      activeController.abort()
      activeController = null
    }
  }

  function sleep(ms: number): Promise<void> {
    return new Promise(resolve => {
      sleepResolve = resolve
      sleepTimer = setTimeout(() => {
        sleepTimer = null
        sleepResolve = null
        resolve()
      }, ms)
    })
  }

  onUnmounted(() => {
    disposed = true
    runToken += 1
    cancelWait()
  })

  async function observe(token: number): Promise<DiagnosticOperation<T> | null> {
    const deadline = Date.now() + observation.timeoutMs
    let readFailures = 0
    while (operation.value && !finished(operation.value.status)) {
      if (disposed || token !== runToken) return null
      if (Date.now() >= deadline) {
        error.value = '任务结果尚未确认，请检查 Bot 在线状态后继续查询。继续查询不会重新调用模型。'
        return null
      }
      // 只有读失败参与退避：成功一次即复位到基础间隔
      await sleep(Math.min(observation.intervalMs * 2 ** readFailures, READ_BACKOFF_CAP_MS))
      if (disposed || token !== runToken || !operation.value) return null
      const controller = typeof AbortController === 'function' ? new AbortController() : null
      activeController = controller
      try {
        const next = await read(operation.value.id, controller?.signal)
        if (disposed || token !== runToken) return null
        operation.value = next
        error.value = ''
        readFailures = 0
      } catch (cause) {
        if (disposed || token !== runToken) return null
        if (isAbortError(cause) && controller?.signal.aborted) return null
        // Only reads are retried. Submission remains bound to its original request id.
        readFailures += 1
        error.value = failureMessage(cause)
      } finally {
        if (activeController === controller) activeController = null
      }
    }
    if (disposed || token !== runToken || !operation.value) return null
    if (operation.value.status === 'succeeded') result.value = operation.value.result
    else error.value = failureMessage(operation.value.error || { message: '诊断任务已取消' })
    return operation.value
  }

  async function resume(): Promise<DiagnosticOperation<T> | null> {
    if (loading.value || cancelling.value || disposed || !submission.value) return null
    const token = ++runToken
    loading.value = true
    error.value = ''
    try {
      if (!operation.value) {
        const submitted = await submission.value()
        if (disposed || token !== runToken) return null
        operation.value = submitted
      }
      return await observe(token)
    } catch (cause) {
      if (disposed || token !== runToken) return null
      error.value = failureMessage(cause)
      const status = cause && typeof cause === 'object' && 'status' in cause ? Number(cause.status) : 0
      // A rejected request can be corrected. A lost response retains its exact submission.
      if (status >= 400 && status < 500) submission.value = null
      return null
    } finally {
      if (token === runToken) loading.value = false
    }
  }

  async function start(submit: () => Promise<DiagnosticOperation<T>>) {
    if (loading.value || cancelling.value || disposed) return null
    if (pending.value) return resume()
    submission.value = submit
    operation.value = null
    result.value = null
    return resume()
  }

  /** 放弃当前待确认任务的本地跟踪，解除表单阻塞（不重新提交） */
  function reset() {
    runToken += 1
    cancelWait()
    submission.value = null
    operation.value = null
    error.value = ''
    loading.value = false
    cancelling.value = false
  }

  /** 尝试通过后端取消挂起任务；无 operation.id 时等价于 reset() */
  async function cancel(
    cancelOp?: (id: string) => Promise<DiagnosticOperation<T>>,
  ): Promise<boolean> {
    if (disposed || cancelling.value) return false
    const op = operation.value
    if (!op || finished(op.status) || !cancelOp) {
      reset()
      return true
    }
    runToken += 1
    cancelWait()
    loading.value = false
    cancelling.value = true
    error.value = ''
    try {
      const updated = await cancelOp(op.id)
      if (disposed) return false
      operation.value = updated
      if (finished(updated.status)) {
        submission.value = null
        if (updated.status === 'succeeded') result.value = updated.result
        else error.value = failureMessage(updated.error || { message: '诊断任务已取消' })
      }
      return true
    } catch (cause) {
      if (!disposed) error.value = failureMessage(cause)
      return false
    } finally {
      if (!disposed) cancelling.value = false
    }
  }

  return { operation, result, loading, cancelling, error, pending, statusText, start, resume, reset, cancel }
}
