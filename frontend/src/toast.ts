import { ref } from 'vue'
import type { Ref } from 'vue'

export type ToastType = 'info' | 'error'

export const toastMsg: Ref<string | null> = ref(null)
export const toastType: Ref<ToastType> = ref('info')

let _timer: ReturnType<typeof setTimeout> | null = null
export function toast(msg: string, type: ToastType = 'info', duration = 2500): void {
  if (_timer) clearTimeout(_timer)
  toastMsg.value = msg
  toastType.value = type
  _timer = setTimeout(() => { toastMsg.value = null }, duration)
}
