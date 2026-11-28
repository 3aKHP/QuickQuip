<template>
  <label :class="['ui-toggle', `ui-toggle--${size}`, { 'ui-toggle--on': modelValue, 'ui-toggle--disabled': disabled, 'ui-toggle--squish': squishing }]">
    <input
      type="checkbox"
      class="ui-toggle__input"
      role="switch"
      :checked="modelValue"
      :aria-checked="modelValue"
      :aria-label="ariaLabel"
      :disabled="disabled"
      @change="toggle"
    />
    <span class="ui-toggle__track">
      <span class="ui-toggle__knob" />
    </span>
  </label>
</template>

<script setup lang="ts">
import { onUnmounted, ref, watch } from 'vue'
import { useMotionPrefs } from '../../composables/useMotionPrefs'

const props = withDefaults(defineProps<{
  modelValue?: boolean
  disabled?: boolean
  size?: 'md' | 'sm'
  ariaLabel?: string
}>(), {
  modelValue: false,
  size: 'md',
  ariaLabel: undefined,
})

const emit = defineEmits<{
  'update:modelValue': [value: boolean]
}>()

const { lowMotion } = useMotionPrefs()
const squishing = ref(false)
let squishTimer: ReturnType<typeof setTimeout> | null = null

function reducedMotion(): boolean {
  if (lowMotion.value) return true
  try {
    return typeof window !== 'undefined' && window.matchMedia('(prefers-reduced-motion: reduce)').matches
  } catch {
    return false
  }
}

// 切换状态时触发短瞬橡皮糖拉伸形变（190ms 后弹回正圆；低动态模式跳过）
watch(() => props.modelValue, () => {
  if (reducedMotion()) {
    squishing.value = false
    return
  }
  squishing.value = true
  if (squishTimer) clearTimeout(squishTimer)
  squishTimer = setTimeout(() => {
    squishing.value = false
    squishTimer = null
  }, 190)
})

function toggle(e: Event) {
  const input = e.target as HTMLInputElement
  const next = input.checked
  // 受控同步：先回正原生 checkbox，待父级异步/同步更新 modelValue 后再切换，防止接口失败后视觉卡死
  input.checked = props.modelValue
  emit('update:modelValue', next)
}

onUnmounted(() => {
  if (squishTimer) clearTimeout(squishTimer)
})
</script>

<style scoped>
.ui-toggle {
  position: relative;
  display: inline-flex;
  align-items: center;
  cursor: pointer;
}

.ui-toggle--disabled {
  opacity: 0.5;
  cursor: not-allowed;
}

.ui-toggle__input {
  position: absolute;
  opacity: 0;
  width: 1px;
  height: 1px;
  margin: 0;
  pointer-events: none;
}

.ui-toggle__track {
  position: relative;
  border-radius: var(--qq-radius-full);
  background: var(--qq-toggle-off);
  transition: background var(--qq-transition-base), box-shadow var(--qq-transition-base);
}

.ui-toggle__input:focus-visible + .ui-toggle__track {
  box-shadow: 0 0 0 3px var(--qq-primary-glow);
}

.ui-toggle__knob {
  position: absolute;
  background: var(--qq-white);
  border-radius: var(--qq-radius-full);
  box-shadow: 0 1px 3px rgba(0, 0, 0, 0.18);
  transition:
    transform var(--qq-transition-spring),
    width var(--qq-transition-spring-fast),
    margin-left var(--qq-transition-spring-fast);
}

/* md size: 34x20 track, 18x18 knob */
.ui-toggle--md .ui-toggle__track {
  width: 34px;
  height: 20px;
}

.ui-toggle--md .ui-toggle__knob {
  width: 18px;
  height: 18px;
  top: 1px;
  left: 1px;
}

.ui-toggle--md.ui-toggle--on .ui-toggle__track {
  background: var(--qq-primary);
  box-shadow: inset 0 0 0 1px rgba(255, 255, 255, 0.14), 0 0 10px var(--qq-primary-soft);
}

.ui-toggle--md.ui-toggle--on .ui-toggle__knob {
  transform: translateX(14px);
}

