import { request } from './index'

export interface ConfigListItem {
  key: string
  filename: string
  label: string
  description?: string
  missing?: boolean
}

export async function listConfigs() {
  return request<{ configs: ConfigListItem[] }>('/api/config')
}

export async function fetchConfig(key: string) {
  return request(`/api/config/${encodeURIComponent(key)}`)
}

export async function saveConfig(key: string, content: string) {
  return request(`/api/config/${encodeURIComponent(key)}`, {
    method: 'PUT',
    body: JSON.stringify({ content }),
  })
}
