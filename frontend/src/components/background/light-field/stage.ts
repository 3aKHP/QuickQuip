// LightField 场景/舞台：粒子物理、三层视差投影、域染色插值、换页跃迁与声呐波纹
import {
  COLOR_LERP,
  GLOW_RADIUS,
  HALO_LERP,
  LAYER_SHIFT,
  LINK_MAX_PARTICLES,
  PARALLAX,
  SONAR_DURATION_MS,
  SONAR_MAX_RINGS,
  isMobile,
  resolveDomainPalette,
  type Particle,
  type RGB,
  type ScreenPoint,
  type SonarRing,
} from './config'
import { drawBaseWash, drawLinks, drawMouseHalo, drawRays, drawSonarRings } from './decor'
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

  // 路由切换跃迁冲量（~320ms 指数衰减）
  let warpEnergy = 0
  let warpSign = 1

  // 声呐脉冲环列表
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

  /** 切入静态/低动态模式前清理瞬态波纹与跃迁，并将域色一步到位 */
  function settleStatic() {
    warpEnergy = 0
    sonarRings.length = 0
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

  /** 触发短暂的换页速度跃迁冲量 */
  function triggerWarp(direction: WarpDirection = 'switch') {
    warpEnergy = 1
    warpSign = direction === 'back' ? -1 : 1
  }

  /** 触发克制的声呐脉冲环 */
  function triggerSonar(event: SonarEvent) {
    const x = typeof event.x === 'number' ? event.x : (hasPointer ? haloX : cx)
    const y = typeof event.y === 'number' ? event.y : (hasPointer ? haloY : cy)
    const maxRadius = Math.min(Math.max(cx, cy) * 0.65, 360)
    const rgb: RGB = event.kind === 'error'
      ? [250, 81, 81]
      : event.kind === 'success'
        ? [...targetPrimary]
        : [...targetSecondary]

    if (sonarRings.length >= SONAR_MAX_RINGS) sonarRings.shift()
    sonarRings.push({
      x,
      y,
      radius: 12,
      maxRadius,
      ageMs: 0,
      durationMs: SONAR_DURATION_MS,
      rgb,
    })
  }

  function initParticles(w: number, h: number) {
    // showcase 满强度；ambient 约七成密度，保持可感知
    const dark = flags.isDark()
    const base = dark
      ? (isMobile() ? 80 : 180)
      : (isMobile() ? 56 : 132)
    const count = Math.round(base * (flags.isShowcase() ? 1 : 0.7))
    particles = []
    linkIndices = []
    for (let i = 0; i < count; i++) {
      const layer = i % 3
      particles.push({
        x: Math.random() * w, y: Math.random() * h,
        r: (dark ? 0.6 + Math.random() * 1.4 : 0.8 + Math.random() * 2.4) * (1 + layer * 0.25),
        alpha: dark ? 0.30 + Math.random() * 0.35 : 0.22 + Math.random() * 0.26,
        vx: (dark ? (Math.random() - 0.5) * 0.30 : (Math.random() - 0.5) * 0.10) * (1 + layer * 0.4),
        vy: (dark ? (Math.random() - 0.5) * 0.20 : (Math.random() - 0.5) * 0.08) * (1 + layer * 0.4),
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
    // 粒子坐标在 CSS 像素空间计算，绘制时整体缩放
    canvas.getContext('2d')?.setTransform(dpr, 0, 0, dpr, 0, 0)
    cx = window.innerWidth / 2
    cy = window.innerHeight / 2
    initParticles(window.innerWidth, window.innerHeight)
  }

  /** 单帧编排：清屏 → 域色插值 → 装饰层 → 声呐环 → 粒子物理/投影 → 粒子形态 */
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
    const t = now * 0.001
    const w = window.innerWidth
    const h = window.innerHeight
    ctx.clearRect(0, 0, w, h)

    lerpRgb(currentPrimary, targetPrimary, colorStep)
    lerpRgb(currentSecondary, targetSecondary, colorStep)

    // 换页跃迁冲量按指数自然衰减
    if (warpEnergy > 0.005) {
      warpEnergy *= Math.exp(-dtMs / 150)
    } else {
      warpEnergy = 0
    }

    // 推进声呐脉冲环
    for (let i = sonarRings.length - 1; i >= 0; i--) {
      const ring = sonarRings[i]
      ring.ageMs += dtMs
      if (ring.ageMs >= ring.durationMs) {
        sonarRings.splice(i, 1)
        continue
      }
      const p = ring.ageMs / ring.durationMs
      const eased = 1 - Math.pow(1 - p, 3)
      ring.radius = 12 + (ring.maxRadius - 12) * eased
    }

    // 归一化鼠标位移，驱动三层视差
    const px = (mouseX - cx) * PARALLAX
    const py = (mouseY - cy) * PARALLAX

    if (!dark) drawBaseWash(ctx, w, h, showcase, currentPrimary, currentSecondary)
    drawRays(ctx, t, w, h, px, py, dark, showcase, currentPrimary, currentSecondary, warpEnergy * warpSign)

    haloX += (mouseX - haloX) * haloStep
    haloY += (mouseY - haloY) * haloStep
    drawMouseHalo(ctx, t, haloX, haloY, dark, showcase, currentPrimary, currentSecondary)

    drawSonarRings(ctx, sonarRings, dark)

    const alphaK = showcase ? 1 : 0.85
    const speedMult = 1 + warpEnergy * 2.4
    const warpDriftX = warpEnergy * warpSign * 1.15 * frameScale

    // 先算全部粒子屏幕坐标（暗色连线要用）
    const pts: ScreenPoint[] = []
    for (const p of particles) {
      const layerBoost = 1 + p.layer * 0.35
      p.x += p.vx * frameScale * speedMult + warpDriftX * layerBoost
      p.y += p.vy * frameScale * speedMult
      if (p.x < -10) p.x = w + 10
      if (p.x > w + 10) p.x = -10
      if (p.y < -10) p.y = h + 10
      if (p.y > h + 10) p.y = -10

      const dx = p.x - cx
      const dy = p.y - cy
      const shift = LAYER_SHIFT[p.layer]
      pts.push({
        sx: p.x + px * shift * (1 + Math.abs(dx) / Math.max(cx, 1)),
        sy: p.y + py * shift * (1 + Math.abs(dy) / Math.max(cy, 1)),
      })
    }

    if (dark) drawLinks(ctx, linkIndices.map((i) => pts[i]), currentPrimary)

    for (let i = 0; i < particles.length; i++) {
      const p = particles[i]
      const { sx, sy } = pts[i]

      const a = p.alpha + Math.sin(t * 0.6 + p.twinkle) * 0.1
      let alpha = Math.max(dark ? 0.08 : 0.04, a) * alphaK

      // 鼠标邻近增亮：粒子自身变亮
      const mdx = sx - haloX
      const mdy = sy - haloY
      const md = Math.sqrt(mdx * mdx + mdy * mdy)
      if (md < GLOW_RADIUS) alpha = Math.min(1, alpha * (1 + (1 - md / GLOW_RADIUS) * 1.6))

      // 声呐波前经过粒子时短暂点亮
      for (const ring of sonarRings) {
        const rd = Math.hypot(sx - ring.x, sy - ring.y)
        const waveDist = Math.abs(rd - ring.radius)
        if (waveDist < 42) {
          const boost = (1 - waveDist / 42) * (1 - ring.ageMs / ring.durationMs)
          alpha = Math.min(1, alpha + boost * 0.42)
        }
      }

      drawParticleShape(ctx, p, sx, sy, alpha, t, dark)
    }
    return true
  }

  return {
    onMouseMove,
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
