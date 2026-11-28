// LightField 场景/舞台：粒子物理、指针斥力场、指针星座牵丝、流动极光、星速跃迁与双环声呐
import {
  COLOR_LERP,
  GLOW_RADIUS,
  HALO_LERP,
  LAYER_SHIFT,
  LINK_MAX_PARTICLES,
  PARALLAX,
  REPEL_RADIUS,
  REPEL_STRENGTH,
  RIPPLE_DURATION_MS,
  SONAR_DURATION_MS,
  SONAR_MAX_RINGS,
  SPRING_DAMP,
  SPRING_K,
  isMobile,
  resolveDomainPalette,
  type Particle,
  type RGB,
  type ScreenPoint,
  type SonarRing,
} from './config'
import {
  drawAuroraMesh,
  drawCursorConstellation,
  drawLinks,
  drawMouseHalo,
  drawRays,
  drawSonarRings,
} from './decor'
import { drawParticleShape } from './shapes'
import type { SonarEvent, WarpDirection } from '../../../lib/lightFieldBus'

/** 主题与模式开关由组件以 getter 形式注入，舞台内部不直接依赖 Vue 响应式 */
export interface StageFlags {
  isDark: () => boolean
  isShowcase: () => boolean
}

function lerpRgb(cur: RGB, target: RGB, step: number) {
  cur[0] += (target[0] - cur[0]) * step
  cur[1] += (target[1] - cur[1]) * step
  cur[2] += (target[2] - cur[2]) * step
}

