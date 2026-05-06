import { request } from './index'

export async function fetchGroups() {
  return request('/api/groups')
}

export async function fetchKnownGroups() {
  return request('/api/groups/known').catch(() => ({ groups: [] }))
}

export async function updateGroup(type: string, gid: string | number, enabled: boolean) {
  return request(`/api/groups/${type}/${gid}`, {
    method: 'POST',
    body: JSON.stringify({ enabled }),
  })
}
