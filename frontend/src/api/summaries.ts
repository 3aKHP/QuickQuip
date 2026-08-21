import { request } from './index'
import type { PeriodReportDetail, PeriodReportRow } from './period_reports'

/** 对应 GET /api/summaries/{group_id} 列表元素（summaries 表投影，无 content） */
export interface SummaryRow {
  group_id: string
  summary_date: string
  generated_at: string
  published_at: string | null
  model_used: string | null
  char_count: number | null
}

/** 对应 GET /api/summaries/{group_id}/{date}（SELECT *，含 content 与自增 id） */
export interface SummaryDetail extends SummaryRow {
  id: number
  content: string
}

/** SummaryView 跨 tab 共用的列表行：每日总结或周期报告 */
export type SummaryListRow = SummaryRow | PeriodReportRow

/** SummaryView 详情行：对应两类详情响应的并集 */
export type SummaryDetailRow = SummaryDetail | PeriodReportDetail

export async function fetchSummaryGroups(): Promise<string[]> {
  return request('/api/summaries-groups')
}

export async function fetchSummaries(groupId: string): Promise<SummaryRow[]> {
  return request(`/api/summaries/${groupId}`)
}

export async function fetchSummaryDetail(groupId: string, date: string): Promise<SummaryDetail> {
  return request(`/api/summaries/${groupId}/${date}`)
}

export async function deleteSummary(groupId: string, date: string): Promise<{ ok: boolean }> {
  return request(`/api/summaries/${groupId}/${date}`, { method: 'DELETE' })
}
