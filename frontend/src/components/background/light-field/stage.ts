// LightField 场景/舞台：粒子物理、三层视差投影与主循环单帧编排
import {
  GLOW_RADIUS,
  HALO_LERP,
  LAYER_SHIFT,
  LINK_MAX_PARTICLES,
  PARALLAX,
  isMobile,
  type Particle,
  type ScreenPoint,
} from './config'
import { drawBaseWash, drawLinks, drawMouseHalo, drawRays } from './decor'
import { drawParticleShape } from './shapes'

/** 主题与模式开关由组件以 getter 形式注入，舞台内部不直接依赖 Vue 响应式 */
export interface StageFlags {
  isDark: () => boolean
  isShowcase: () => boolean
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
  let cx = 0
  let cy = 0

  function onMouseMove(e: MouseEvent) {
    mouseX = e.clientX
    mouseY = e.clientY
  }

  /** 鼠标与光晕归位到视口中心（挂载时调用） */
  function centerPointer() {
    mouseX = cx
    mouseY = cy
    haloX = cx
    haloY = cy
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

  /** 单帧编排：清屏 → 装饰层 → 粒子物理/投影 → 粒子形态；RAF 调度由组件负责；返回 false 表示本帧未绘制 */
  function draw(canvas: HTMLCanvasElement, now: number): boolean {
    const ctx = canvas.getContext('2d')
    if (!ctx) return false

    const dark = flags.isDark()
    const showcase = flags.isShowcase()
    const t = now * 0.001
    const w = window.innerWidth
    const h = window.innerHeight
    ctx.clearRect(0, 0, w, h)

    // 归一化鼠标位移，驱动三层视差
    const px = (mouseX - cx) * PARALLAX
    const py = (mouseY - cy) * PARALLAX

    if (!dark) drawBaseWash(ctx, w, h, showcase)
    drawRays(ctx, t, w, h, px, py, dark, showcase)

    haloX += (mouseX - haloX) * HALO_LERP
    haloY += (mouseY - haloY) * HALO_LERP
    drawMouseHalo(ctx, t, haloX, haloY, dark, showcase)

    const alphaK = showcase ? 1 : 0.85

    // 先算全部粒子屏幕坐标（暗色连线要用）
    const pts: ScreenPoint[] = []
    for (const p of particles) {
      p.x += p.vx
      p.y += p.vy
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

    if (dark) drawLinks(ctx, linkIndices.map((i) => pts[i]))

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

      drawParticleShape(ctx, p, sx, sy, alpha, t, dark)
    }
    return true
  }

  return { onMouseMove, centerPointer, resize, draw }
}
