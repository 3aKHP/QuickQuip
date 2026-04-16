import { request } from './index.js'

export async function fetchStats() {
  return request('/api/stats')
}
