import { request } from './index.js'

export async function fetchRateLimit() {
  return request('/api/rate-limit')
}
