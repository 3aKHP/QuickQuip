<template>
  <div ref="rootRef" class="ui-tabs" role="tablist">
    <div
      v-if="indicator.ready"
      class="ui-tabs__indicator"
      :style="indicatorStyle"
      aria-hidden="true"
    />
    <button
      v-for="t in tabs"
      :key="t.key"
      ref="btnRefs"
      type="button"
      role="tab"
      class="ui-tabs__btn"
      :class="{ 'ui-tabs__btn--active': modelValue === t.key }"
      :aria-selected="modelValue === t.key"
      @click="select(t.key)"
    >
      <span class="ui-tabs__label">{{ t.label }}</span>
      <span v-if="t.sub" class="ui-tabs__sub">{{ t.sub }}</span>
    </button>
  </div>
</template>

<script setup lang="ts">
import { computed, nextTick, onMounted, onUnmounted, reactive, ref, watch } from 'vue'

export interface UiTabItem {
  key: string
  label: string
  /** 副标题（如文件名），纵向排列在主标签下方 */
  sub?: string
}

const props = defineProps<{
  tabs: UiTabItem[]
  modelValue: string
}>()

const emit = defineEmits<{
  'update:modelValue': [key: string]
  change: [key: string]
}>()

const rootRef = ref<HTMLElement | null>(null)
const btnRefs = ref<HTMLElement[]>([])
const indicator = reactive({ ready: false, x: 0, y: 0, w: 0, h: 0 })

const indicatorStyle = computed(() => ({
  transform: `translate(${indicator.x}px, ${indicator.y}px)`,
  width: `${indicator.w}px`,
  height: `${indicator.h}px`,
}))

function measure() {
  const idx = props.tabs.findIndex((t) => t.key === props.modelValue)
  const btn = btnRefs.value?.[idx]
  if (!btn) return
  indicator.x = btn.offsetLeft
  indicator.y = btn.offsetTop
  indicator.w = btn.offsetWidth
  indicator.h = btn.offsetHeight
  indicator.ready = true
}

function select(key: string) {
  if (key === props.modelValue) return
  emit('update:modelValue', key)
  emit('change', key)
}

let resizeObserver: ResizeObserver | null = null

onMounted(() => {
  nextTick(measure)
  if (rootRef.value && typeof ResizeObserver !== 'undefined') {
    resizeObserver = new ResizeObserver(() => measure())
    resizeObserver.observe(rootRef.value)
  }
})

watch(() => props.modelValue, () => nextTick(measure))
watch(() => props.tabs, () => nextTick(measure), { deep: true })

onUnmounted(() => {
  resizeObserver?.disconnect()
})
</script>

<style scoped>
.ui-tabs {
  position: relative;
  display: inline-flex;
  flex-wrap: wrap;
  gap: 2px;
  padding: 3px;
  border: 1px solid var(--qq-border);
  border-radius: var(--qq-radius-card);
  background: var(--qq-surface-strong);
}

/* 滑动指示条：药丸背景跟随选中项 */
.ui-tabs__indicator {
  position: absolute;
  top: 0;
  left: 0;
  border-radius: calc(var(--qq-radius-card) - 3px);
  background: var(--qq-surface);
  box-shadow: var(--qq-shadow-card);
  transition:
    transform var(--qq-transition-slow),
    width var(--qq-transition-slow),
    height var(--qq-transition-slow);
  pointer-events: none;
}

.ui-tabs__btn {
  position: relative;
  z-index: 1;
  display: flex;
  flex-direction: column;
  align-items: center;
  justify-content: center;
  gap: 1px;
  border: 0;
  padding: 5px 14px;
  border-radius: calc(var(--qq-radius-card) - 3px);
  background: transparent;
  color: var(--qq-text-muted);
  font-family: var(--qq-font-base);
  font-size: var(--qq-text-sm);
  cursor: pointer;
  transition: color var(--qq-transition-fast);
}

.ui-tabs__btn:hover {
  color: var(--qq-text);
}

.ui-tabs__btn--active {
  color: var(--qq-text);
}

.ui-tabs__sub {
  font-size: var(--qq-text-xs);
  color: var(--qq-text-quiet);
}

@media (prefers-reduced-motion: reduce) {
  .ui-tabs__indicator {
    transition: none;
  }
}
</style>
