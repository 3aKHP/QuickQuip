import { request } from './index.js'

export async function fetchGroups() {
  return request('/api/groups')
}

export async function fetchKnownGroups() {
  return request('/api/groups/known').catch(() => ({ groups: [] }))
}

export async function updateGroup(type, gid, enabled) {
  return request(`/api/groups/${type}/${gid}`, {
    method: 'POST',
    body: JSON.stringify({ enabled }),
  })
}
