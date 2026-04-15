import { ref } from 'vue'

export const toastMsg = ref(null)
export const toastType = ref('info') // 'info' | 'error'

let _timer = null
export function toast(msg, type = 'info', duration = 2500) {
  if (_timer) clearTimeout(_timer)
  toastMsg.value = msg
  toastType.value = type
  _timer = setTimeout(() => { toastMsg.value = null }, duration)
}
