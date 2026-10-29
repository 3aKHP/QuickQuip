import { ref, nextTick, onScopeDispose } from 'vue'
import { startTiebaSync, type TiebaSyncStream } from '../api/tieba'

/**
 * 贴吧同步流（POST + fetch 流式读取）：连接、日志缓冲与自动滚动。
 * 结束语义与 api/tieba.startTiebaSync 一致：收到 [done]、流结束或连接出错
 * 即视为完成（不重连），随后回调 onSynced 让调用方刷新数据。
 * 组件卸载或重入时主动中止旧流：被中止的流不再触发任何回调
 * （不会误清新流状态，也不会在卸载后多发一次 onSynced 刷新）；
 * 服务端的抓取任务可能继续执行至完成。
 */
export function useTiebaSync(onSynced: () => void) {
  const syncing = ref(false)
  const syncLog = ref<string[]>([])
  const logEl = ref<HTMLPreElement | null>(null)
  let stream: TiebaSyncStream | null = null

  function startSync(forum: string | null) {
    stream?.close()
    syncing.value = true
    syncLog.value = [`▶ 开始同步${forum ? ' ' + forum + '吧' : '全部贴吧'}…`]
    stream = startTiebaSync(
      forum || '',
      (msg) => {
        syncLog.value.push(msg)
        nextTick(() => { if (logEl.value) logEl.value.scrollTop = logEl.value.scrollHeight })
      },
      () => {
        stream = null
        syncing.value = false
        onSynced()
      },
    )
  }

  function clearLog() {
    syncLog.value = []
  }

  onScopeDispose(() => {
    stream?.close()
    stream = null
    syncing.value = false
  })

  return { syncing, syncLog, logEl, startSync, clearLog }
}