/* M3 Expressive 橡皮糖按压/切换拉伸 */
.ui-toggle--md:not(.ui-toggle--disabled):active .ui-toggle__knob,
.ui-toggle--md.ui-toggle--squish .ui-toggle__knob {
  width: 22px;
}

.ui-toggle--md.ui-toggle--on:not(.ui-toggle--disabled):active .ui-toggle__knob,
.ui-toggle--md.ui-toggle--on.ui-toggle--squish .ui-toggle__knob {
  margin-left: -4px;
}

/* sm size: 28x16 track, 14x14 knob */
.ui-toggle--sm .ui-toggle__track {
  width: 28px;
  height: 16px;
}

.ui-toggle--sm .ui-toggle__knob {
  width: 14px;
  height: 14px;
  top: 1px;
  left: 1px;
}

.ui-toggle--sm.ui-toggle--on .ui-toggle__track {
  background: var(--qq-primary);
  box-shadow: inset 0 0 0 1px rgba(255, 255, 255, 0.14), 0 0 8px var(--qq-primary-soft);
}

.ui-toggle--sm.ui-toggle--on .ui-toggle__knob {
  transform: translateX(12px);
}

.ui-toggle--sm:not(.ui-toggle--disabled):active .ui-toggle__knob,
.ui-toggle--sm.ui-toggle--squish .ui-toggle__knob {
  width: 17px;
}

.ui-toggle--sm.ui-toggle--on:not(.ui-toggle--disabled):active .ui-toggle__knob,
.ui-toggle--sm.ui-toggle--on.ui-toggle--squish .ui-toggle__knob {
  margin-left: -3px;
}

@media (prefers-reduced-motion: reduce) {
  .ui-toggle__track,
  .ui-toggle__knob {
    transition: none;
  }

  .ui-toggle--md:not(.ui-toggle--disabled):active .ui-toggle__knob,
  .ui-toggle--md.ui-toggle--squish .ui-toggle__knob {
    width: 18px;
  }

  .ui-toggle--md.ui-toggle--on:not(.ui-toggle--disabled):active .ui-toggle__knob,
  .ui-toggle--md.ui-toggle--on.ui-toggle--squish .ui-toggle__knob {
    margin-left: 0;
  }

  .ui-toggle--sm:not(.ui-toggle--disabled):active .ui-toggle__knob,
  .ui-toggle--sm.ui-toggle--squish .ui-toggle__knob {
    width: 14px;
  }

  .ui-toggle--sm.ui-toggle--on:not(.ui-toggle--disabled):active .ui-toggle__knob,
  .ui-toggle--sm.ui-toggle--on.ui-toggle--squish .ui-toggle__knob {
    margin-left: 0;
  }
}
</style>

<style>
html[data-motion="reduced"] .ui-toggle__track,
html[data-motion="reduced"] .ui-toggle__knob {
  transition: none;
}

html[data-motion="reduced"] .ui-toggle--md:not(.ui-toggle--disabled):active .ui-toggle__knob,
html[data-motion="reduced"] .ui-toggle--md.ui-toggle--squish .ui-toggle__knob {
  width: 18px;
}

html[data-motion="reduced"] .ui-toggle--md.ui-toggle--on:not(.ui-toggle--disabled):active .ui-toggle__knob,
html[data-motion="reduced"] .ui-toggle--md.ui-toggle--on.ui-toggle--squish .ui-toggle__knob {
  margin-left: 0;
}

html[data-motion="reduced"] .ui-toggle--sm:not(.ui-toggle--disabled):active .ui-toggle__knob,
html[data-motion="reduced"] .ui-toggle--sm.ui-toggle--squish .ui-toggle__knob {
  width: 14px;
}

html[data-motion="reduced"] .ui-toggle--sm.ui-toggle--on:not(.ui-toggle--disabled):active .ui-toggle__knob,
html[data-motion="reduced"] .ui-toggle--sm.ui-toggle--on.ui-toggle--squish .ui-toggle__knob {
  margin-left: 0;
}
</style>
