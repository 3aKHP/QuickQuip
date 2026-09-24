/**
 * ECharts 按需注册中心。
 * 所有图表组件统一从这里 import，避免全量打包；
 * 新增图表类型时在此补充 use() 注册即可。
 */
import * as echarts from 'echarts/core'
import { BarChart, LineChart, ScatterChart } from 'echarts/charts'
import {
  DataZoomComponent,
  GridComponent,
  MarkAreaComponent,
  MarkLineComponent,
  TooltipComponent,
} from 'echarts/components'
import { CanvasRenderer } from 'echarts/renderers'
import type { ComposeOption } from 'echarts/core'
import type {
  BarSeriesOption,
  LineSeriesOption,
  ScatterSeriesOption,
} from 'echarts/charts'
import type {
  DataZoomComponentOption,
  GridComponentOption,
  MarkAreaComponentOption,
  MarkLineComponentOption,
  TooltipComponentOption,
} from 'echarts/components'

echarts.use([
  LineChart,
  BarChart,
  ScatterChart,
  GridComponent,
  TooltipComponent,
  DataZoomComponent,
  MarkLineComponent,
  MarkAreaComponent,
  CanvasRenderer,
])

export type ECOption = ComposeOption<
  | LineSeriesOption
  | BarSeriesOption
  | ScatterSeriesOption
  | GridComponentOption
  | TooltipComponentOption
  | DataZoomComponentOption
  | MarkLineComponentOption
  | MarkAreaComponentOption
>

export type { ECElementEvent } from 'echarts/core'

export { echarts }
