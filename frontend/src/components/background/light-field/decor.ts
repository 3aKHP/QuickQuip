// LightField 装饰层：底色 wash、光束/圆弧、鼠标光晕、暗色连线
import { LINK_MAX, type ScreenPoint } from './config'

// 亮色模式底色：冷色微染，让刻度粒子与光束有对比基底
export function drawBaseWash(
  ctx: CanvasRenderingContext2D,
  w: number,
  h: number,
  isShowcase: boolean,
) {
  const k = isShowcase ? 1 : 0.75
  const washes = [
    { x: w * 0.82, y: h * 0.10, r: Math.max(w, h) * 0.55, c: `rgba(18, 183, 245, ${0.075 * k})` },
    { x: w * 0.08, y: h * 0.92, r: Math.max(w, h) * 0.50, c: `rgba(6, 182, 212, ${0.065 * k})` },
    { x: w * 0.55, y: h * 0.55, r: Math.max(w, h) * 0.45, c: `rgba(245, 158, 11, ${0.022 * k})` },
  ]
  for (const ws of washes) {
    const g = ctx.createRadialGradient(ws.x, ws.y, 0, ws.x, ws.y, ws.r)
    g.addColorStop(0, ws.c)
    g.addColorStop(1, 'rgba(255, 255, 255, 0)')
    ctx.fillStyle = g
    ctx.fillRect(0, 0, w, h)
  }
}

// 鼠标光晕：小号品牌色径向光；位置由调用方 lerp 后传入
export function drawMouseHalo(
  ctx: CanvasRenderingContext2D,
  t: number,
  haloX: number,
  haloY: number,
  isDark: boolean,
  isShowcase: boolean,
) {
  const breathe = 1 + Math.sin(t * 0.8) * 0.06
  const k = isShowcase ? 1 : 0.7
  const radius = (isDark ? 360 : 300) * breathe
  const g = ctx.createRadialGradient(haloX, haloY, 0, haloX, haloY, radius)
  if (isDark) {
    g.addColorStop(0, `rgba(18, 183, 245, ${0.22 * k})`)
    g.addColorStop(0.45, `rgba(6, 182, 212, ${0.10 * k})`)
    g.addColorStop(1, 'rgba(6, 182, 212, 0)')
  } else {
    g.addColorStop(0, `rgba(13, 155, 224, ${0.15 * k})`)
    g.addColorStop(0.45, `rgba(6, 182, 212, ${0.07 * k})`)
    g.addColorStop(1, 'rgba(6, 182, 212, 0)')
  }
  ctx.fillStyle = g
  ctx.fillRect(haloX - radius, haloY - radius, radius * 2, radius * 2)
}

// 光束与大圆弧：QQ 蓝 / 青 / 琥珀；暗色与 ambient 模式收敛透明度
export function drawRays(
  ctx: CanvasRenderingContext2D,
  t: number,
  w: number,
  h: number,
  px: number,
  py: number,
  isDark: boolean,
  isShowcase: boolean,
) {
  ctx.save()
  ctx.globalCompositeOperation = 'source-over'
  ctx.lineCap = 'round'
  ctx.lineJoin = 'round'

  const driftX = px * 0.9 + Math.sin(t * 0.18) * 16
  const driftY = py * 0.65 + Math.cos(t * 0.14) * 12

  const k = (isDark ? 0.55 : 1) * (isShowcase ? 1 : 0.6)
  const rays = [
    { y: h * 0.20, slope: 0.10, color: `rgba(18, 183, 245, ${0.18 * k})`, width: 1.2 },
    { y: h * 0.42, slope: -0.13, color: `rgba(6, 182, 212, ${0.16 * k})`, width: 1.0 },
    { y: h * 0.66, slope: 0.08, color: `rgba(13, 155, 224, ${0.13 * k})`, width: 1.0 },
    { y: h * 0.82, slope: -0.05, color: `rgba(245, 158, 11, ${0.08 * k})`, width: 1.0 },
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

  const arcK = (isDark ? 0.5 : 1) * (isShowcase ? 1 : 0.65)
  const centers = [
    { x: w * 0.22 + driftX * 0.22, y: h * 0.23 + driftY * 0.18, r: Math.min(w, h) * 0.16, c: `rgba(18, 183, 245, ${0.14 * arcK})` },
    { x: w * 0.76 - driftX * 0.16, y: h * 0.58 - driftY * 0.12, r: Math.min(w, h) * 0.22, c: `rgba(245, 158, 11, ${0.10 * arcK})` },
  ]
  for (const arc of centers) {
    ctx.strokeStyle = arc.c
    ctx.lineWidth = 1
    ctx.beginPath()
    ctx.arc(arc.x, arc.y, arc.r, -0.25 + Math.sin(t * 0.12) * 0.05, Math.PI * 1.15)
    ctx.stroke()
    ctx.beginPath()
    ctx.arc(arc.x, arc.y, arc.r * 0.62, Math.PI * 0.12, Math.PI * 1.72 + Math.cos(t * 0.1) * 0.05)
    ctx.stroke()
  }

  ctx.restore()
}

// 暗色：近层候选粒子之间连线（候选由调用方按上限截断），星座感
export function drawLinks(ctx: CanvasRenderingContext2D, pts: ScreenPoint[]) {
  ctx.save()
  ctx.lineWidth = 0.6
  for (let i = 0; i < pts.length; i++) {
    for (let j = i + 1; j < pts.length; j++) {
      const dx = pts[i].sx - pts[j].sx
      const dy = pts[i].sy - pts[j].sy
      const d2 = dx * dx + dy * dy
      if (d2 > LINK_MAX * LINK_MAX) continue
      const a = (1 - Math.sqrt(d2) / LINK_MAX) * 0.22
      ctx.strokeStyle = `rgba(18, 183, 245, ${a.toFixed(3)})`
      ctx.beginPath()
      ctx.moveTo(pts[i].sx, pts[i].sy)
      ctx.lineTo(pts[j].sx, pts[j].sy)
      ctx.stroke()
    }
  }
  ctx.restore()
}
