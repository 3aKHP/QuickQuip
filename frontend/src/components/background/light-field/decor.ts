// LightField 装饰层：流动极光底幕、光束/圆弧、鼠标光晕、指针星座牵丝、暗色连线与双环声呐
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

// 流动极光底幕（暗色深空极光 / 亮色通透棱镜流彩），随工作域色流体漫染
export function drawAuroraMesh(
  ctx: CanvasRenderingContext2D,
  t: number,
  w: number,
  h: number,
  isDark: boolean,
  isShowcase: boolean,
  primaryRgb: RGB,
  secondaryRgb: RGB,
  warpEnergy = 0,
) {
  const k = (isShowcase ? 1.15 : 0.85) * (1 + Math.min(warpEnergy, 1.5) * 0.22)
  const diag = Math.max(w, h)
  const blobs = [
    {
      x: w * (0.76 + Math.sin(t * 0.14) * 0.08),
      y: h * (0.16 + Math.cos(t * 0.11) * 0.07),
      r: diag * 0.56,
      rgb: primaryRgb,
      alpha: (isDark ? 0.16 : 0.105) * k,
    },
    {
      x: w * (0.14 + Math.cos(t * 0.12 + 1.4) * 0.09),
      y: h * (0.84 + Math.sin(t * 0.15 + 0.8) * 0.07),
      r: diag * 0.52,
      rgb: secondaryRgb,
      alpha: (isDark ? 0.14 : 0.09) * k,
    },
    {
      x: w * (0.52 + Math.sin(t * 0.09 + 2.6) * 0.11),
      y: h * (0.48 + Math.cos(t * 0.13 + 1.9) * 0.09),
      r: diag * 0.42,
      rgb: isDark ? primaryRgb : ([245, 158, 11] as RGB),
      alpha: (isDark ? 0.075 : 0.032) * k,
    },
  ]

  for (const blob of blobs) {
    const g = ctx.createRadialGradient(blob.x, blob.y, 0, blob.x, blob.y, blob.r)
    g.addColorStop(0, rgba(blob.rgb, blob.alpha))
    g.addColorStop(0.55, rgba(blob.rgb, blob.alpha * 0.32))
    g.addColorStop(1, rgba(blob.rgb, 0))
    ctx.fillStyle = g
    ctx.fillRect(0, 0, w, h)
  }
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
  const breathe = 1 + Math.sin(t * 0.9) * 0.07
  const k = isShowcase ? 1.08 : 0.82
  const radius = (isDark ? 380 : 320) * breathe
  const g = ctx.createRadialGradient(haloX, haloY, 0, haloX, haloY, radius)
  if (isDark) {
    g.addColorStop(0, rgba(primaryRgb, 0.26 * k))
    g.addColorStop(0.45, rgba(secondaryRgb, 0.12 * k))
    g.addColorStop(1, rgba(secondaryRgb, 0))
  } else {
    g.addColorStop(0, rgba(primaryRgb, 0.18 * k))
    g.addColorStop(0.45, rgba(secondaryRgb, 0.08 * k))
    g.addColorStop(1, rgba(secondaryRgb, 0))
  }
  ctx.fillStyle = g
  ctx.fillRect(haloX - radius, haloY - radius, radius * 2, radius * 2)
}

// 指针星座牵丝：指针向半径内最近粒子拉出纤细发光引力丝线，营造可把玩的物理光场手感
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
  const peakAlpha = (isDark ? 0.44 : 0.30) * (isShowcase ? 1.1 : 0.92)
  for (const c of candidates) {
    const ratio = 1 - Math.sqrt(c.d2) / CURSOR_LINK_RADIUS
    const alpha = ratio * ratio * peakAlpha
    if (alpha <= 0.01) continue

    const grad = ctx.createLinearGradient(haloX, haloY, c.sx, c.sy)
    grad.addColorStop(0, rgba(secondaryRgb, alpha * 0.85))
    grad.addColorStop(1, rgba(primaryRgb, alpha * 0.28))
    ctx.strokeStyle = grad
    ctx.beginPath()
    ctx.moveTo(haloX, haloY)
    ctx.lineTo(c.sx, c.sy)
    ctx.stroke()

    // 端点星芒微核
    ctx.fillStyle = rgba(primaryRgb, Math.min(0.85, alpha * 1.4))
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
    const grad = ctx.createLinearGradient(0, 0, w, 0)
    grad.addColorStop(0, 'rgba(255, 255, 255, 0)')
    grad.addColorStop(0.18, ray.color)
    grad.addColorStop(0.82, ray.color)
    grad.addColorStop(1, 'rgba(255, 255, 255, 0)')
    ctx.strokeStyle = grad
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

// 双环声呐 / 点击水波：清晰通透的主波前 + 滞后次级内环 + 径向微晕
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

    // 主波前细环
    ctx.strokeStyle = rgba(ring.rgb, alpha)
    ctx.lineWidth = isRipple ? 1.35 : 1.75
    ctx.beginPath()
    ctx.arc(ring.x, ring.y, ring.radius, 0, Math.PI * 2)
    ctx.stroke()

    // 滞后次级内环（双波前质感）
    const echoRadius = ring.radius * 0.78
    if (echoRadius > 8) {
      ctx.strokeStyle = rgba(ring.rgb, alpha * 0.48)
      ctx.lineWidth = 1
      ctx.beginPath()
      ctx.arc(ring.x, ring.y, echoRadius, 0, Math.PI * 2)
      ctx.stroke()
    }

    // 柔和内沿尾晕，增强空间波前立体感
    const band = isRipple ? 24 : 36
    const inner = Math.max(0, ring.radius - band)
    const grad = ctx.createRadialGradient(ring.x, ring.y, inner, ring.x, ring.y, ring.radius)
    grad.addColorStop(0, rgba(ring.rgb, 0))
    grad.addColorStop(1, rgba(ring.rgb, alpha * 0.28))
    ctx.fillStyle = grad
    ctx.beginPath()
    ctx.arc(ring.x, ring.y, ring.radius, 0, Math.PI * 2)
    ctx.fill()
  }
  ctx.restore()
}
