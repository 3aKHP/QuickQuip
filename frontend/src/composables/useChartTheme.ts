/**
 * 从 QQ 设计变量运行时解析出的 ECharts 配色/基础样式。
 * 通过 getComputedStyle 读取 --qq-* 变量，保证图表配色与
 * variables.css 的设计系统（含暗色主题）始终一致。
 */
import { computed } from 'vue'
import { useTheme } from './useTheme'

export interface ChartTheme {
  primary: string
  cyan: string
  accent: string
  success: string
  warn: string
  danger: string
  text: string
  textMuted: string
  border: string
  gridLine: string
  surface: string
  surfaceElevated: string
  /** 多系列默认色板（主色 → 青 → 琥珀 → 语义色） */
  palette: string[]
  /** 坐标轴 / tooltip 的通用样式片段 */
  axisLine: { lineStyle: { color: string } }
  axisLabel: { color: string; fontSize: number }
  splitLine: { lineStyle: { color: string } }
  tooltip: {
    backgroundColor: string
    borderColor: string
    textStyle: { color: string; fontSize: number }
  }
}

function readCssVars(): ChartTheme {
  const style = getComputedStyle(document.documentElement)
  const get = (name: string, fallback: string) => style.getPropertyValue(name).trim() || fallback

  const primary = get('--qq-primary', '#12b7f5')
  const cyan = get('--qq-cyan', '#06b6d4')
  const accent = get('--qq-accent', '#f59e0b')
  const success = get('--qq-success', '#07c160')
  const warn = get('--qq-warn', '#fa9d3b')
  const danger = get('--qq-danger', '#fa5151')
  const text = get('--qq-text', '#1c2330')
  const textMuted = get('--qq-text-muted', '#5b6678')
  const border = get('--qq-border', 'rgba(0, 0, 0, 0.08)')
  const gridLine = get('--qq-grid-line', 'rgba(18, 60, 95, 0.040)')
  const surface = get('--qq-surface', '#ffffff')
  const surfaceElevated = get('--qq-surface-elevated', '#f8f9fb')

  return {
    primary,
    cyan,
    accent,
    success,
    warn,
    danger,
    text,
    textMuted,
    border,
    gridLine,
    surface,
    surfaceElevated,
    palette: [primary, cyan, accent, success, warn, danger],
    axisLine: { lineStyle: { color: border } },
    axisLabel: { color: textMuted, fontSize: 11 },
    splitLine: { lineStyle: { color: gridLine } },
    tooltip: {
      backgroundColor: surfaceElevated,
      borderColor: border,
      textStyle: { color: text, fontSize: 12 },
    },
  }
}

export function useChartTheme() {
  const { theme } = useTheme()
  // theme 变化时 data-theme 属性已同步更新，重新读取变量即可
  const chartTheme = computed<ChartTheme>(() => {
    void theme.value
    return readCssVars()
  })
  return { chartTheme }
}
