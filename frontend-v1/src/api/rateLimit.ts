import { request } from './index'

export async function fetchRateLimit() {
  return request('/api/rate-limit')
}
