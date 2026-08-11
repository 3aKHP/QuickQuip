<template>
  <div ref="el" class="e-chart" :style="{ height: `${height}px` }" />
</template>

<script setup lang="ts">
/**
 * 通用 ECharts 容器组件。
 * - echarts 通过动态 import 加载，独立异步 chunk，不拖慢首屏；
 * - option 变化时整体重建 setOption（notMerge）；主题切换时由父级重建 option 传入；
 * - ResizeObserver 自适应容器宽度，卸载时自动 dispose。
 */
import { onBeforeUnmount, onMounted, ref, watch } from 'vue'
import type { ECOption, ECElementEvent } from '../../charts/echarts'
import type { echarts as echartsApi } from '../../charts/echarts'

const props = withDefaults(defineProps<{
  option: ECOption
  height?: number
}>(), {
  height: 260,
})

const emit = defineEmits<{
  click: [params: ECElementEvent]
}>()

const el = ref<HTMLDivElement | null>(null)
let chart: echartsApi.ECharts | null = null
let resizeObserver: ResizeObserver | null = null

function render() {
  if (!chart || !props.option) return
  chart.setOption(props.option, { notMerge: true })
}

onMounted(async () => {
  const { echarts } = await import('../../charts/echarts')
  if (!el.value) return
  chart = echarts.init(el.value)
  chart.on('click', params => emit('click', params))
  render()
  resizeObserver = new ResizeObserver(() => chart?.resize())
  resizeObserver.observe(el.value)
})

watch(() => props.option, render, { deep: true })

onBeforeUnmount(() => {
  resizeObserver?.disconnect()
  chart?.dispose()
  chart = null
})
</script>

<style scoped>
.e-chart {
  width: 100%;
}
</style>
