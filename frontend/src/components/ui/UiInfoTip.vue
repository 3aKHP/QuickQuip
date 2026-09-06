<template>
  <span
    ref="rootEl"
    class="ui-info-tip"
    @focusin="open = true"
    @focusout="open = false"
  >
    <button
      ref="btnEl"
      type="button"
      class="ui-info-tip__btn"
      :aria-label="ariaLabel ?? '查看说明'"
      :aria-expanded="open"
      :aria-describedby="open ? tipId : undefined"
      @mouseenter="open = true"
      @mouseleave="open = false"
      @click.stop="open = true"
      @keydown.esc.stop.prevent="open = false"
    >
      <UiIcon name="CircleHelp" :size="size" />
    </button>
    <Transition name="ui-info-tip">
      <span
        v-if="open"
        :id="tipId"
        ref="bubbleEl"
        role="tooltip"
        class="ui-info-tip__bubble"
        :style="pos"
      >
        <slot>{{ text }}</slot>
      </span>
    </Transition>
  </span>
</template>

<script setup lang="ts">
/**
 * 「?」悬浮说明。hover / 键盘聚焦显示，点击固定显示（触屏主路径），
 * Esc、点击外部或页面滚动关闭。说明文案走 text 属性，复杂内容用插槽覆盖。
 *
 * 气泡为 position: fixed + 打开时 JS 实测像素坐标：absolute + 百分比居中
 * 会被滚动容器（.content）的溢出裁切吃掉越界部分，且个别引擎存在包含块
 * 偏移怪癖；fixed 直接脱离滚动容器，坐标由视口计算，不依赖 CSS 定位技巧。
 */
import { nextTick, onBeforeUnmount, ref, watch } from 'vue'
import UiIcon from './UiIcon.vue'

withDefaults(defineProps<{
  /** 说明文案（无插槽时显示） */
  text?: string
  /** 图标尺寸，默认 13 */
  size?: number
  /** 无障碍朗读标签，默认「查看说明」 */
  ariaLabel?: string
}>(), {
  text: undefined,
  size: 13,
  ariaLabel: undefined,
})

const tipId = `ui-info-tip-${Math.random().toString(36).slice(2)}`
const open = ref(false)
const rootEl = ref<HTMLElement | null>(null)
const btnEl = ref<HTMLElement | null>(null)
const bubbleEl = ref<HTMLElement | null>(null)
const pos = ref<{ left: string; top: string; width: string }>({ left: '0px', top: '0px', width: '280px' })

/** 按触发点居中放置气泡，并夹取在视口内（左右各留 8px 边距）。 */
function place() {
  const btn = btnEl.value
  const bub = bubbleEl.value
  if (!btn || !bub) return
  const t = btn.getBoundingClientRect()
  const b = bub.getBoundingClientRect()
  const vw = document.documentElement.clientWidth
  const vh = document.documentElement.clientHeight
  const width = Math.min(280, vw - 24)
  let left = t.left + t.width / 2 - width / 2
  left = Math.min(Math.max(8, left), vw - width - 8)
  const above = t.top - b.height - 8 >= 8
  let top = above ? t.top - b.height - 8 : t.bottom + 8
  top = Math.min(Math.max(8, top), vh - b.height - 8)
  pos.value = { left: `${Math.round(left)}px`, top: `${Math.round(top)}px`, width: `${width}px` }
}

function onDocClick(e: MouseEvent) {
  if (!rootEl.value?.contains(e.target as Node)) open.value = false
}

function onScroll() {
  open.value = false
}

watch(open, async (v) => {
  if (v) {
    await nextTick()
    place()
    // 宽度收紧后行数可能变化，下一帧按最终高度复核一次纵向位置
    requestAnimationFrame(place)
    document.addEventListener('click', onDocClick, { capture: true })
    window.addEventListener('scroll', onScroll, { capture: true, passive: true })
    window.addEventListener('resize', onScroll)
  } else {
    document.removeEventListener('click', onDocClick, { capture: true })
    window.removeEventListener('scroll', onScroll, { capture: true })
    window.removeEventListener('resize', onScroll)
  }
})

onBeforeUnmount(() => {
  document.removeEventListener('click', onDocClick, { capture: true })
  window.removeEventListener('scroll', onScroll, { capture: true })
  window.removeEventListener('resize', onScroll)
})
</script>

<style scoped>
.ui-info-tip {
  position: relative;
  display: inline-flex;
  flex-shrink: 0;
}

.ui-info-tip__btn {
  display: inline-flex;
  align-items: center;
  justify-content: center;
  padding: 1px;
  border: 0;
  border-radius: var(--qq-radius-full);
  background: transparent;
  color: var(--qq-text-muted);
  cursor: help;
  transition: color var(--qq-transition-fast);
}

.ui-info-tip__btn:hover,
.ui-info-tip__btn:focus-visible {
  color: var(--qq-primary);
  outline: none;
}

.ui-info-tip__bubble {
  position: fixed;
  z-index: 70;
  padding: 10px 12px;
  border: 1px solid var(--qq-shell-glass-border);
  border-radius: var(--qq-radius-card);
  background:
    linear-gradient(180deg, var(--qq-shell-glass-highlight), transparent 58%),
    var(--qq-shell-drawer-bg);
  color: var(--qq-text);
  font-size: var(--qq-text-xs);
  line-height: 1.7;
  text-align: left;
  white-space: normal;
  box-shadow: var(--qq-shadow-md);
  backdrop-filter: blur(16px) saturate(1.2);
  -webkit-backdrop-filter: blur(16px) saturate(1.2);
  pointer-events: none;
}

.ui-info-tip-enter-active,
.ui-info-tip-leave-active {
  transition: opacity 140ms var(--qq-ease-out);
}

.ui-info-tip-enter-from,
.ui-info-tip-leave-to {
  opacity: 0;
}
</style>
