// LightField 粒子形态：离屏精灵缓存（替代每帧 130+ 次 createRadialGradient）+ 零渐变星速拖尾
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

const SPRITE_SIZE = 32
const SPRITE_HALF = SPRITE_SIZE / 2

let glowSprite: HTMLCanvasElement | null = null
let crossHaloSprite: HTMLCanvasElement | null = null

function createGlowSprite(coreAlpha: number, outerAlpha: number, withBrightCore: boolean): HTMLCanvasElement | null {
  if (typeof document === 'undefined') return null
  const c = document.createElement('canvas')
  c.width = SPRITE_SIZE
  c.height = SPRITE_SIZE
  const gctx = c.getContext('2d')
  if (!gctx) return null

  const g = gctx.createRadialGradient(SPRITE_HALF, SPRITE_HALF, 0, SPRITE_HALF, SPRITE_HALF, SPRITE_HALF)
  g.addColorStop(0, `rgba(18, 183, 245, ${coreAlpha})`)
  g.addColorStop(0.55, `rgba(18, 183, 245, ${outerAlpha})`)
  g.addColorStop(1, 'rgba(18, 183, 245, 0)')
  gctx.fillStyle = g
  gctx.fillRect(0, 0, SPRITE_SIZE, SPRITE_SIZE)

  if (withBrightCore) {
    gctx.fillStyle = 'rgba(195, 238, 255, 0.96)'
    gctx.beginPath()
    gctx.arc(SPRITE_HALF, SPRITE_HALF, SPRITE_HALF * 0.27, 0, Math.PI * 2)
    gctx.fill()
  }
  return c
}

function getGlowSprite(): HTMLCanvasElement | null {
  if (!glowSprite) glowSprite = createGlowSprite(0.95, 0.28, true)
  return glowSprite
}

function getCrossHaloSprite(): HTMLCanvasElement | null {
  if (!crossHaloSprite) crossHaloSprite = createGlowSprite(0.42, 0.12, false)
  return crossHaloSprite
}

/** 按明暗主题与 tone 分发到具体粒子形态；跃迁时附带低开销双段方向星速拖尾 */
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
  // 星速跃迁拖尾：双段实色半透明直线模拟头部亮、尾部渐隐，零 CanvasGradient 分配
  if (Math.abs(streakDx) > 1.2 || Math.abs(streakDy) > 1.2) {
    const r = Math.round(primaryRgb[0])
    const g = Math.round(primaryRgb[1])
    const b = Math.round(primaryRgb[2])
    const headAlpha = Math.min(0.82, alpha * (isDark ? 0.92 : 0.72))
    const midX = sx - streakDx * 0.48
    const midY = sy - streakDy * 0.48
    const tailX = sx - streakDx
    const tailY = sy - streakDy

    ctx.lineWidth = Math.max(0.85, p.r * (isDark ? 0.88 : 0.68))
    ctx.strokeStyle = `rgba(${r}, ${g}, ${b}, ${headAlpha.toFixed(3)})`
    ctx.beginPath()
    ctx.moveTo(sx, sy)
    ctx.lineTo(midX, midY)
    ctx.stroke()

    ctx.strokeStyle = `rgba(${r}, ${g}, ${b}, ${(headAlpha * 0.34).toFixed(3)})`
    ctx.beginPath()
    ctx.moveTo(midX, midY)
    ctx.lineTo(tailX, tailY)
    ctx.stroke()
  }

  if (isDark) {
    drawDarkParticle(ctx, p, sx, sy, alpha, t)
  } else {
    drawLightTick(ctx, p, sx, sy, alpha)
  }
}

// 暗色：英雄星 / 十字星 / 精灵发光圆点
function drawDarkParticle(
  ctx: CanvasRenderingContext2D,
  p: Particle,
  sx: number,
  sy: number,
  alpha: number,
  t: number,
) {
  if (p.tone > DARK_HERO_TONE) {
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
    const tick = 3.5 + p.r * 2.2
    const sprite = getCrossHaloSprite()
    if (sprite) {
      const prevAlpha = ctx.globalAlpha
      ctx.globalAlpha = Math.min(1, alpha)
      ctx.drawImage(sprite, sx - tick, sy - tick, tick * 2, tick * 2)
      ctx.globalAlpha = prevAlpha
    }
    ctx.strokeStyle = `rgba(125, 205, 252, ${alpha.toFixed(3)})`
    ctx.lineWidth = 0.9
    ctx.beginPath()
    ctx.moveTo(sx - tick, sy); ctx.lineTo(sx + tick, sy)
    ctx.moveTo(sx, sy - tick); ctx.lineTo(sx, sy + tick)
    ctx.stroke()
  } else {
    const sprite = getGlowSprite()
    const radius = p.r * 3.1
    if (sprite) {
      const prevAlpha = ctx.globalAlpha
      ctx.globalAlpha = Math.min(1, alpha)
      ctx.drawImage(sprite, sx - radius, sy - radius, radius * 2, radius * 2)
      ctx.globalAlpha = prevAlpha
    } else {
      ctx.fillStyle = `rgba(185, 232, 255, ${Math.min(1, alpha).toFixed(3)})`
      ctx.beginPath()
      ctx.arc(sx, sy, p.r * 0.9, 0, Math.PI * 2)
      ctx.fill()
    }
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
    const prevAlpha = ctx.globalAlpha
    ctx.globalAlpha = prevAlpha * 0.55
    ctx.beginPath()
    ctx.arc(sx, sy, tick * 0.62, 0, Math.PI * 2)
    ctx.stroke()
    ctx.globalAlpha = prevAlpha
  }
}
