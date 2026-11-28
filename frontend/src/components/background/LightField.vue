<template>
  <div class="light-field-layer" :class="`light-field-layer--${mode}`" :style="auroraVars" aria-hidden="true">
    <div class="light-field-aurora light-field-aurora--a" />
    <div class="light-field-aurora light-field-aurora--b" />
    <canvas
      ref="canvasRef"
      class="light-field"
      :class="`light-field--${mode}`"
    />
  </div>
</template>

<script setup lang="ts">
import { computed, onMounted, onUnmounted, ref, watch } from 'vue'
import { useTheme } from '../../composables/useTheme'
import { useMotionPrefs } from '../../composables/useMotionPrefs'
import { getLightFieldDomain, subscribeLightField } from '../../lib/lightFieldBus'
import { resolveDomainPalette } from './light-field/config'
import { createLightFieldStage } from './light-field/stage'

const props = withDefaults(defineProps<{
  mode: 'showcase' | 'ambient'
  domain?: string
}>(), {
  domain: 'overview',
})

const { theme } = useTheme()
const { lowMotion } = useMotionPrefs()
const isDark = computed(() => theme.value === 'dark')
const isShowcase = computed(() => props.mode === 'showcase')
const activeDomain = ref(props.domain || getLightFieldDomain())

const auroraVars = computed(() => {
  const palette = resolveDomainPalette(activeDomain.value)
  return {
    '--lf-primary': `${palette.primary[0]}, ${palette.primary[1]}, ${palette.primary[2]}`,
    '--lf-secondary': `${palette.secondary[0]}, ${palette.secondary[1]}, ${palette.secondary[2]}`,
  }
})

// 舞台负责粒子物理/视差投影/域染色/单帧编排；流动极光由 GPU 合成 CSS 层承担
const stage = createLightFieldStage({
  isDark: () => isDark.value,
  isShowcase: () => isShowcase.value,
})

const canvasRef = ref<HTMLCanvasElement | null>(null)
let raf = 0
let resizeRaf = 0
let reducedMotionMql: MediaQueryList | null = null
let unsubscribeBus: (() => void) | null = null
const systemReducedMotion = ref(false)

/** 静态渲染判定：系统 reduced-motion 或用户开启低动态 */
function shouldStatic(): boolean {
  return lowMotion.value || systemReducedMotion.value
}

// 静态模式（低动效/reduced-motion）不消费指针视差与点击波纹
const onMouseMove = (e: MouseEvent) => { if (!shouldStatic()) stage.onMouseMove(e) }
const INTERACTIVE_SKIP_SELECTOR = 'input, textarea, select, button, a, label, canvas, pre, code, [contenteditable="true"], [role="button"], [role="switch"], [role="slider"], [role="option"], [role="dialog"]'
const onPointerDown = (e: PointerEvent) => {
  if (shouldStatic() || document.hidden || e.button !== 0 || e.pointerType === 'touch') return
  const target = e.target instanceof Element ? e.target : null
  // 交互控件、画布图表、代码区与弹窗内部点击不触发背景水波，避免与按钮涟漪或图表拖拽叠加
  if (target && target.closest(INTERACTIVE_SKIP_SELECTOR)) return
  stage.onPointerDown(e)
}

function draw(now: number) {
  raf = 0
  const canvas = canvasRef.value
  if (!canvas) return
  if (!stage.draw(canvas, now)) return
  if (!shouldStatic() && !document.hidden) {
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
    if (shouldStatic()) {
      stage.settleStatic()
      draw(performance.now())
    }
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
  const initial = props.domain || getLightFieldDomain()
  activeDomain.value = initial
  stage.setDomain(initial, true)
  const canvas = canvasRef.value
  if (canvas) stage.resize(canvas)
  stage.centerPointer()
  window.addEventListener('resize', onWindowResize)
  window.addEventListener('mousemove', onMouseMove, { passive: true })
  window.addEventListener('pointerdown', onPointerDown, { passive: true })
  document.addEventListener('visibilitychange', onVisibilityChange)

  unsubscribeBus = subscribeLightField((event) => {
    if (event.type === 'domain') {
      activeDomain.value = event.domain || 'overview'
      const changed = stage.setDomain(event.domain, shouldStatic())
      if (changed && shouldStatic()) draw(performance.now())
      return
    }
    // 静态/低动态模式跳过跃迁与声呐动画
    if (shouldStatic() || document.hidden) return
    if (event.type === 'warp') {
      stage.triggerWarp(event.direction, event.intensity)
    } else if (event.type === 'sonar') {
      stage.triggerSonar(event.payload)
    }
  })

  syncLoop()
})

