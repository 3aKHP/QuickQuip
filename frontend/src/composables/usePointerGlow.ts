import { onBeforeUnmount, onMounted, watch } from 'vue'
import type { Ref } from 'vue'
import { useMotionPrefs } from './useMotionPrefs'

/**
 * 容器级指针高光追光（单监听器 + RAF 节流）：
 * 在容器内监听 pointermove，按邻近距离更新 `[data-glow-card]` 元素的
 * `--mx` / `--my` / `--glow-opacity` 变量，形成克制的 1px 玻璃边缘高光。
 *
 * 低动态模式、系统 prefers-reduced-motion 或触屏设备（pointer: coarse）自动静默。
 */
const PROXIMITY_PX = 280

export function usePointerGlow(containerRef: Ref<HTMLElement | null>) {
  const { lowMotion } = useMotionPrefs()

  let raf = 0
  let pendingX = 0
  let pendingY = 0
  let active = false
  let attachedEl: HTMLElement | null = null
  let reducedMql: MediaQueryList | null = null
  let coarseMql: MediaQueryList | null = null
  let systemReduced = false
  let coarsePointer = false
  const dirtyCards = new Set<HTMLElement>()

  function disabledByEnv(): boolean {
    return lowMotion.value || systemReduced || coarsePointer || typeof window === 'undefined'
  }

  function clearCards(removeProps = false) {
    for (const card of dirtyCards) {
      if (removeProps) {
        card.style.removeProperty('--mx')
        card.style.removeProperty('--my')
        card.style.removeProperty('--glow-opacity')
      } else {
        card.style.setProperty('--glow-opacity', '0')
      }
    }
    dirtyCards.clear()
  }

  function flush() {
    raf = 0
    if (!attachedEl || !active || disabledByEnv()) {
      clearCards()
      return
    }
    const cards = attachedEl.matches('[data-glow-card]')
      ? [attachedEl]
      : Array.from(attachedEl.querySelectorAll<HTMLElement>('[data-glow-card]'))

    const stillNear = new Set<HTMLElement>()
    for (const card of cards) {
      const rect = card.getBoundingClientRect()
      const dx = pendingX < rect.left
        ? rect.left - pendingX
        : pendingX > rect.right
          ? pendingX - rect.right
          : 0
      const dy = pendingY < rect.top
        ? rect.top - pendingY
        : pendingY > rect.bottom
          ? pendingY - rect.bottom
          : 0
      const dist = Math.hypot(dx, dy)
      if (dist <= PROXIMITY_PX) {
        const intensity = dist === 0 ? 1 : Math.max(0, 1 - dist / PROXIMITY_PX)
        card.style.setProperty('--mx', `${(pendingX - rect.left).toFixed(1)}px`)
        card.style.setProperty('--my', `${(pendingY - rect.top).toFixed(1)}px`)
        card.style.setProperty('--glow-opacity', intensity.toFixed(3))
        stillNear.add(card)
        dirtyCards.add(card)
      }
    }

    for (const card of dirtyCards) {
      if (!stillNear.has(card)) {
        card.style.setProperty('--glow-opacity', '0')
        dirtyCards.delete(card)
      }
    }
  }

  function onPointerMove(e: PointerEvent) {
    if (e.pointerType === 'touch' || disabledByEnv()) return
    active = true
    pendingX = e.clientX
    pendingY = e.clientY
    if (!raf) raf = requestAnimationFrame(flush)
  }

  function onPointerLeave() {
    active = false
    if (raf) {
      cancelAnimationFrame(raf)
      raf = 0
    }
    clearCards()
  }

  function detach() {
    if (raf) {
      cancelAnimationFrame(raf)
      raf = 0
    }
    if (attachedEl) {
      attachedEl.removeEventListener('pointermove', onPointerMove)
      attachedEl.removeEventListener('pointerleave', onPointerLeave)
      attachedEl = null
    }
    clearCards(true)
  }

  function attach(el: HTMLElement | null) {
    if (el === attachedEl) return
    detach()
    if (!el || disabledByEnv()) return
    attachedEl = el
    el.addEventListener('pointermove', onPointerMove, { passive: true })
    el.addEventListener('pointerleave', onPointerLeave, { passive: true })
  }

  function syncMediaState() {
    systemReduced = Boolean(reducedMql?.matches)
    coarsePointer = Boolean(coarseMql?.matches)
    if (disabledByEnv()) detach()
    else attach(containerRef.value)
  }

  onMounted(() => {
    try {
      reducedMql = window.matchMedia('(prefers-reduced-motion: reduce)')
      coarseMql = window.matchMedia('(pointer: coarse)')
      systemReduced = reducedMql.matches
      coarsePointer = coarseMql.matches
      reducedMql.addEventListener('change', syncMediaState)
      coarseMql.addEventListener('change', syncMediaState)
    } catch { /* ignore */ }
    attach(containerRef.value)
  })

  watch(containerRef, (el) => attach(el))
  watch(lowMotion, () => {
    if (disabledByEnv()) detach()
    else attach(containerRef.value)
  })

  onBeforeUnmount(() => {
    reducedMql?.removeEventListener('change', syncMediaState)
    coarseMql?.removeEventListener('change', syncMediaState)
    detach()
  })
}
