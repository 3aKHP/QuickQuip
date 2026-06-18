<template>
  <div
    class="mouse-glow"
    :style="glowStyle"
    aria-hidden="true"
  />
</template>

<script setup lang="ts">
import { computed, onMounted, onUnmounted, ref } from 'vue'
import { useTheme } from '../../composables/useTheme'

const { theme } = useTheme()
const isDark = computed(() => theme.value === 'dark')

const mx = ref(0)
const my = ref(0)
let raf = 0
let rawX = 0
let rawY = 0

function onMouseMove(e: MouseEvent) { rawX = e.clientX; rawY = e.clientY }

function tick() {
  if (rawX || rawY) { mx.value = rawX; my.value = rawY }
  raf = requestAnimationFrame(tick)
}

const glowStyle = computed(() => {
  // 克制：半径从展示站的 430/560 降到 280/360
  const radius = isDark.value ? 360 : 280
  const mask = `radial-gradient(circle ${radius}px at ${mx.value}px ${my.value}px, #000 0%, rgba(0, 0, 0, 0.82) 42%, transparent 76%)`
  return {
    background: isDark.value
      ? `radial-gradient(circle 340px at ${mx.value}px ${my.value}px, rgba(18, 183, 245, 0.16), transparent 60%)`
      : [
          // QQ 蓝 + 青双层径向 + 锥形点缀（去掉展示站的琥珀 / 紫）
          `radial-gradient(circle 20px at ${mx.value}px ${my.value}px, rgba(255, 255, 255, 0.68), transparent 76%)`,
          `radial-gradient(circle 150px at ${mx.value}px ${my.value}px, rgba(18, 183, 245, 0.16), transparent 64%)`,
          `radial-gradient(circle 240px at ${mx.value}px ${my.value}px, rgba(6, 182, 212, 0.12), transparent 68%)`,
          `conic-gradient(from 18deg at ${mx.value}px ${my.value}px, transparent 0deg, rgba(18, 183, 245, 0.16) 24deg, transparent 48deg, rgba(6, 182, 212, 0.16) 72deg, transparent 112deg, transparent 360deg)`,
        ].join(', '),
    maskImage: mask,
    WebkitMaskImage: mask,
  }
})

onMounted(() => {
  rawX = window.innerWidth / 2; rawY = window.innerHeight / 2
  mx.value = rawX; my.value = rawY
  window.addEventListener('mousemove', onMouseMove, { passive: true })
  raf = requestAnimationFrame(tick)
})

onUnmounted(() => {
  cancelAnimationFrame(raf)
  window.removeEventListener('mousemove', onMouseMove)
})
</script>

<style scoped>
.mouse-glow {
  position: fixed; inset: 0;
  width: 100vw; height: 100vh;
  z-index: 0; pointer-events: none;
  opacity: var(--qq-mouse-glow-opacity);
  mix-blend-mode: var(--qq-mouse-glow-blend);
  filter: blur(0.4px);
  transition: opacity 0.6s linear;
}
</style>