watch(() => props.domain, (domain) => {
  const normalized = domain || 'overview'
  activeDomain.value = normalized
  const changed = stage.setDomain(normalized, shouldStatic())
  if (changed && shouldStatic()) draw(performance.now())
})

watch(theme, () => {
  if (shouldStatic()) draw(performance.now())
})
watch(isShowcase, () => resize())
watch(lowMotion, () => syncLoop())

onUnmounted(() => {
  if (raf) cancelAnimationFrame(raf)
  if (resizeRaf) cancelAnimationFrame(resizeRaf)
  unsubscribeBus?.()
  reducedMotionMql?.removeEventListener('change', onReducedMotionChange)
  window.removeEventListener('resize', onWindowResize)
  window.removeEventListener('mousemove', onMouseMove)
  window.removeEventListener('pointerdown', onPointerDown)
  document.removeEventListener('visibilitychange', onVisibilityChange)
})
</script>

<style scoped>
.light-field-layer {
  position: fixed;
  inset: 0;
  z-index: 0;
  pointer-events: none;
  overflow: hidden;
}

/* 纯 GPU 合成流动极光柔光球（零每帧 Canvas 全屏填充） */
.light-field-aurora {
  position: absolute;
  border-radius: 50%;
  pointer-events: none;
  will-change: transform;
  opacity: 0.78;
}

.light-field-layer--showcase .light-field-aurora {
  opacity: 1;
}

.light-field-aurora--a {
  width: 68vmax;
  height: 68vmax;
  top: -22vmax;
  right: -12vmax;
  background: radial-gradient(
    circle at 50% 50%,
    rgba(var(--lf-primary, 18, 183, 245), var(--qq-aurora-alpha-a, 0.11)) 0%,
    rgba(var(--lf-primary, 18, 183, 245), 0) 68%
  );
  animation: lf-aurora-a 18s ease-in-out infinite alternate;
}

.light-field-aurora--b {
  width: 62vmax;
  height: 62vmax;
  bottom: -24vmax;
  left: -14vmax;
  background: radial-gradient(
    circle at 50% 50%,
    rgba(var(--lf-secondary, 6, 182, 212), var(--qq-aurora-alpha-b, 0.095)) 0%,
    rgba(var(--lf-secondary, 6, 182, 212), 0) 68%
  );
  animation: lf-aurora-b 22s ease-in-out infinite alternate;
}

@keyframes lf-aurora-a {
  from { transform: translate3d(0, 0, 0) scale(1); }
  to   { transform: translate3d(-5vw, 4vh, 0) scale(1.07); }
}

@keyframes lf-aurora-b {
  from { transform: translate3d(0, 0, 0) scale(1); }
  to   { transform: translate3d(6vw, -5vh, 0) scale(1.08); }
}

.light-field {
  position: absolute;
  inset: 0;
  width: 100%;
  height: 100%;
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

@media (prefers-reduced-motion: reduce) {
  .light-field-aurora {
    animation: none;
    will-change: auto;
  }
}
</style>

<style>
[data-theme="dark"] {
  --qq-aurora-alpha-a: 0.19;
  --qq-aurora-alpha-b: 0.16;
}

html[data-motion="reduced"] .light-field-aurora {
  animation: none;
  will-change: auto;
}
</style>
