import { onUnmounted, ref, watch } from 'vue'
import type { Ref } from 'vue'

/**
 * 数字滚动：目标值变化时以 ease-out 曲线从当前值过渡到新值。
 * prefers-reduced-motion 下直接跳到目标值。
 */
export function useCountUp(target: () => number | undefined, duration = 600): Ref<number> {
  const display = ref(0)
  let raf = 0

  function reducedMotion(): boolean {
    return window.matchMedia('(prefers-reduced-motion: reduce)').matches
  }

  watch(
    target,
    (to) => {
      if (to === undefined || !Number.isFinite(to)) return
      if (raf) cancelAnimationFrame(raf)
      const from = display.value
      if (reducedMotion() || from === to) {
        display.value = to
        return
      }
      const start = performance.now()
      const tick = (now: number) => {
        const p = Math.min(1, (now - start) / duration)
        const eased = 1 - Math.pow(1 - p, 3)
        display.value = from + (to - from) * eased
        if (p < 1) raf = requestAnimationFrame(tick)
        else raf = 0
      }
      raf = requestAnimationFrame(tick)
    },
    { immediate: true },
  )

  onUnmounted(() => {
    if (raf) cancelAnimationFrame(raf)
  })

  return display
}
