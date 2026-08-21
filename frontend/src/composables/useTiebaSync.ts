import { ref, nextTick } from 'vue'
import { openTiebaSyncStream } from '../api/tieba'

/**
 * 贴吧同步流（SSE）生命周期：连接、日志缓冲、自动滚动与清理。
 * 结束语义与 api/tieba.openTiebaSyncStream 一致：收到 [done] 或连接出错
 * 即关闭流并视为完成（不重连），随后回调 onSynced 让调用方刷新数据。
 */
export function useTiebaSync(onSynced: () => void) {
  const syncing = ref(false)
  const syncLog = ref<string[]>([])
  const logEl = ref<HTMLPreElement | null>(null)

  function startSync(forum: string | null) {
    syncing.value = true
    syncLog.value = [`▶ 开始同步${forum ? ' ' + forum + '吧' : '全部贴吧'}…`]
    openTiebaSyncStream(
      forum || '',
      (msg) => {
        syncLog.value.push(msg)
        nextTick(() => { if (logEl.value) logEl.value.scrollTop = logEl.value.scrollHeight })
      },
      () => {
        syncing.value = false
        onSynced()
      },
    )
  }

  function clearLog() {
    syncLog.value = []
  }

  return { syncing, syncLog, logEl, startSync, clearLog }
}
