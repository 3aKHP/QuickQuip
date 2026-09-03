import { request } from './index'

export interface CronJob {
  id: string
  name: string
  trigger: string
  next_run: string | null
  last_run: string | null
  last_status: string | null
  last_error: string | null
}

export interface CronDashboardResponse {
  jobs: CronJob[]
  updated_at?: string | null
}

export async function fetchCronDashboard(): Promise<CronDashboardResponse> {
  return request('/api/cron-dashboard')
}
