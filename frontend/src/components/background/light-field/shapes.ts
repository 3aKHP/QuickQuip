// LightField 粒子形态：暗色 hero/cross/glow 与亮色 tick，支持星速跃迁拖尾（Star Streaks）
import {
  DARK_CROSS_TONE,
  DARK_HERO_TONE,
  LIGHT_AMBER_TONE,
  LIGHT_CYAN_TONE,
  LIGHT_RING_TONE,
  LIGHT_TICK_DOUBLE_TONE,
  LIGHT_TICK_HORIZONTAL_TONE,
  type Particle,
  type RGB,
} from './config'

/** 按明暗主题与 tone 分发到具体粒子形态；跃迁时附带方向速度拖尾 */
export function drawParticleShape(
  ctx: CanvasRenderingContext2D,
  p: Particle,
  sx: number,
  sy: number,
  alpha: number,
  t: number,
  isDark: boolean,
  primaryRgb: RGB,
  streakDx = 0,
  streakDy = 0,
) {
  // 星速跃迁拖尾：粒子瞬时高速掠过时拉出渐变光丝，随后自然收短定格
  if (Math.abs(streakDx) > 1.2 || Math.abs(streakDy) > 1.2) {
    const tailX = sx - streakDx
    const tailY = sy - streakDy
    const grad = ctx.createLinearGradient(sx, sy, tailX, tailY)
    const headAlpha = Math.min(0.85, alpha * (isDark ? 1.15 : 0.85))
    grad.addColorStop(0, `rgba(${Math.round(primaryRgb[0])}, ${Math.round(primaryRgb[1])}, ${Math.round(primaryRgb[2])}, ${headAlpha.toFixed(3)})`)
    grad.addColorStop(1, `rgba(${Math.round(primaryRgb[0])}, ${Math.round(primaryRgb[1])}, ${Math.round(primaryRgb[2])}, 0)`)
    ctx.strokeStyle = grad
    ctx.lineWidth = Math.max(0.85, p.r * (isDark ? 0.9 : 0.7))
    ctx.beginPath()
    ctx.moveTo(sx, sy)
    ctx.lineTo(tailX, tailY)
    ctx.stroke()
  }

  if (isDark) {
    drawDarkParticle(ctx, p, sx, sy, alpha, t)
  } else {
    drawLightTick(ctx, p, sx, sy, alpha)
  }
}

// 暗色：英雄星 / 十字星 / 发光圆点
function drawDarkParticle(
  ctx: CanvasRenderingContext2D,
  p: Particle,
  sx: number,
  sy: number,
  alpha: number,
  t: number,
) {
  if (p.tone > DARK_HERO_TONE) {
    // 英雄星：四向星芒 + 亮核，缓慢旋转呼吸
    const flare = (3.4 + p.r * 2.3) * (1 + Math.sin(t * 0.9 + p.twinkle) * 0.25)
    const rot = p.twinkle + t * 0.16
    ctx.strokeStyle = `rgba(155, 220, 255, ${(alpha * 0.92).toFixed(3)})`
    ctx.lineWidth = 0.85
    ctx.beginPath()
    for (let k2 = 0; k2 < 4; k2++) {
      const ang = rot + (Math.PI / 2) * k2
      ctx.moveTo(sx, sy)
      ctx.lineTo(sx + Math.cos(ang) * flare, sy + Math.sin(ang) * flare)
    }
    ctx.stroke()
    ctx.fillStyle = `rgba(232, 247, 255, ${Math.min(1, alpha * 1.3).toFixed(3)})`
    ctx.beginPath()
    ctx.arc(sx, sy, p.r * 0.92, 0, Math.PI * 2)
    ctx.fill()
  } else if (p.tone > DARK_CROSS_TONE) {
    // 十字星：横竖刻度 + 微光晕
    const tick = 3.5 + p.r * 2.2
    ctx.strokeStyle = `rgba(125, 205, 252, ${alpha.toFixed(3)})`
    ctx.lineWidth = 0.9
    ctx.beginPath()
    ctx.moveTo(sx - tick, sy); ctx.lineTo(sx + tick, sy)
    ctx.moveTo(sx, sy - tick); ctx.lineTo(sx, sy + tick)
    ctx.stroke()
    const g = ctx.createRadialGradient(sx, sy, 0, sx, sy, tick)
    g.addColorStop(0, `rgba(18, 183, 245, ${(alpha * 0.38).toFixed(3)})`)
    g.addColorStop(1, 'rgba(18, 183, 245, 0)')
    ctx.fillStyle = g
    ctx.beginPath()
    ctx.arc(sx, sy, tick, 0, Math.PI * 2)
    ctx.fill()
  } else {
    // 发光圆点：光晕 + 亮核
    const glow = ctx.createRadialGradient(sx, sy, 0, sx, sy, p.r * 3.1)
    glow.addColorStop(0, `rgba(18, 183, 245, ${alpha.toFixed(3)})`)
    glow.addColorStop(1, 'rgba(18, 183, 245, 0)')
    ctx.fillStyle = glow
    ctx.beginPath()
    ctx.arc(sx, sy, p.r * 3.1, 0, Math.PI * 2)
    ctx.fill()
    ctx.fillStyle = `rgba(185, 232, 255, ${Math.min(1, alpha * 1.12).toFixed(3)})`
    ctx.beginPath()
    ctx.arc(sx, sy, p.r * 0.82, 0, Math.PI * 2)
    ctx.fill()
  }
}

// 亮色：刻度线粒子（QQ 蓝主色，青次之，琥珀点缀）
function drawLightTick(
  ctx: CanvasRenderingContext2D,
  p: Particle,
  sx: number,
  sy: number,
  alpha: number,
) {
  const amber = p.tone > LIGHT_AMBER_TONE
  const cyan = p.tone < LIGHT_CYAN_TONE
  const color = amber
    ? `rgba(245, 158, 11, ${(alpha * 0.65).toFixed(3)})`
    : cyan
      ? `rgba(6, 182, 212, ${(alpha * 0.88).toFixed(3)})`
      : `rgba(13, 155, 224, ${alpha.toFixed(3)})`
  const tick = 4 + p.r * 2.6
  ctx.strokeStyle = color
  ctx.lineWidth = 1
  ctx.beginPath()
  if (p.tone > LIGHT_TICK_HORIZONTAL_TONE) {
    ctx.moveTo(sx - tick, sy)
    ctx.lineTo(sx + tick, sy)
  } else {
    ctx.moveTo(sx, sy - tick)
    ctx.lineTo(sx, sy + tick)
  }
  if (p.tone > LIGHT_TICK_DOUBLE_TONE) {
    ctx.moveTo(sx, sy - tick * 0.72)
    ctx.lineTo(sx, sy + tick * 0.72)
  }
  ctx.stroke()

  if (p.tone > LIGHT_RING_TONE) {
    ctx.save()
    ctx.globalAlpha = 0.55
    ctx.beginPath()
    ctx.arc(sx, sy, tick * 0.62, 0, Math.PI * 2)
    ctx.stroke()
    ctx.restore()
  }
}
