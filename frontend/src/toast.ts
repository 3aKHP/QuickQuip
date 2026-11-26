import { ref } from 'vue'
import type { Ref } from 'vue'

export type ToastType = 'info' | 'error'

export const toastMsg: Ref<string | null> = ref(null)
export const toastType: Ref<ToastType> = ref('info')

let _timer: ReturnType<typeof setTimeout> | null = null
let _remaining = 2600
let _startedAt = 0

function scheduleDismiss(ms: number): void {
  if (_timer) clearTimeout(_timer)
  _remaining = ms
  _startedAt = Date.now()
  _timer = setTimeout(() => {
    toastMsg.value = null
    _timer = null
  }, ms)
}

export function dismissToast(): void {
  if (_timer) {
    clearTimeout(_timer)
    _timer = null
  }
  toastMsg.value = null
}

export function pauseToast(): void {
  if (!_timer) return
  clearTimeout(_timer)
  _timer = null
  _remaining = Math.max(400, _remaining - (Date.now() - _startedAt))
}

export function resumeToast(): void {
  if (!toastMsg.value || _timer) return
  scheduleDismiss(_remaining)
}

export function toast(msg: string, type: ToastType = 'info', duration?: number): void {
  const effectiveDuration = duration ?? (type === 'error' ? 4200 : 2600)
  toastMsg.value = msg
  toastType.value = type
  scheduleDismiss(effectiveDuration)
}
