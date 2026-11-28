// LightField 装饰层（高性能无冗余渐变版）：光束/圆弧、鼠标光晕、指针星座牵丝、暗色连线与双环声呐
// 流动极光底幕由 LightField.vue 的纯 GPU 合成 CSS 层渲染，避免每帧 3 次全屏像素填充。
import {
  CURSOR_LINK_MAX,
  CURSOR_LINK_RADIUS,
  LINK_MAX,
  type RGB,
  type ScreenPoint,
  type SonarRing,
} from './config'

function rgba(rgb: RGB, alpha: number): string {
  return `rgba(${Math.round(rgb[0])}, ${Math.round(rgb[1])}, ${Math.round(rgb[2])}, ${alpha.toFixed(3)})`
}

// 鼠标光晕：随域色过渡的径向微光；位置由调用方 lerp 后传入
export function drawMouseHalo(
  ctx: CanvasRenderingContext2D,
  t: number,
  haloX: number,
  haloY: number,
  isDark: boolean,
  isShowcase: boolean,
  primaryRgb: RGB,
  secondaryRgb: RGB,
) {
  const breathe = 1 + Math.sin(t * 0.9) * 0.06
  const k = isShowcase ? 1.08 : 0.82
  const radius = (isDark ? 340 : 280) * breathe
  const g = ctx.createRadialGradient(haloX, haloY, 0, haloX, haloY, radius)
  if (isDark) {
    g.addColorStop(0, rgba(primaryRgb, 0.24 * k))
    g.addColorStop(0.45, rgba(secondaryRgb, 0.10 * k))
    g.addColorStop(1, rgba(secondaryRgb, 0))
  } else {
    g.addColorStop(0, rgba(primaryRgb, 0.16 * k))
    g.addColorStop(0.45, rgba(secondaryRgb, 0.07 * k))
    g.addColorStop(1, rgba(secondaryRgb, 0))
  }
  ctx.fillStyle = g
  ctx.fillRect(haloX - radius, haloY - radius, radius * 2, radius * 2)
}

// 指针星座牵丝：零 CanvasGradient 分配，按距离直接着色并批量绘点
export function drawCursorConstellation(
  ctx: CanvasRenderingContext2D,
  haloX: number,
  haloY: number,
  pts: ScreenPoint[],
  isDark: boolean,
  isShowcase: boolean,
  primaryRgb: RGB,
  secondaryRgb: RGB,
) {
  const r2Max = CURSOR_LINK_RADIUS * CURSOR_LINK_RADIUS
  const candidates: Array<{ sx: number; sy: number; d2: number }> = []

  for (let i = 0; i < pts.length; i++) {
    const dx = pts[i].sx - haloX
    const dy = pts[i].sy - haloY
    const d2 = dx * dx + dy * dy
    if (d2 > 36 && d2 < r2Max) {
      candidates.push({ sx: pts[i].sx, sy: pts[i].sy, d2 })
    }
  }
  if (!candidates.length) return

  if (candidates.length > CURSOR_LINK_MAX) {
    candidates.sort((a, b) => a.d2 - b.d2)
    candidates.length = CURSOR_LINK_MAX
  }

  ctx.save()
  ctx.lineWidth = isDark ? 0.9 : 0.85
  const peakAlpha = (isDark ? 0.42 : 0.28) * (isShowcase ? 1.1 : 0.92)
  for (const c of candidates) {
    const ratio = 1 - Math.sqrt(c.d2) / CURSOR_LINK_RADIUS
    const alpha = ratio * ratio * peakAlpha
    if (alpha <= 0.012) continue

    ctx.strokeStyle = rgba(secondaryRgb, alpha * 0.72)
    ctx.beginPath()
    ctx.moveTo(haloX, haloY)
    ctx.lineTo(c.sx, c.sy)
    ctx.stroke()

    ctx.fillStyle = rgba(primaryRgb, Math.min(0.85, alpha * 1.35))
    ctx.beginPath()
    ctx.arc(c.sx, c.sy, 1.5, 0, Math.PI * 2)
    ctx.fill()
  }
  ctx.restore()
}

