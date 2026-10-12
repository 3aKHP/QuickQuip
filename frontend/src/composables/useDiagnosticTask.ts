import { computed, onUnmounted, ref, shallowRef } from 'vue'
import { fetchDiagnosticOperation } from '../api/diagnostics'
import type { DiagnosticOperation } from '../api/diagnostics'

const finished = (status: string) => ['succeeded', 'failed', 'cancelled'].includes(status)

function failureMessage(error: unknown): string {
  if (error && typeof error === 'object' && 'message' in error) return String(error.message)
  return '诊断请求失败'
}

/** One billable submission, with explicit recovery and bounded read-only observation. */
export function useDiagnosticTask<T>(
  read: (id: string) => Promise<DiagnosticOperation<T>> = fetchDiagnosticOperation<T>,
  observation = { intervalMs: 1000, timeoutMs: 60_000 },
) {
  const operation = shallowRef<DiagnosticOperation<T> | null>(null)
  const result = shallowRef<T | null>(null)
  const loading = ref(false)
  const error = ref('')
  const submission = shallowRef<(() => Promise<DiagnosticOperation<T>>) | null>(null)
  const pending = computed(() => submission.value !== null && !finished(operation.value?.status || ''))
  const statusText = computed(() => operation.value
    ? ({ queued: '排队中', running: '执行中', succeeded: '已完成', failed: '失败', cancelled: '已取消' }[operation.value.status])
    : pending.value ? '提交结果尚未确认' : '')
  let disposed = false
  onUnmounted(() => { disposed = true })

  async function observe(): Promise<DiagnosticOperation<T> | null> {
    const deadline = Date.now() + observation.timeoutMs
    while (operation.value && !finished(operation.value.status)) {
      if (disposed) return null
      if (Date.now() >= deadline) {
        error.value = '任务结果尚未确认，请检查 Bot 在线状态后继续查询。继续查询不会重新调用模型。'
        return null
      }
      await new Promise(resolve => setTimeout(resolve, observation.intervalMs))
      if (disposed) return null
      try {
        operation.value = await read(operation.value.id)
        error.value = ''
      } catch (cause) {
        // Only reads are retried. Submission remains bound to its original request id.
        error.value = failureMessage(cause)
      }
    }
    if (!operation.value) return null
    if (operation.value.status === 'succeeded') result.value = operation.value.result
    else error.value = failureMessage(operation.value.error || { message: '诊断任务已取消' })
    return operation.value
  }

  async function resume(): Promise<DiagnosticOperation<T> | null> {
    if (loading.value || disposed || !submission.value) return null
    loading.value = true
    error.value = ''
    try {
      if (!operation.value) operation.value = await submission.value()
      return await observe()
    } catch (cause) {
      error.value = failureMessage(cause)
      const status = cause && typeof cause === 'object' && 'status' in cause ? Number(cause.status) : 0
      // A rejected request can be corrected. A lost response retains its exact submission.
      if (status >= 400 && status < 500) submission.value = null
      return null
    } finally {
      loading.value = false
    }
  }

  async function start(submit: () => Promise<DiagnosticOperation<T>>) {
    if (loading.value || disposed) return null
    if (pending.value) return resume()
    submission.value = submit
    operation.value = null
    result.value = null
    return resume()
  }

  return { operation, result, loading, error, pending, statusText, start, resume }
}
