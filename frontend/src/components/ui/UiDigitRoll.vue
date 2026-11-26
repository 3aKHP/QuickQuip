<template>
  <span class="ui-digit-roll">
    <template v-if="staticMode">
      <span>{{ text }}</span>
    </template>
    <template v-else>
      <span class="ui-digit-roll__sr">{{ text }}</span>
      <span class="ui-digit-roll__visual" aria-hidden="true">
        <template v-for="tok in tokens" :key="tok.key">
          <span v-if="tok.digit !== null" class="ui-digit-roll__slot">
            <span
              class="ui-digit-roll__track"
              :class="{ 'ui-digit-roll__track--animated': ready }"
              :style="{ transform: `translateY(-${(ready ? tok.digit : 0) * 10}%)` }"
            >
              <span v-for="n in DIGITS" :key="n" class="ui-digit-roll__num">{{ n }}</span>
            </span>
          </span>
          <span v-else class="ui-digit-roll__sep">{{ tok.char }}</span>
        </template>
      </span>
    </template>
  </span>
</template>

<script setup lang="ts">
import { computed, onBeforeUnmount, onMounted, ref } from 'vue'
import { useMotionPrefs } from '../../composables/useMotionPrefs'

const DIGITS = [0, 1, 2, 3, 4, 5, 6, 7, 8, 9] as const

const props = defineProps<{
  value: string | number
}>()

const { lowMotion } = useMotionPrefs()
const systemReduced = ref(false)
const ready = ref(false)
let raf1 = 0
let raf2 = 0
let mql: MediaQueryList | null = null

const text = computed(() => String(props.value ?? ''))
const staticMode = computed(() => lowMotion.value || systemReduced.value)

interface CharToken {
  key: string
  char: string
  digit: number | null
}

// 从右向左给数字位编号（d-0 为最末位），避免千分位位数变化时左侧旧滚轮整体错位重滚
const tokens = computed<CharToken[]>(() => {
  const chars = Array.from(text.value)
  let digitPosFromRight = 0
  const result: CharToken[] = new Array(chars.length)
  for (let i = chars.length - 1; i >= 0; i--) {
    const ch = chars[i]
    if (ch >= '0' && ch <= '9') {
      result[i] = { key: `d-${digitPosFromRight++}`, char: ch, digit: Number(ch) }
    } else {
      result[i] = { key: `s-${chars.length - 1 - i}-${ch}`, char: ch, digit: null }
    }
  }
  return result
})

function onMqlChange(e: MediaQueryListEvent) {
  systemReduced.value = e.matches
}

onMounted(() => {
  try {
    mql = window.matchMedia('(prefers-reduced-motion: reduce)')
    systemReduced.value = mql.matches
    mql.addEventListener('change', onMqlChange)
  } catch { /* ignore */ }
  // 双 RAF 确保首帧 translateY(0%) 完成绘制后再启动滚轮过渡，兼容 Firefox/Safari
  if (typeof requestAnimationFrame === 'function') {
    raf1 = requestAnimationFrame(() => {
      raf1 = 0
      raf2 = requestAnimationFrame(() => {
        raf2 = 0
        ready.value = true
      })
    })
  } else {
    ready.value = true
  }
})

onBeforeUnmount(() => {
  if (raf1) cancelAnimationFrame(raf1)
  if (raf2) cancelAnimationFrame(raf2)
  mql?.removeEventListener('change', onMqlChange)
})
</script>

<style scoped>
.ui-digit-roll {
  position: relative;
  display: inline-flex;
  align-items: center;
  font-variant-numeric: tabular-nums;
}

.ui-digit-roll__sr {
  position: absolute;
  width: 1px;
  height: 1px;
  padding: 0;
  margin: -1px;
  overflow: hidden;
  clip: rect(0, 0, 0, 0);
  white-space: nowrap;
  border: 0;
}

.ui-digit-roll__visual {
  display: inline-flex;
  align-items: center;
}

.ui-digit-roll__slot {
  position: relative;
  display: inline-block;
  height: 1.15em;
  line-height: 1.15em;
  overflow: hidden;
  -webkit-mask-image: linear-gradient(180deg, transparent 0%, #000 12%, #000 88%, transparent 100%);
  mask-image: linear-gradient(180deg, transparent 0%, #000 12%, #000 88%, transparent 100%);
}

.ui-digit-roll__track {
  display: flex;
  flex-direction: column;
}

.ui-digit-roll__track--animated {
  transition: transform 440ms var(--qq-ease-spring-soft);
}

.ui-digit-roll__num {
  display: block;
  height: 1.15em;
  line-height: 1.15em;
  text-align: center;
}

.ui-digit-roll__sep {
  display: inline-block;
  height: 1.15em;
  line-height: 1.15em;
}

@media (prefers-reduced-motion: reduce) {
  .ui-digit-roll__track--animated {
    transition: none;
  }
}
</style>

<style>
html[data-motion="reduced"] .ui-digit-roll__track--animated {
  transition: none;
}
</style>
