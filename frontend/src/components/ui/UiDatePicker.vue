<template>
  <VueDatePicker
    class="ui-date-picker"
    :model-value="inner"
    :model-type="modelType"
    :time-picker="mode === 'time'"
    :time-config="timeConfig"
    :formats="{ input: modelType }"
    :locale="zhCN"
    :dark="theme === 'dark'"
    :config="{ monthChangeOnScroll: false }"
    :aria-labels="ariaLabel ? { input: ariaLabel } : undefined"
    :placeholder="placeholder"
    auto-apply
    text-input
    clearable
    teleport
    @update:model-value="onUpdate"
  />
</template>

<script setup lang="ts">
/**
 * 日期/时间选择器（@vuepic/vue-datepicker 封装）。
 * - 字符串契约：date 模式 '' | "yyyy-MM-dd"，time 模式 '' | "HH:mm"——与被替换的
 *   原生 input[type=date/time] v-model 完全一致，调用方的 watch/组装/校验零改动；
 * - 库清空时 emit null，统一归一为 ''；防御性兼容字符串 / Date / {hours,minutes}
 *   三种形态，model-type 若有行为出入时降级正确而非坏值；
 * - 弹层 teleport 到 body（避免被 UiCard 的 overflow:hidden 裁剪），暗色走 :dark
 *   prop + styles/datepicker.css 的 --dp-* → --qq-* 变量重映射；
 * - text-input 模式保留键盘输入（E2E fill 亦依赖），auto-apply 免掉英文操作行。
 */
import { computed } from 'vue'
import { VueDatePicker } from '@vuepic/vue-datepicker'
import { zhCN } from 'date-fns/locale'
import { format } from 'date-fns'
import { useTheme } from '../../composables/useTheme'

const props = withDefaults(defineProps<{
  /** '' 或模式对应格式的字符串 */
  modelValue: string
  mode?: 'date' | 'time'
  placeholder?: string
  /** 输入框的可读名称（库经 aria-labels.input 透传，attr 不回落） */
  ariaLabel?: string
}>(), {
  mode: 'date',
})

const emit = defineEmits<{
  'update:modelValue': [value: string]
}>()

const { theme } = useTheme()

const modelType = computed(() => (props.mode === 'time' ? 'HH:mm' : 'yyyy-MM-dd'))

const timeConfig = computed(() => (
  props.mode === 'time'
    ? { is24: true }
    // enableTimePicker 默认 true，date 模式必须显式关闭，否则会长出时间区
    : { enableTimePicker: false }
))

const inner = computed(() => props.modelValue || null)

function onUpdate(value: unknown) {
  if (value == null || value === '') {
    emit('update:modelValue', '')
    return
  }
  if (typeof value === 'string') {
    emit('update:modelValue', value)
    return
  }
  if (value instanceof Date) {
    emit('update:modelValue', format(value, modelType.value))
    return
  }
  if (typeof value === 'object' && 'hours' in (value as Record<string, unknown>)) {
    const t = value as { hours?: number; minutes?: number }
    const h = String(t.hours ?? 0).padStart(2, '0')
    const m = String(t.minutes ?? 0).padStart(2, '0')
    emit('update:modelValue', `${h}:${m}`)
    return
  }
  emit('update:modelValue', '')
}
</script>

<style scoped>
.ui-date-picker {
  width: 100%;
  min-width: 0;
}

/* base.css 的全局 input[type=text] 会作用于选择器输入框（36px 高/边框，视觉一致），
   但它的 padding（7px 11px）也压掉了库的图标避让（--dp-input-icon-padding）：
   日历/时钟图标 absolute 定位在输入框左缘，clear 图标在右缘，两侧都要补避让 */
.ui-date-picker :deep(input.dp--input) {
  padding-inline: 40px;
}
</style>
