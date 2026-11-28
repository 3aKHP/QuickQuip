import { onBeforeUnmount, onMounted, watch } from 'vue'
import type { Ref } from 'vue'
import { useMotionPrefs } from './useMotionPrefs'

/**
 * 全站统一指针物理引擎（单监听器 + 时间归一化按需 RAF 阻尼插值）：
 * 在容器内监听 pointermove，统一驱动三类零侵入交互特性：
 * 1. `[data-glow-card]`：邻近 1.5px 镜面边框追光 + 表层漫反射（--mx / --my / --glow-opacity）
 * 2. `[data-tilt-card]`：阻尼弹簧 3D 透视微倾（±3.5°）+ 随倾角游走的镜面扫光（--glare-x / --glare-y / --glare-opacity）
 * 3. `[data-magnetic]`：指针悬停时的温柔微磁吸偏移（--mag-x / --mag-y，最大 ±3px）
 *
 * 所有插值按 60fps 基准做帧间隔归一化（120Hz/240Hz 高刷屏手感一致）；
 * 变换收敛后自动清除 inline transform / will-change 并停止 RAF（空闲 0 CPU）；
 * 低动态模式、系统 prefers-reduced-motion 或触屏设备（pointer: coarse）自动静默。
 */
const PROXIMITY_PX = 310
const DEFAULT_TILT_MAX_DEG = 3.6
const DEFAULT_MAG_MAX_PX = 3.2
const TILT_LERP = 0.16
const GLARE_POS_LERP = 0.22
const GLARE_OPACITY_LERP = 0.18
const MAG_LERP = 0.22
const TILT_EPS = 0.015
const MAG_EPS = 0.04

interface TiltState {
  rx: number
  ry: number
  trx: number
  try_: number
  gx: number
  gy: number
  tgx: number
  tgy: number
  go: number
  tgo: number
}

interface MagneticState {
  x: number
  y: number
  tx: number
  ty: number
}

function stepFactor(base60: number, frameScale: number): number {
  return 1 - Math.pow(1 - base60, frameScale)
}