// 光束与大圆弧：随当前工作域微染；换页跃迁时瞬间增亮拉伸
export function drawRays(
  ctx: CanvasRenderingContext2D,
  t: number,
  w: number,
  h: number,
  px: number,
  py: number,
  isDark: boolean,
  isShowcase: boolean,
  primaryRgb: RGB,
  secondaryRgb: RGB,
  warpBoost = 0,
) {
  ctx.save()
  ctx.globalCompositeOperation = 'source-over'
  ctx.lineCap = 'round'
  ctx.lineJoin = 'round'

  const absWarp = Math.min(Math.abs(warpBoost), 1.8)
  const driftX = px * 0.95 + Math.sin(t * 0.18) * 18 + warpBoost * 34
  const driftY = py * 0.7 + Math.cos(t * 0.14) * 14

  const k = (isDark ? 0.65 : 1.05) * (isShowcase ? 1 : 0.68) * (1 + absWarp * 0.45)
  const rays = [
    { y: h * 0.20, slope: 0.10, color: rgba(primaryRgb, 0.20 * k), width: 1.25 },
    { y: h * 0.42, slope: -0.13, color: rgba(secondaryRgb, 0.18 * k), width: 1.05 },
    { y: h * 0.66, slope: 0.08, color: rgba(primaryRgb, 0.14 * k), width: 1.0 },
    { y: h * 0.82, slope: -0.05, color: `rgba(245, 158, 11, ${(0.09 * k).toFixed(3)})`, width: 1.0 },
  ]

  for (const ray of rays) {
    ctx.strokeStyle = ray.color
    ctx.lineWidth = ray.width
    ctx.beginPath()
    ctx.moveTo(-40, ray.y + driftY)
    ctx.bezierCurveTo(
      w * 0.28 + driftX,
      ray.y + h * ray.slope,
      w * 0.66 - driftX * 0.4,
      ray.y - h * ray.slope,
      w + 40,
      ray.y + driftY * 0.3,
    )
    ctx.stroke()
  }

  const arcK = (isDark ? 0.56 : 1) * (isShowcase ? 1 : 0.7) * (1 + absWarp * 0.35)
  const centers = [
    { x: w * 0.22 + driftX * 0.22, y: h * 0.23 + driftY * 0.18, r: Math.min(w, h) * 0.16, c: rgba(primaryRgb, 0.15 * arcK) },
    { x: w * 0.76 - driftX * 0.16, y: h * 0.58 - driftY * 0.12, r: Math.min(w, h) * 0.22, c: `rgba(245, 158, 11, ${(0.11 * arcK).toFixed(3)})` },
  ]
  for (const arc of centers) {
    ctx.strokeStyle = arc.c
    ctx.lineWidth = 1
    ctx.beginPath()
    ctx.arc(arc.x, arc.y, arc.r, -0.25 + Math.sin(t * 0.14) * 0.08, Math.PI * 1.15)
    ctx.stroke()
    ctx.beginPath()
    ctx.arc(arc.x, arc.y, arc.r * 0.62, Math.PI * 0.12, Math.PI * 1.72 + Math.cos(t * 0.12) * 0.08)
    ctx.stroke()
  }

  ctx.restore()
}

// 暗色：近层候选粒子之间连线（候选由调用方按上限截断），星座感
export function drawLinks(ctx: CanvasRenderingContext2D, pts: ScreenPoint[], primaryRgb: RGB) {
  ctx.save()
  ctx.lineWidth = 0.65
  for (let i = 0; i < pts.length; i++) {
    for (let j = i + 1; j < pts.length; j++) {
      const dx = pts[i].sx - pts[j].sx
      const dy = pts[i].sy - pts[j].sy
      const d2 = dx * dx + dy * dy
      if (d2 > LINK_MAX * LINK_MAX) continue
      const a = (1 - Math.sqrt(d2) / LINK_MAX) * 0.26
      ctx.strokeStyle = rgba(primaryRgb, a)
      ctx.beginPath()
      ctx.moveTo(pts[i].sx, pts[i].sy)
      ctx.lineTo(pts[j].sx, pts[j].sy)
      ctx.stroke()
    }
  }
  ctx.restore()
}

// 双环声呐 / 点击水波：零全圆渐变填充，改用主细环 + 宽柔光描边 + 滞后次级内环
export function drawSonarRings(
  ctx: CanvasRenderingContext2D,
  rings: SonarRing[],
  isDark: boolean,
) {
  if (!rings.length) return
  ctx.save()
  for (const ring of rings) {
    const p = Math.min(1, ring.ageMs / ring.durationMs)
    const fade = Math.pow(1 - p, 1.45)
    const isRipple = ring.kind === 'ripple'
    const baseAlpha = isRipple
      ? (isDark ? 0.30 : 0.24)
      : (isDark ? 0.42 : 0.34)
    const alpha = baseAlpha * fade
    if (alpha <= 0.005 || ring.radius <= 1) continue

    // 柔和光晕宽描边（替代昂贵的全圆 createRadialGradient 填充）
    const glowR = Math.max(1, ring.radius - 4)
    ctx.strokeStyle = rgba(ring.rgb, alpha * 0.22)
    ctx.lineWidth = isRipple ? 8 : 12
    ctx.beginPath()
    ctx.arc(ring.x, ring.y, glowR, 0, Math.PI * 2)
    ctx.stroke()

    // 主波前细环
    ctx.strokeStyle = rgba(ring.rgb, alpha)
    ctx.lineWidth = isRipple ? 1.35 : 1.75
    ctx.beginPath()
    ctx.arc(ring.x, ring.y, ring.radius, 0, Math.PI * 2)
    ctx.stroke()

    // 滞后次级内环
    const echoRadius = ring.radius * 0.78
    if (echoRadius > 8) {
      ctx.strokeStyle = rgba(ring.rgb, alpha * 0.48)
      ctx.lineWidth = 1
      ctx.beginPath()
      ctx.arc(ring.x, ring.y, echoRadius, 0, Math.PI * 2)
      ctx.stroke()
    }
  }
  ctx.restore()
}
