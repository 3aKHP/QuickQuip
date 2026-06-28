import { request } from './index'

export type PeriodType = 'weekly' | 'monthly'

export async function fetchPeriodReportGroups(periodType: PeriodType) {
  return request(`/api/period-reports-groups/${periodType}`)
}

export async function fetchPeriodReports(groupId: string, periodType: PeriodType) {
  return request(`/api/period-reports/${groupId}/${periodType}`)
}

export async function fetchPeriodReportDetail(
  groupId: string,
  periodType: PeriodType,
  periodKey: string,
) {
  return request(`/api/period-reports/${groupId}/${periodType}/${encodeURIComponent(periodKey)}`)
}

export async function deletePeriodReport(
  groupId: string,
  periodType: PeriodType,
  periodKey: string,
) {
  return request(`/api/period-reports/${groupId}/${periodType}/${encodeURIComponent(periodKey)}`, {
    method: 'DELETE',
  })
}