export function createLightFieldStage(flags: StageFlags) {
  let particles: Particle[] = []
  // 近层连线候选下标（初始化时截取，上限 LINK_MAX_PARTICLES）
  let linkIndices: number[] = []
  let mouseX = 0
  let mouseY = 0
  // 光晕位置独立 lerp，拖出平滑尾随
  let haloX = 0
  let haloY = 0
  let hasPointer = false
  let cx = 0
  let cy = 0
  let lastFrameMs = 0

  // 域染色状态：当前 RGB 逐帧平滑插值至目标域色
  let activeDomain = 'overview'
  const initPalette = resolveDomainPalette(activeDomain)
  const currentPrimary: RGB = [...initPalette.primary]
  const currentSecondary: RGB = [...initPalette.secondary]
  let targetPrimary: RGB = [...initPalette.primary]
  let targetSecondary: RGB = [...initPalette.secondary]

  // 路由切换 / 登录解锁星速跃迁冲量（~240ms 指数衰减）
  let warpEnergy = 0
  let warpSign = 1

  // 双环声呐 / 点击水波列表
  const sonarRings: SonarRing[] = []

  function resetClock() {
    lastFrameMs = 0
  }

  function onMouseMove(e: MouseEvent) {
    mouseX = e.clientX
    mouseY = e.clientY
    hasPointer = true
  }

  /** 鼠标与光晕归位到视口中心（挂载时调用） */
  function centerPointer() {
    mouseX = cx
    mouseY = cy
    haloX = cx
    haloY = cy
    hasPointer = false
  }

  /** 切入静态/低动态模式前清理瞬态物理位移、波纹与跃迁，并将域色一步到位 */
  function settleStatic() {
    warpEnergy = 0
    sonarRings.length = 0
    for (const p of particles) {
      p.ox = 0
      p.oy = 0
      p.ovx = 0
      p.ovy = 0
    }
    currentPrimary[0] = targetPrimary[0]
    currentPrimary[1] = targetPrimary[1]
    currentPrimary[2] = targetPrimary[2]
    currentSecondary[0] = targetSecondary[0]
    currentSecondary[1] = targetSecondary[1]
    currentSecondary[2] = targetSecondary[2]
  }

  /** 切换当前工作域色彩目标（instant=true 用于静态/低动态模式一步到位） */
  function setDomain(domain: string, instant = false): boolean {
    const normalized = domain || 'overview'
    const changed = normalized !== activeDomain
    activeDomain = normalized
    const palette = resolveDomainPalette(normalized)
    targetPrimary = [...palette.primary]
    targetSecondary = [...palette.secondary]
    if (instant) {
      settleStatic()
    }
    return changed
  }

  /** 触发星速跃迁冲量（intensity=1 普通换页，1.8+ 用于登录解锁大跃迁） */
  function triggerWarp(direction: WarpDirection = 'switch', intensity = 1) {
    warpEnergy = Math.max(warpEnergy, Math.min(intensity, 2.2))
    warpSign = direction === 'back' ? -1 : 1
  }

  /** 对点击位置周围粒子施加瞬时径向冲量（在视差投影屏幕空间计算，边缘点击精准对齐） */
  function impulseParticles(ix: number, iy: number, radius: number, power: number) {
    const r2Max = radius * radius
    const px = (mouseX - cx) * PARALLAX
    const py = (mouseY - cy) * PARALLAX
    const safeCx = Math.max(cx, 1)
    const safeCy = Math.max(cy, 1)
    for (const p of particles) {
      const shift = LAYER_SHIFT[p.layer]
      const sx = p.x + px * shift * (1 + Math.abs(p.x - cx) / safeCx) + p.ox
      const sy = p.y + py * shift * (1 + Math.abs(p.y - cy) / safeCy) + p.oy
      const dx = sx - ix
      const dy = sy - iy
      const d2 = dx * dx + dy * dy
      if (d2 > 1 && d2 < r2Max) {
        const d = Math.sqrt(d2)
        const falloff = (1 - d / radius) * (0.65 + p.layer * 0.25)
        p.ovx += (dx / d) * power * falloff
        p.ovy += (dy / d) * power * falloff
      }
    }
  }

  /** 触发双环声呐或轻点水波 */
  function triggerSonar(event: SonarEvent) {
    const isRipple = event.kind === 'ripple'
    const x = typeof event.x === 'number' ? event.x : (hasPointer ? haloX : cx)
    const y = typeof event.y === 'number' ? event.y : (hasPointer ? haloY : cy)
    const scale = event.scale ?? 1
    const baseMax = isRipple
      ? 168
      : Math.min(Math.max(cx, cy) * 0.72, 420)
    const maxRadius = baseMax * scale
    const rgb: RGB = event.kind === 'error'
      ? [250, 81, 81]
      : event.kind === 'success'
        ? [...targetPrimary]
        : [...targetSecondary]

    if (sonarRings.length >= SONAR_MAX_RINGS) sonarRings.shift()
    sonarRings.push({
      x,
      y,
      radius: isRipple ? 6 : 14,
      maxRadius,
      ageMs: 0,
      durationMs: isRipple ? RIPPLE_DURATION_MS : SONAR_DURATION_MS,
      rgb,
      kind: event.kind,
    })

    // 同步给周围粒子轻微物理冲击
    impulseParticles(x, y, isRipple ? 180 : 240, isRipple ? 3.2 : 4.8)
  }

  /** 页面点击：发射轻点双环水波并轻推星尘 */
  function onPointerDown(e: PointerEvent) {
    if (e.button !== 0) return
    mouseX = e.clientX
    mouseY = e.clientY
    hasPointer = true
    triggerSonar({ x: e.clientX, y: e.clientY, kind: 'ripple' })
  }

  function initParticles(w: number, h: number) {
    // showcase 满强度；ambient 约七成半密度，保证可玩性与通透感
    const dark = flags.isDark()
    const base = dark
      ? (isMobile() ? 84 : 188)
      : (isMobile() ? 60 : 138)
    const count = Math.round(base * (flags.isShowcase() ? 1 : 0.76))
    particles = []
    linkIndices = []
    for (let i = 0; i < count; i++) {
      const layer = i % 3
      particles.push({
        x: Math.random() * w, y: Math.random() * h,
        ox: 0, oy: 0, ovx: 0, ovy: 0,
        r: (dark ? 0.65 + Math.random() * 1.45 : 0.8 + Math.random() * 2.4) * (1 + layer * 0.25),
        alpha: dark ? 0.34 + Math.random() * 0.36 : 0.24 + Math.random() * 0.28,
        vx: (dark ? (Math.random() - 0.5) * 0.32 : (Math.random() - 0.5) * 0.12) * (1 + layer * 0.4),
        vy: (dark ? (Math.random() - 0.5) * 0.22 : (Math.random() - 0.5) * 0.09) * (1 + layer * 0.4),
        twinkle: Math.random() * Math.PI * 2,
        tone: Math.random(),
        layer,
      })
      // 连线候选：只保留前 LINK_MAX_PARTICLES 个近层粒子，约束每帧 O(n²) 判定规模
      if (layer === 2 && linkIndices.length < LINK_MAX_PARTICLES) linkIndices.push(i)
    }
  }

  /** 视口尺寸变化：重设 canvas 位图尺寸与 DPR 变换，并重建粒子 */
  function resize(canvas: HTMLCanvasElement) {
    const dpr = Math.min(window.devicePixelRatio || 1, 2)
    canvas.width = Math.floor(window.innerWidth * dpr)
    canvas.height = Math.floor(window.innerHeight * dpr)
    canvas.getContext('2d')?.setTransform(dpr, 0, 0, dpr, 0, 0)
    cx = window.innerWidth / 2
    cy = window.innerHeight / 2
    initParticles(window.innerWidth, window.innerHeight)
  }

  /** 单帧编排：清屏 → 域色插值 → 流动极光 → 光束 → 光晕 → 声呐 → 粒子物理/投影 → 星座牵丝 → 粒子与星速拖尾 */
  function draw(canvas: HTMLCanvasElement, now: number): boolean {
    const ctx = canvas.getContext('2d')
    if (!ctx) return false

    const dark = flags.isDark()
    const showcase = flags.isShowcase()
    const dtMs = lastFrameMs ? Math.min(Math.max(now - lastFrameMs, 0), 50) : 16.667
    lastFrameMs = now
    // 归一化到 60fps 基准，保证 120Hz/240Hz 高刷屏与 60Hz 速率一致
    const frameScale = dtMs / 16.667
    const haloStep = 1 - Math.pow(1 - HALO_LERP, frameScale)
    const colorStep = 1 - Math.pow(1 - COLOR_LERP, frameScale)
    const dampPow = Math.pow(SPRING_DAMP, frameScale)
    const t = now * 0.001
    const w = window.innerWidth
    const h = window.innerHeight
    ctx.clearRect(0, 0, w, h)

    lerpRgb(currentPrimary, targetPrimary, colorStep)
    lerpRgb(currentSecondary, targetSecondary, colorStep)

    // 星速跃迁冲量按指数自然衰减（~240ms 时间常数）
    if (warpEnergy > 0.008) {
      warpEnergy *= Math.exp(-dtMs / 240)
    } else {
      warpEnergy = 0
    }

    // 推进双环声呐 / 水波
    for (let i = sonarRings.length - 1; i >= 0; i--) {
      const ring = sonarRings[i]
      ring.ageMs += dtMs
      if (ring.ageMs >= ring.durationMs) {
        sonarRings.splice(i, 1)
        continue
      }
      const p = ring.ageMs / ring.durationMs
      const eased = 1 - Math.pow(1 - p, 3)
      const startR = ring.kind === 'ripple' ? 6 : 14
      ring.radius = startR + (ring.maxRadius - startR) * eased
    }

    // 归一化鼠标位移，驱动三层视差
    const px = (mouseX - cx) * PARALLAX
    const py = (mouseY - cy) * PARALLAX

    drawAuroraMesh(ctx, t, w, h, dark, showcase, currentPrimary, currentSecondary, warpEnergy)
    drawRays(ctx, t, w, h, px, py, dark, showcase, currentPrimary, currentSecondary, warpEnergy * warpSign)

    haloX += (mouseX - haloX) * haloStep
    haloY += (mouseY - haloY) * haloStep
    drawMouseHalo(ctx, t, haloX, haloY, dark, showcase, currentPrimary, currentSecondary)

    drawSonarRings(ctx, sonarRings, dark)

    const alphaK = showcase ? 1.05 : 0.88
    const speedMult = 1 + warpEnergy * 4.2
    const warpDriftX = warpEnergy * warpSign * 7.8 * frameScale
    const warpDriftY = -warpEnergy * warpSign * 1.4 * frameScale
    const repelR2 = REPEL_RADIUS * REPEL_RADIUS

    // 计算全部粒子物理与屏幕坐标
    const pts: ScreenPoint[] = []
    for (const p of particles) {
      const layerBoost = 1 + p.layer * 0.55
      p.x += p.vx * frameScale * speedMult + warpDriftX * layerBoost
      p.y += p.vy * frameScale * speedMult + warpDriftY * layerBoost
      if (p.x < -16) p.x = w + 16
      if (p.x > w + 16) p.x = -16
      if (p.y < -16) p.y = h + 16
      if (p.y > h + 16) p.y = -16

      const dx = p.x - cx
      const dy = p.y - cy
      const shift = LAYER_SHIFT[p.layer]
      const baseSx = p.x + px * shift * (1 + Math.abs(dx) / Math.max(cx, 1))
      const baseSy = p.y + py * shift * (1 + Math.abs(dy) / Math.max(cy, 1))

      // 指针柔韧物理斥力场：靠近指针时温柔拨开，离开后弹簧回归原轨
      if (hasPointer) {
        const rdx = baseSx + p.ox - haloX
        const rdy = baseSy + p.oy - haloY
        const rd2 = rdx * rdx + rdy * rdy
        if (rd2 > 1 && rd2 < repelR2) {
          const rd = Math.sqrt(rd2)
          const force = (1 - rd / REPEL_RADIUS) * REPEL_STRENGTH * (0.55 + p.layer * 0.28) * frameScale
          p.ovx += (rdx / rd) * force
          p.ovy += (rdy / rd) * force
        }
      }

      // 胡克弹性回弹 + 阻尼
      p.ovx += -p.ox * SPRING_K * frameScale
      p.ovy += -p.oy * SPRING_K * frameScale
      p.ovx *= dampPow
      p.ovy *= dampPow
      p.ox += p.ovx * frameScale
      p.oy += p.ovy * frameScale
      // 收敛阈值置零避免微抖
      if (Math.abs(p.ox) < 0.02 && Math.abs(p.ovx) < 0.02) { p.ox = 0; p.ovx = 0 }
      if (Math.abs(p.oy) < 0.02 && Math.abs(p.ovy) < 0.02) { p.oy = 0; p.ovy = 0 }

      pts.push({
        sx: baseSx + p.ox,
        sy: baseSy + p.oy,
      })
    }

    if (dark) drawLinks(ctx, linkIndices.map((i) => pts[i]), currentPrimary)
    if (hasPointer) {
      drawCursorConstellation(ctx, haloX, haloY, pts, dark, showcase, currentPrimary, currentSecondary)
    }

    for (let i = 0; i < particles.length; i++) {
      const p = particles[i]
      const { sx, sy } = pts[i]

      const a = p.alpha + Math.sin(t * 0.65 + p.twinkle) * 0.11
      let alpha = Math.max(dark ? 0.09 : 0.05, a) * alphaK

      // 鼠标邻近增亮
      const mdx = sx - haloX
      const mdy = sy - haloY
      const md = Math.sqrt(mdx * mdx + mdy * mdy)
      if (hasPointer && md < GLOW_RADIUS) {
        alpha = Math.min(1, alpha * (1 + (1 - md / GLOW_RADIUS) * 1.85))
      }

      // 声呐/水波前经过粒子时清晰点亮星芒
      for (const ring of sonarRings) {
        const rd = Math.hypot(sx - ring.x, sy - ring.y)
        const waveDist = Math.abs(rd - ring.radius)
        if (waveDist < 48) {
          const boost = (1 - waveDist / 48) * (1 - ring.ageMs / ring.durationMs)
          alpha = Math.min(1, alpha + boost * 0.62)
        }
      }

      // 跃迁期间计算粒子星速拖尾向量
      let streakDx = 0
      let streakDy = 0
      if (warpEnergy > 0.05) {
        const layerLen = 1 + p.layer * 0.72
        streakDx = warpEnergy * warpSign * 26 * layerLen
        streakDy = -warpEnergy * warpSign * 4.5 * layerLen
      }

      drawParticleShape(ctx, p, sx, sy, alpha, t, dark, currentPrimary, streakDx, streakDy)
    }
    return true
  }

  return {
    onMouseMove,
    onPointerDown,
    centerPointer,
    resetClock,
    resize,
    draw,
    setDomain,
    settleStatic,
    triggerWarp,
    triggerSonar,
  }
}