export function usePointerGlow(containerRef: Ref<HTMLElement | null>) {
  const { lowMotion } = useMotionPrefs()

  let raf = 0
  let lastFrameMs = 0
  let pendingX = -9999
  let pendingY = -9999
  let hoveredTiltCard: HTMLElement | null = null
  let hoveredMagEl: HTMLElement | null = null
  let pointerInside = false
  let pointerDirty = false
  let attachedEl: HTMLElement | null = null
  let mutationObserver: MutationObserver | null = null
  let cachedGlowCards: HTMLElement[] = []
  let glowCardsDirty = true
  let reducedMql: MediaQueryList | null = null
  let coarseMql: MediaQueryList | null = null
  let systemReduced = false
  let coarsePointer = false

  const dirtyGlowCards = new Set<HTMLElement>()
  const tiltStates = new Map<HTMLElement, TiltState>()
  const magStates = new Map<HTMLElement, MagneticState>()

  function disabledByEnv(): boolean {
    return lowMotion.value || systemReduced || coarsePointer || typeof window === 'undefined'
  }

  function clearGlowCard(card: HTMLElement, removeProps: boolean) {
    if (removeProps) {
      card.style.removeProperty('--mx')
      card.style.removeProperty('--my')
      card.style.removeProperty('--glow-opacity')
    } else {
      card.style.setProperty('--glow-opacity', '0')
    }
  }

  function clearTiltCard(card: HTMLElement) {
    card.style.removeProperty('transform')
    card.style.removeProperty('will-change')
    card.style.removeProperty('--glare-x')
    card.style.removeProperty('--glare-y')
    card.style.removeProperty('--glare-opacity')
  }

  function clearMagnetic(el: HTMLElement) {
    el.style.removeProperty('--mag-x')
    el.style.removeProperty('--mag-y')
  }

  function clearAll(removeProps = false) {
    for (const card of dirtyGlowCards) clearGlowCard(card, removeProps)
    dirtyGlowCards.clear()
    for (const card of tiltStates.keys()) clearTiltCard(card)
    tiltStates.clear()
    for (const el of magStates.keys()) clearMagnetic(el)
    magStates.clear()
    hoveredTiltCard = null
    hoveredMagEl = null
  }

  function getGlowCards(): HTMLElement[] {
    if (!attachedEl) return []
    if (glowCardsDirty) {
      cachedGlowCards = attachedEl.matches('[data-glow-card]')
        ? [attachedEl]
        : Array.from(attachedEl.querySelectorAll<HTMLElement>('[data-glow-card]'))
      glowCardsDirty = false
    }
    return cachedGlowCards
  }

  function updateTargetsFromPointer() {
    if (!attachedEl) return
    const px = pendingX
    const py = pendingY

    // 1. Glow 邻近高光卡片：命中 DOM 缓存 + 先批量读取几何信息再批量写入样式，避免全树查询与 layout thrashing
    const glowCards = getGlowCards()

    const glowMeasurements: Array<{ card: HTMLElement; rect: DOMRect }> = []
    if (pointerInside) {
      for (const card of glowCards) {
        const rect = card.getBoundingClientRect()
        if (rect.width > 0 && rect.height > 0) {
          glowMeasurements.push({ card, rect })
        }
      }
    }

    // 同步读取当前直接命中的 tilt / magnetic 几何信息（避免再扫全 DOM）
    const activeTilt = pointerInside && hoveredTiltCard && hoveredTiltCard.isConnected && attachedEl.contains(hoveredTiltCard)
      ? hoveredTiltCard
      : null
    const activeTiltRect = activeTilt ? activeTilt.getBoundingClientRect() : null

    const activeMag = pointerInside && hoveredMagEl && hoveredMagEl.isConnected && attachedEl.contains(hoveredMagEl)
      && !(hoveredMagEl as HTMLButtonElement).disabled
      ? hoveredMagEl
      : null
    const activeMagRect = activeMag ? activeMag.getBoundingClientRect() : null

    // 批量写入 Glow 样式
    const stillNearGlow = new Set<HTMLElement>()
    for (const { card, rect } of glowMeasurements) {
      const dx = px < rect.left ? rect.left - px : px > rect.right ? px - rect.right : 0
      const dy = py < rect.top ? rect.top - py : py > rect.bottom ? py - rect.bottom : 0
      const dist = Math.hypot(dx, dy)
      if (dist <= PROXIMITY_PX) {
        const intensity = dist === 0 ? 1 : Math.max(0, 1 - dist / PROXIMITY_PX)
        card.style.setProperty('--mx', `${(px - rect.left).toFixed(1)}px`)
        card.style.setProperty('--my', `${(py - rect.top).toFixed(1)}px`)
        card.style.setProperty('--glow-opacity', intensity.toFixed(3))
        stillNearGlow.add(card)
        dirtyGlowCards.add(card)
      }
    }
    for (const card of dirtyGlowCards) {
      if (!stillNearGlow.has(card)) {
        clearGlowCard(card, false)
        dirtyGlowCards.delete(card)
      }
    }

    // 2. 更新 3D 微倾目标值
    if (activeTilt && activeTiltRect && activeTiltRect.width > 0 && activeTiltRect.height > 0) {
      const nx = Math.max(-1, Math.min(1, ((px - activeTiltRect.left) / activeTiltRect.width - 0.5) * 2))
      const ny = Math.max(-1, Math.min(1, ((py - activeTiltRect.top) / activeTiltRect.height - 0.5) * 2))
      const maxAttr = Number(activeTilt.dataset.tiltMax)
      const maxDeg = Number.isFinite(maxAttr) && maxAttr > 0 ? maxAttr : DEFAULT_TILT_MAX_DEG
      const st = tiltStates.get(activeTilt) ?? {
        rx: 0, ry: 0, trx: 0, try_: 0,
        gx: 50, gy: 50, tgx: 50, tgy: 50,
        go: 0, tgo: 0,
      }
      st.trx = -ny * maxDeg
      st.try_ = nx * maxDeg
      st.tgx = Math.max(0, Math.min(100, ((px - activeTiltRect.left) / activeTiltRect.width) * 100))
      st.tgy = Math.max(0, Math.min(100, ((py - activeTiltRect.top) / activeTiltRect.height) * 100))
      st.tgo = 1
      tiltStates.set(activeTilt, st)
    }
    for (const [card, st] of tiltStates) {
      if (card !== activeTilt) {
        st.trx = 0
        st.try_ = 0
        st.tgo = 0
      }
    }

    // 3. 更新微磁吸目标值（扣除当前平移偏移，消除 rect 自反馈衰减）
    if (activeMag && activeMagRect && activeMagRect.width > 0 && activeMagRect.height > 0) {
      const st = magStates.get(activeMag) ?? { x: 0, y: 0, tx: 0, ty: 0 }
      const baseLeft = activeMagRect.left - st.x
      const baseTop = activeMagRect.top - st.y
      const nx = Math.max(-1, Math.min(1, ((px - baseLeft) / activeMagRect.width - 0.5) * 2))
      const ny = Math.max(-1, Math.min(1, ((py - baseTop) / activeMagRect.height - 0.5) * 2))
      const maxAttr = Number(activeMag.dataset.magneticMax)
      const maxPx = Number.isFinite(maxAttr) && maxAttr > 0 ? maxAttr : DEFAULT_MAG_MAX_PX
      st.tx = nx * maxPx
      st.ty = ny * maxPx
      magStates.set(activeMag, st)
    }
    for (const [el, st] of magStates) {
      if (el !== activeMag) {
        st.tx = 0
        st.ty = 0
      }
    }
  }

  function tick(now: number) {
    raf = 0
    if (!attachedEl || disabledByEnv()) {
      lastFrameMs = 0
      clearAll(true)
      return
    }

    const dtMs = lastFrameMs ? Math.min(Math.max(now - lastFrameMs, 0), 50) : 16.667
    lastFrameMs = now
    const frameScale = dtMs / 16.667
    const tiltStep = stepFactor(TILT_LERP, frameScale)
    const glarePosStep = stepFactor(GLARE_POS_LERP, frameScale)
    const glareOpStep = stepFactor(GLARE_OPACITY_LERP, frameScale)
    const magStep = stepFactor(MAG_LERP, frameScale)

    if (pointerDirty) {
      pointerDirty = false
      updateTargetsFromPointer()
    }

    let needMoreFrames = false

    // 步进 3D 倾斜阻尼插值
    for (const [card, st] of tiltStates) {
      if (!card.isConnected) {
        tiltStates.delete(card)
        continue
      }
      st.rx += (st.trx - st.rx) * tiltStep
      st.ry += (st.try_ - st.ry) * tiltStep
      st.gx += (st.tgx - st.gx) * glarePosStep
      st.gy += (st.tgy - st.gy) * glarePosStep
      st.go += (st.tgo - st.go) * glareOpStep

      const settled =
        st.tgo === 0
        && Math.abs(st.rx) <= TILT_EPS
        && Math.abs(st.ry) <= TILT_EPS
        && st.go <= 0.01

      if (settled) {
        clearTiltCard(card)
        tiltStates.delete(card)
      } else {
        card.style.willChange = 'transform'
        card.style.transform = `perspective(920px) rotateX(${st.rx.toFixed(2)}deg) rotateY(${st.ry.toFixed(2)}deg)`
        card.style.setProperty('--glare-x', `${st.gx.toFixed(1)}%`)
        card.style.setProperty('--glare-y', `${st.gy.toFixed(1)}%`)
        card.style.setProperty('--glare-opacity', st.go.toFixed(3))
        if (
          Math.abs(st.trx - st.rx) > TILT_EPS
          || Math.abs(st.try_ - st.ry) > TILT_EPS
          || Math.abs(st.tgo - st.go) > 0.008
          || Math.abs(st.tgx - st.gx) > 0.2
          || Math.abs(st.tgy - st.gy) > 0.2
        ) {
          needMoreFrames = true
        }
      }
    }

    // 步进微磁吸阻尼插值
    for (const [el, st] of magStates) {
      if (!el.isConnected) {
        magStates.delete(el)
        continue
      }
      st.x += (st.tx - st.x) * magStep
      st.y += (st.ty - st.y) * magStep
      const settled =
        st.tx === 0
        && st.ty === 0
        && Math.abs(st.x) <= MAG_EPS
        && Math.abs(st.y) <= MAG_EPS

      if (settled) {
        clearMagnetic(el)
        magStates.delete(el)
      } else {
        el.style.setProperty('--mag-x', `${st.x.toFixed(2)}px`)
        el.style.setProperty('--mag-y', `${st.y.toFixed(2)}px`)
        if (Math.abs(st.tx - st.x) > MAG_EPS || Math.abs(st.ty - st.y) > MAG_EPS) {
          needMoreFrames = true
        }
      }
    }

    if (needMoreFrames || pointerDirty) {
      raf = requestAnimationFrame(tick)
    } else {
      lastFrameMs = 0
    }
  }

  function scheduleTick() {
    if (!raf) raf = requestAnimationFrame(tick)
  }

  function onPointerMove(e: PointerEvent) {
    if (e.pointerType === 'touch' || disabledByEnv()) return
    pointerInside = true
    pendingX = e.clientX
    pendingY = e.clientY
    const target = e.target instanceof Element ? e.target : null
    hoveredTiltCard = target ? target.closest<HTMLElement>('[data-tilt-card]') : null
    hoveredMagEl = target ? target.closest<HTMLElement>('[data-magnetic]') : null
    pointerDirty = true
    scheduleTick()
  }

  function releasePointer() {
    if (!pointerInside && !hoveredTiltCard && !hoveredMagEl && !dirtyGlowCards.size) return
    pointerInside = false
    hoveredTiltCard = null
    hoveredMagEl = null
    pointerDirty = true
    scheduleTick()
  }

  function detach() {
    if (raf) {
      cancelAnimationFrame(raf)
      raf = 0
    }
    lastFrameMs = 0
    mutationObserver?.disconnect()
    mutationObserver = null
    cachedGlowCards = []
    glowCardsDirty = true
    if (attachedEl) {
      attachedEl.removeEventListener('pointermove', onPointerMove)
      attachedEl.removeEventListener('pointerleave', releasePointer)
      window.removeEventListener('blur', releasePointer)
      attachedEl = null
    }
    pointerInside = false
    pointerDirty = false
    clearAll(true)
  }

  function attach(el: HTMLElement | null) {
    if (el === attachedEl) return
    detach()
    if (!el || disabledByEnv()) return
    attachedEl = el
    glowCardsDirty = true
    if (typeof MutationObserver !== 'undefined') {
      mutationObserver = new MutationObserver(() => {
        glowCardsDirty = true
      })
      mutationObserver.observe(el, { childList: true, subtree: true })
    }
    el.addEventListener('pointermove', onPointerMove, { passive: true })
    el.addEventListener('pointerleave', releasePointer, { passive: true })
    window.addEventListener('blur', releasePointer)
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
