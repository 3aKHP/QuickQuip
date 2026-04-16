import { request } from './index.js'

export async function fetchOptions() {
  return request('/api/group-settings/options')
}

export async function listGroupSettings() {
  return request('/api/group-settings')
}

export async function fetchGroupSettings(groupId) {
  return request(`/api/group-settings/${encodeURIComponent(groupId)}`)
}

export async function saveGroupSettings(groupId, fields) {
  return request(`/api/group-settings/${encodeURIComponent(groupId)}`, {
    method: 'PUT',
    body: JSON.stringify(fields),
  })
}

export async function clearGroupSettings(groupId) {
  return request(`/api/group-settings/${encodeURIComponent(groupId)}`, {
    method: 'DELETE',
  })
}
