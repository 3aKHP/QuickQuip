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
import { createLightFieldStage } from './light-field/stage'

const props = defineProps<{
  mode: 'showcase' | 'ambient'
}>()

const { theme } = useTheme()
const { lowMotion } = useMotionPrefs()
const isDark = computed(() => theme.value === 'dark')
const isShowcase = computed(() => props.mode === 'showcase')

// 舞台负责粒子物理/视差投影/单帧编排；本组件只管生命周期与调度
const stage = createLightFieldStage({
  isDark: () => isDark.value,
  isShowcase: () => isShowcase.value,
})

const canvasRef = ref<HTMLCanvasElement | null>(null)
let raf = 0
let resizeRaf = 0
let reducedMotionMql: MediaQueryList | null = null
const systemReducedMotion = ref(false)

/** 静态渲染判定：系统 reduced-motion 或用户开启低动态 */
function shouldStatic(): boolean {
  return lowMotion.value || systemReducedMotion.value
}

// 静态模式（低动效/reduced-motion）不消费指针视差，跳过坐标更新
const onMouseMove = (e: MouseEvent) => { if (!shouldStatic()) stage.onMouseMove(e) }

function draw(now: number) {
  const canvas = canvasRef.value
  if (!canvas) return
  if (!stage.draw(canvas, now)) return
  if (!shouldStatic()) {
    raf = requestAnimationFrame(draw)
  }
}

function resize() {
  const canvas = canvasRef.value
  if (!canvas) return
  stage.resize(canvas)
  // 静态模式：重设 canvas 尺寸会清空位图且无 RAF 循环，补画一帧
  if (shouldStatic()) draw(performance.now())
}

function onWindowResize() {
  if (resizeRaf) return
  resizeRaf = requestAnimationFrame(() => {
    resizeRaf = 0
    resize()
  })
}

function syncLoop() {
  if (shouldStatic() || document.hidden) {
    if (raf) { cancelAnimationFrame(raf); raf = 0 }
    if (shouldStatic()) draw(performance.now())
  } else if (!raf) {
    stage.resetClock()
    raf = requestAnimationFrame(draw)
  }
}

function onReducedMotionChange(e: MediaQueryListEvent) {
  systemReducedMotion.value = e.matches
  syncLoop()
}

function onVisibilityChange() {
  syncLoop()
}

onMounted(() => {
  try {
    reducedMotionMql = window.matchMedia('(prefers-reduced-motion: reduce)')
    systemReducedMotion.value = reducedMotionMql.matches
    reducedMotionMql.addEventListener('change', onReducedMotionChange)
  } catch { /* ignore */ }
  resize()
  stage.centerPointer()
  window.addEventListener('resize', onWindowResize)
  window.addEventListener('mousemove', onMouseMove, { passive: true })
  document.addEventListener('visibilitychange', onVisibilityChange)
  // 尊重 reduced-motion / 低动态开关：只画一帧静态，不启动 RAF 循环
  if (shouldStatic()) {
    draw(performance.now())
    return
  }
  raf = requestAnimationFrame(draw)
})

watch(theme, () => {
  if (shouldStatic()) draw(performance.now())
})
watch(isShowcase, () => resize())
watch(lowMotion, () => syncLoop())

onUnmounted(() => {
  if (raf) cancelAnimationFrame(raf)
  if (resizeRaf) cancelAnimationFrame(resizeRaf)
  reducedMotionMql?.removeEventListener('change', onReducedMotionChange)
  window.removeEventListener('resize', onWindowResize)
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
