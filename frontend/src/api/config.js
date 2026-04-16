import { request } from './index.js'

export async function listConfigs() {
  return request('/api/config')
}

export async function fetchConfig(key) {
  return request(`/api/config/${encodeURIComponent(key)}`)
}

export async function saveConfig(key, content) {
  return request(`/api/config/${encodeURIComponent(key)}`, {
    method: 'PUT',
    body: JSON.stringify({ content }),
  })
}
