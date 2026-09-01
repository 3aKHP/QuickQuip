<template>
  <canvas
    ref="canvasRef"
    class="light-field"
    :class="`light-field--${mode}`"
    aria-hidden="true"
  />
</template>

<script setup lang="ts">
import { computed, onMounted, onUnmounted, ref, watch } from 'vue'
import { useTheme } from '../../composables/useTheme'
import { useMotionPrefs } from '../../composables/useMotionPrefs'

const props = defineProps<{
  mode: 'showcase' | 'ambient'
}>()

const { theme } = useTheme()
const { lowMotion } = useMotionPrefs()
const isDark = computed(() => theme.value === 'dark')
const isShowcase = computed(() => props.mode === 'showcase')

interface Particle {
  x: number; y: number
  r: number; alpha: number; vx: number; vy: number
  twinkle: number; tone: number; layer: number
}

// 视差层：远 / 中 / 近，位移幅度递增营造纵深
const LAYER_SHIFT = [0.7, 1.5, 3.0]

const canvasRef = ref<HTMLCanvasElement | null>(null)
let raf = 0
let particles: Particle[] = []
let mouseX = 0
let mouseY = 0
// 光晕位置独立 lerp，拖出平滑尾随
let haloX = 0
let haloY = 0
let cx = 0
let cy = 0

function onMouseMove(e: MouseEvent) { mouseX = e.clientX; mouseY = e.clientY }

function isMobile(): boolean { return window.innerWidth < 768 }

function initParticles(w: number, h: number) {
  // showcase 满强度；ambient 约七成密度，保持可感知
  const base = isDark.value
    ? (isMobile() ? 80 : 180)
    : (isMobile() ? 56 : 132)
  const count = Math.round(base * (isShowcase.value ? 1 : 0.7))
  particles = []
  for (let i = 0; i < count; i++) {
    const layer = i % 3
    particles.push({
      x: Math.random() * w, y: Math.random() * h,
      r: (isDark.value ? 0.6 + Math.random() * 1.4 : 0.8 + Math.random() * 2.4) * (1 + layer * 0.25),
      alpha: isDark.value ? 0.30 + Math.random() * 0.35 : 0.22 + Math.random() * 0.26,
      vx: (isDark.value ? (Math.random() - 0.5) * 0.30 : (Math.random() - 0.5) * 0.10) * (1 + layer * 0.4),
      vy: (isDark.value ? (Math.random() - 0.5) * 0.20 : (Math.random() - 0.5) * 0.08) * (1 + layer * 0.4),
      twinkle: Math.random() * Math.PI * 2,
      tone: Math.random(),
      layer,
    })
  }
}

