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
import { prefersReducedMotion } from './light-field/config'
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

const onMouseMove = (e: MouseEvent) => stage.onMouseMove(e)

/** 静态渲染判定：系统 reduced-motion 或用户开启低动态 */
function shouldStatic(): boolean {
  return lowMotion.value || prefersReducedMotion()
}

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

function onVisibilityChange() {
  if (document.hidden) {
    if (raf) { cancelAnimationFrame(raf); raf = 0 }
  } else if (!raf && !shouldStatic()) {
    raf = requestAnimationFrame(draw)
  }
}

onMounted(() => {
  resize()
  stage.centerPointer()
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
