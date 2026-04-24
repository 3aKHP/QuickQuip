import { request } from './index'

export async function fetchOptions() {
  return request('/api/group-settings/options')
}

export async function listGroupSettings() {
  return request('/api/group-settings')
}

export async function fetchGroupSettings(groupId: string) {
  return request(`/api/group-settings/${encodeURIComponent(groupId)}`)
}

export async function saveGroupSettings(groupId: string, fields: Record<string, unknown>) {
  return request(`/api/group-settings/${encodeURIComponent(groupId)}`, {
    method: 'PUT',
    body: JSON.stringify(fields),
  })
}

export async function clearGroupSettings(groupId: string) {
  return request(`/api/group-settings/${encodeURIComponent(groupId)}`, {
    method: 'DELETE',
  })
}