// 亮色模式底色：冷色微染，让刻度粒子与光束有对比基底
function drawBaseWash(ctx: CanvasRenderingContext2D, w: number, h: number) {
  const k = isShowcase.value ? 1 : 0.75
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

// 鼠标光晕：小号品牌色径向光，lerp 尾随
function drawMouseHalo(ctx: CanvasRenderingContext2D, t: number) {
  haloX += (mouseX - haloX) * 0.07
  haloY += (mouseY - haloY) * 0.07
  const breathe = 1 + Math.sin(t * 0.8) * 0.06
  const k = isShowcase.value ? 1 : 0.7
  const radius = (isDark.value ? 360 : 300) * breathe
  const g = ctx.createRadialGradient(haloX, haloY, 0, haloX, haloY, radius)
  if (isDark.value) {
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

function drawRays(ctx: CanvasRenderingContext2D, t: number, w: number, h: number, px: number, py: number) {
  ctx.save()
  ctx.globalCompositeOperation = 'source-over'
  ctx.lineCap = 'round'
  ctx.lineJoin = 'round'

  const driftX = px * 0.9 + Math.sin(t * 0.18) * 16
  const driftY = py * 0.65 + Math.cos(t * 0.14) * 12

  // QQ 蓝 / 青 / 琥珀光束；暗色与 ambient 模式收敛透明度
  const k = (isDark.value ? 0.55 : 1) * (isShowcase.value ? 1 : 0.6)
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

  const arcK = (isDark.value ? 0.5 : 1) * (isShowcase.value ? 1 : 0.65)
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

// 暗色：邻近粒子连线（近层粒子之间），星座感
function drawLinks(ctx: CanvasRenderingContext2D, pts: { sx: number; sy: number; layer: number }[]) {
  const maxD = 120
  ctx.save()
  ctx.lineWidth = 0.6
  for (let i = 0; i < pts.length; i++) {
    if (pts[i].layer !== 2) continue
    for (let j = i + 1; j < pts.length; j++) {
      if (pts[j].layer !== 2) continue
      const dx = pts[i].sx - pts[j].sx
      const dy = pts[i].sy - pts[j].sy
      const d2 = dx * dx + dy * dy
      if (d2 > maxD * maxD) continue
      const a = (1 - Math.sqrt(d2) / maxD) * 0.22
      ctx.strokeStyle = `rgba(18, 183, 245, ${a.toFixed(3)})`
      ctx.beginPath()
      ctx.moveTo(pts[i].sx, pts[i].sy)
      ctx.lineTo(pts[j].sx, pts[j].sy)
      ctx.stroke()
    }
  }
  ctx.restore()
}

function draw(now: number) {
  const canvas = canvasRef.value
  if (!canvas) return
  const ctx = canvas.getContext('2d')
  if (!ctx) return

  const t = now * 0.001
  const w = window.innerWidth
  const h = window.innerHeight
  ctx.clearRect(0, 0, w, h)

  // 归一化鼠标位移，驱动三层视差
  const px = (mouseX - cx) * 0.008
  const py = (mouseY - cy) * 0.008

  if (!isDark.value) drawBaseWash(ctx, w, h)
  drawRays(ctx, t, w, h, px, py)
  drawMouseHalo(ctx, t)

  const alphaK = isShowcase.value ? 1 : 0.85
  const glowR = 210 // 鼠标邻近增亮半径

  // 先算全部粒子屏幕坐标（暗色连线要用）
  const pts: { sx: number; sy: number; layer: number }[] = []
  for (const p of particles) {
    p.x += p.vx; p.y += p.vy
    if (p.x < -10) p.x = w + 10; if (p.x > w + 10) p.x = -10
    if (p.y < -10) p.y = h + 10; if (p.y > h + 10) p.y = -10

    const dx = p.x - cx; const dy = p.y - cy
    const shift = LAYER_SHIFT[p.layer]
    pts.push({
      sx: p.x + px * shift * (1 + Math.abs(dx) / Math.max(cx, 1)),
      sy: p.y + py * shift * (1 + Math.abs(dy) / Math.max(cy, 1)),
      layer: p.layer,
    })
  }

  if (isDark.value) drawLinks(ctx, pts)

  for (let i = 0; i < particles.length; i++) {
    const p = particles[i]
    const { sx, sy } = pts[i]

    const a = p.alpha + Math.sin(t * 0.6 + p.twinkle) * 0.1
    let alpha = Math.max(isDark.value ? 0.08 : 0.04, a) * alphaK

    // 鼠标邻近增亮：粒子自身变亮
    const mdx = sx - haloX; const mdy = sy - haloY
    const md = Math.sqrt(mdx * mdx + mdy * mdy)
    if (md < glowR) alpha = Math.min(1, alpha * (1 + (1 - md / glowR) * 1.6))

    if (isDark.value) {
      if (p.tone > 0.85) {
        // 英雄星：四向星芒 + 亮核，缓慢旋转呼吸
        const flare = (3.2 + p.r * 2.2) * (1 + Math.sin(t * 0.9 + p.twinkle) * 0.25)
        const rot = p.twinkle + t * 0.15
        ctx.strokeStyle = `rgba(150, 215, 255, ${(alpha * 0.9).toFixed(3)})`
        ctx.lineWidth = 0.8
        ctx.beginPath()
        for (let k2 = 0; k2 < 4; k2++) {
          const ang = rot + (Math.PI / 2) * k2
          ctx.moveTo(sx, sy)
          ctx.lineTo(sx + Math.cos(ang) * flare, sy + Math.sin(ang) * flare)
        }
        ctx.stroke()
        ctx.fillStyle = `rgba(230, 246, 255, ${Math.min(1, alpha * 1.3).toFixed(3)})`
        ctx.beginPath()
        ctx.arc(sx, sy, p.r * 0.9, 0, Math.PI * 2)
        ctx.fill()
      } else if (p.tone > 0.55) {
        // 十字星：横竖刻度 + 微光晕
        const tick = 3.5 + p.r * 2.2
        ctx.strokeStyle = `rgba(120, 200, 250, ${alpha.toFixed(3)})`
        ctx.lineWidth = 0.9
        ctx.beginPath()
        ctx.moveTo(sx - tick, sy); ctx.lineTo(sx + tick, sy)
        ctx.moveTo(sx, sy - tick); ctx.lineTo(sx, sy + tick)
        ctx.stroke()
        const g = ctx.createRadialGradient(sx, sy, 0, sx, sy, tick)
        g.addColorStop(0, `rgba(18, 183, 245, ${(alpha * 0.35).toFixed(3)})`)
        g.addColorStop(1, 'rgba(18, 183, 245, 0)')
        ctx.fillStyle = g
        ctx.beginPath()
        ctx.arc(sx, sy, tick, 0, Math.PI * 2)
        ctx.fill()
      } else {
        // 发光圆点：光晕 + 亮核
        const glow = ctx.createRadialGradient(sx, sy, 0, sx, sy, p.r * 3)
        glow.addColorStop(0, `rgba(18, 183, 245, ${alpha.toFixed(3)})`)
        glow.addColorStop(1, 'rgba(18, 183, 245, 0)')
        ctx.fillStyle = glow
        ctx.beginPath()
        ctx.arc(sx, sy, p.r * 3, 0, Math.PI * 2)
        ctx.fill()
        ctx.fillStyle = `rgba(180, 230, 255, ${Math.min(1, alpha * 1.1).toFixed(3)})`
        ctx.beginPath()
        ctx.arc(sx, sy, p.r * 0.8, 0, Math.PI * 2)
        ctx.fill()
      }
    } else {
      // 亮色：刻度线粒子（QQ 蓝主色，青次之，琥珀点缀）
      const amber = p.tone > 0.92
      const cyan = p.tone < 0.22
      const color = amber
        ? `rgba(245, 158, 11, ${(alpha * 0.6).toFixed(3)})`
        : cyan
          ? `rgba(6, 182, 212, ${(alpha * 0.85).toFixed(3)})`
          : `rgba(13, 155, 224, ${alpha.toFixed(3)})`
      const tick = 4 + p.r * 2.6
      ctx.strokeStyle = color
      ctx.lineWidth = 1
      ctx.beginPath()
      if (p.tone > 0.55) {
        ctx.moveTo(sx - tick, sy)
        ctx.lineTo(sx + tick, sy)
      } else {
        ctx.moveTo(sx, sy - tick)
        ctx.lineTo(sx, sy + tick)
      }
      if (p.tone > 0.88) {
        ctx.moveTo(sx, sy - tick * 0.72)
        ctx.lineTo(sx, sy + tick * 0.72)
      }
      ctx.stroke()

      if (p.tone > 0.82) {
        ctx.save()
        ctx.globalAlpha = 0.55
        ctx.beginPath()
        ctx.arc(sx, sy, tick * 0.62, 0, Math.PI * 2)
        ctx.stroke()
        ctx.restore()
      }
    }
  }
  if (!shouldStatic()) {
    raf = requestAnimationFrame(draw)
  }
}

function resize() {
  const canvas = canvasRef.value
  if (!canvas) return
  const dpr = Math.min(window.devicePixelRatio || 1, 2)
  canvas.width = Math.floor(window.innerWidth * dpr)
  canvas.height = Math.floor(window.innerHeight * dpr)
  // 粒子坐标在 CSS 像素空间计算，绘制时整体缩放
  canvas.getContext('2d')?.setTransform(dpr, 0, 0, dpr, 0, 0)
  cx = window.innerWidth / 2; cy = window.innerHeight / 2
  initParticles(window.innerWidth, window.innerHeight)
  // 静态模式：重设 canvas 尺寸会清空位图且无 RAF 循环，补画一帧
  if (shouldStatic()) draw(performance.now())
}

function prefersReducedMotion(): boolean {
  return window.matchMedia('(prefers-reduced-motion: reduce)').matches
}

/** 静态渲染判定：系统 reduced-motion 或用户开启低动态 */
function shouldStatic(): boolean {
  return lowMotion.value || prefersReducedMotion()
}

function onVisibilityChange() {
  if (document.hidden) {
    if (raf) { cancelAnimationFrame(raf); raf = 0 }
  } else if (!raf && !shouldStatic()) {
    raf = requestAnimationFrame(draw)
  }
}

onMounted(() => {
  resize()
  mouseX = cx; mouseY = cy
  haloX = cx; haloY = cy
  window.addEventListener('resize', resize)
  window.addEventListener('mousemove', onMouseMove, { passive: true })
  document.addEventListener('visibilitychange', onVisibilityChange)
  // 尊重 reduced-motion / 低动态开关：只画一帧静态，不启动 RAF 循环
  if (shouldStatic()) {
    draw(performance.now())
    return
  }
  raf = requestAnimationFrame(draw)
})

watch(theme, () => resize())
watch(isShowcase, () => resize())

// 低动态开关切换：即时停帧或恢复动画
watch(lowMotion, (staticOnly) => {
  if (staticOnly) {
    if (raf) { cancelAnimationFrame(raf); raf = 0 }
    draw(performance.now())
  } else if (!raf && !document.hidden) {
    raf = requestAnimationFrame(draw)
  }
})

onUnmounted(() => {
  if (raf) cancelAnimationFrame(raf)
  window.removeEventListener('resize', resize)
  window.removeEventListener('mousemove', onMouseMove)
  document.removeEventListener('visibilitychange', onVisibilityChange)
})
</script>

<style scoped>
.light-field {
  position: fixed;
  inset: 0;
  width: 100vw;
  height: 100vh;
  z-index: 0;
  pointer-events: none;
  opacity: var(--qq-background-field-opacity);
  mix-blend-mode: var(--qq-background-field-blend);
  transition: opacity 0.6s var(--qq-ease-loop, linear);
}

/* showcase 满强度，CSS 层不再压透明度 */
.light-field--showcase {
  opacity: 1;
  mix-blend-mode: normal;
}
</style>
