import { request } from './index'

export async function fetchStats() {
  return request('/api/stats')
}
