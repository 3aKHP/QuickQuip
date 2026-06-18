<template>
  <canvas
    ref="canvasRef"
    class="particle-bg"
    aria-hidden="true"
  />
</template>

<script setup lang="ts">
import { computed, onMounted, onUnmounted, ref, watch } from 'vue'
import { useTheme } from '../../composables/useTheme'

const { theme } = useTheme()
const isDark = computed(() => theme.value === 'dark')

interface Particle {
  x: number; y: number
  r: number; alpha: number; vx: number; vy: number; twinkle: number; tone: number
}

const canvasRef = ref<HTMLCanvasElement | null>(null)
let raf = 0
let particles: Particle[] = []
let mouseX = 0
let mouseY = 0
let cx = 0
let cy = 0

function onMouseMove(e: MouseEvent) { mouseX = e.clientX; mouseY = e.clientY }

function isMobile(): boolean { return window.innerWidth < 768 }

function initParticles(w: number, h: number) {
  // 克制动效：桌面 50 / 移动 24（约为展示站强度的 1/3）
  const count = isDark.value
    ? (isMobile() ? 24 : 50)
    : (isMobile() ? 18 : 38)
  particles = []
  for (let i = 0; i < count; i++) {
    particles.push({
      x: Math.random() * w, y: Math.random() * h,
      r: isDark.value ? 0.6 + Math.random() * 1.4 : 0.8 + Math.random() * 2.4,
      alpha: isDark.value ? 0.28 + Math.random() * 0.32 : 0.18 + Math.random() * 0.24,
      // 克制动效：速度降为展示站的 0.4 倍
      vx: isDark.value ? (Math.random() - 0.5) * 0.12 : (Math.random() - 0.5) * 0.04,
      vy: isDark.value ? (Math.random() - 0.5) * 0.08 : (Math.random() - 0.5) * 0.03,
      twinkle: Math.random() * Math.PI * 2,
      tone: Math.random(),
    })
  }
}

function drawLightField(ctx: CanvasRenderingContext2D, t: number, w: number, h: number, px: number, py: number) {
  // 亮色态光线 / 圆弧（透明度降为展示站的 50%）
  ctx.save()
  ctx.globalCompositeOperation = 'source-over'
  ctx.lineCap = 'round'
  ctx.lineJoin = 'round'

  const driftX = px * 0.9 + Math.sin(t * 0.18) * 16
  const driftY = py * 0.65 + Math.cos(t * 0.14) * 12

  const rays = [
    { y: h * 0.22, slope: 0.10, color: 'rgba(18, 183, 245, 0.09)', width: 1.2 },
    { y: h * 0.46, slope: -0.13, color: 'rgba(6, 182, 212, 0.08)', width: 1.0 },
    { y: h * 0.70, slope: 0.08, color: 'rgba(13, 155, 224, 0.06)', width: 1.0 },
    { y: h * 0.86, slope: -0.05, color: 'rgba(245, 158, 11, 0.04)', width: 1.0 },
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

  const centers = [
    { x: w * 0.22 + driftX * 0.22, y: h * 0.23 + driftY * 0.18, r: Math.min(w, h) * 0.16, c: 'rgba(18, 183, 245, 0.07)' },
    { x: w * 0.76 - driftX * 0.16, y: h * 0.58 - driftY * 0.12, r: Math.min(w, h) * 0.22, c: 'rgba(6, 182, 212, 0.06)' },
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

function draw(now: number) {
  const canvas = canvasRef.value
  if (!canvas) return
  const ctx = canvas.getContext('2d')
  if (!ctx) return

  const t = now * 0.001
  const w = canvas.width
  const h = canvas.height
  ctx.clearRect(0, 0, w, h)

  const px = (mouseX - cx) * 0.008
  const py = (mouseY - cy) * 0.008

  if (!isDark.value) {
    drawLightField(ctx, t, w, h, px, py)
  }

  for (const p of particles) {
    p.x += p.vx; p.y += p.vy
    if (p.x < -10) p.x = w + 10; if (p.x > w + 10) p.x = -10
    if (p.y < -10) p.y = h + 10; if (p.y > h + 10) p.y = -10

    const dx = p.x - cx; const dy = p.y - cy
    const sx = p.x + px * (1 + Math.abs(dx) / Math.max(cx, 1))
    const sy = p.y + py * (1 + Math.abs(dy) / Math.max(cy, 1))

    const a = p.alpha + Math.sin(t * 0.6 + p.twinkle) * 0.1
    const alpha = Math.max(isDark.value ? 0.08 : 0.04, a)

    if (isDark.value) {
      ctx.beginPath()
      ctx.arc(sx, sy, p.r, 0, Math.PI * 2)
      ctx.fillStyle = `rgba(18, 183, 245, ${alpha.toFixed(3)})`
      ctx.fill()
    } else {
      // QQ 蓝 + 青 + 极少量琥珀点缀
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
  if (!prefersReducedMotion()) {
    raf = requestAnimationFrame(draw)
  }
}

function resize() {
  const canvas = canvasRef.value
  if (!canvas) return
  canvas.width = window.innerWidth
  canvas.height = window.innerHeight
  cx = canvas.width / 2; cy = canvas.height / 2
  initParticles(canvas.width, canvas.height)
}

function prefersReducedMotion(): boolean {
  return window.matchMedia('(prefers-reduced-motion: reduce)').matches
}

function onVisibilityChange() {
  if (document.hidden) {
    if (raf) { cancelAnimationFrame(raf); raf = 0 }
  } else if (!raf && !prefersReducedMotion()) {
    raf = requestAnimationFrame(draw)
  }
}

onMounted(() => {
  resize()
  window.addEventListener('resize', resize)
  window.addEventListener('mousemove', onMouseMove, { passive: true })
  document.addEventListener('visibilitychange', onVisibilityChange)
  // 尊重 prefers-reduced-motion：只画一帧静态，不启动 RAF 循环
  if (prefersReducedMotion()) {
    draw(performance.now())
    return
  }
  raf = requestAnimationFrame(draw)
})

watch(theme, () => resize())

onUnmounted(() => {
  if (raf) cancelAnimationFrame(raf)
  window.removeEventListener('resize', resize)
  window.removeEventListener('mousemove', onMouseMove)
  document.removeEventListener('visibilitychange', onVisibilityChange)
})
</script>

<style scoped>
.particle-bg {
  position: fixed; inset: 0;
  width: 100vw; height: 100vh;
  z-index: 0; pointer-events: none;
  opacity: var(--qq-background-field-opacity);
  mix-blend-mode: var(--qq-background-field-blend);
  transition: opacity 0.6s linear;
}
</style>
