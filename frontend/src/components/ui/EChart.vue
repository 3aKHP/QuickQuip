<template>
  <div ref="el" class="e-chart" :style="{ height: `${height}px` }" />
</template>

<script setup lang="ts">
/**
 * 通用 ECharts 容器组件。
 * - echarts 通过动态 import 加载，独立异步 chunk，不拖慢首屏；
 * - option 变化时整体重建 setOption（notMerge）；父级 option 必须由 computed
 *   产出新引用（本组件不做 deep watch），主题切换时由父级重建 option 传入；
 * - cursorAt 是轻量增量通道：仅按 id 合并 cursor 系列的 markLine.data
 *   （样式沿用整树 option 中的定义），供播放/擦洗类高频移动使用；
 * - ResizeObserver 自适应容器宽度，卸载时自动 dispose。
 * - plotClick 开启后额外透传"绘图区空白点击"的 x 轴数值（zr click →
 *   convertFromPixel），供时间轴擦洗类交互使用；系列点击不受影响。
 */
import { onBeforeUnmount, onMounted, ref, watch } from 'vue'
import type { ECOption, ECElementEvent } from '../../charts/echarts'
import type { echarts as echartsApi } from '../../charts/echarts'

const props = withDefaults(defineProps<{
  option: ECOption
  height?: number
  plotClick?: boolean
  /** cursor 竖线的 x 轴位置；undefined = 不启用增量 cursor 通道，null = 隐藏 */
  cursorAt?: number | null
}>(), {
  height: 260,
  plotClick: false,
})

const emit = defineEmits<{
  click: [params: ECElementEvent]
  'plot-click': [xValue: number]
}>()

const el = ref<HTMLDivElement | null>(null)
let chart: echartsApi.ECharts | null = null
let resizeObserver: ResizeObserver | null = null

/** 仅更新 cursor markLine 的数据位；未指定 id 的 option（无 cursor 系列）不受影响 */
function applyCursor() {
  if (!chart || props.cursorAt === undefined) return
  chart.setOption({
    series: [{
      id: 'cursor',
      markLine: { data: props.cursorAt != null ? [{ xAxis: props.cursorAt }] : [] },
    }],
  })
}

function render() {
  if (!chart || !props.option) return
  chart.setOption(props.option, { notMerge: true })
  // 整树重建会冲掉 cursor 增量，重建后按当前 cursorAt 回补
  applyCursor()
}

onMounted(async () => {
  const { echarts } = await import('../../charts/echarts')
  if (!el.value) return
  chart = echarts.init(el.value)
  chart.on('click', params => emit('click', params))
  render()
  if (props.plotClick) {
    chart.getZr().on('click', (params: { offsetX?: number; offsetY?: number }) => {
      if (!chart || params.offsetX == null || params.offsetY == null) return
      try {
        const point = chart.convertFromPixel({ seriesIndex: 0 }, [params.offsetX, params.offsetY])
        if (point && Number.isFinite(point[0])) emit('plot-click', point[0])
      } catch {
        // 系列未渲染/坐标系不可转换时静默忽略（如空数据首帧）
      }
    })
  }
  resizeObserver = new ResizeObserver(() => chart?.resize())
  resizeObserver.observe(el.value)
})

watch(() => props.option, render)
watch(() => props.cursorAt, applyCursor)

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
