import { request } from './index'

export type PeriodType = 'weekly' | 'monthly'

/** 对应 GET /api/period-reports/{group_id}/{period_type} 列表元素（无 content） */
export interface PeriodReportRow {
  group_id: string
  period_type: string
  period_key: string
  generated_at: string
  published_at: string | null
  model_used: string | null
  char_count: number | null
}

/** 对应 GET /api/period-reports/{group_id}/{period_type}/{period_key}（SELECT *，含 content 与自增 id） */
export interface PeriodReportDetail extends PeriodReportRow {
  id: number
  content: string
}

export async function fetchPeriodReportGroups(periodType: PeriodType): Promise<string[]> {
  return request(`/api/period-reports-groups/${periodType}`)
}

export async function fetchPeriodReports(groupId: string, periodType: PeriodType): Promise<PeriodReportRow[]> {
  return request(`/api/period-reports/${groupId}/${periodType}`)
}

export async function fetchPeriodReportDetail(
  groupId: string,
  periodType: PeriodType,
  periodKey: string,
): Promise<PeriodReportDetail> {
  return request(`/api/period-reports/${groupId}/${periodType}/${encodeURIComponent(periodKey)}`)
}

export async function deletePeriodReport(
  groupId: string,
  periodType: PeriodType,
  periodKey: string,
): Promise<{ ok: boolean }> {
  return request(`/api/period-reports/${groupId}/${periodType}/${encodeURIComponent(periodKey)}`, {
    method: 'DELETE',
  })
}
