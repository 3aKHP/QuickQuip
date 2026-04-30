import { request } from './index'

export async function listLlmAbout() {
  return request('/api/llm-about')
}

export async function fetchLlmAboutFile(scope: string, kind: string) {
  return request(`/api/llm-about/${encodeURIComponent(scope)}/${encodeURIComponent(kind)}`)
}

export async function saveLlmAboutFile(scope: string, kind: string, content: string) {
  return request(`/api/llm-about/${encodeURIComponent(scope)}/${encodeURIComponent(kind)}`, {
    method: 'PUT',
    body: JSON.stringify({ content }),
  })
}

export async function createLlmAboutGroup(groupId: string, copyExample = true) {
  return request('/api/llm-about/groups', {
    method: 'POST',
    body: JSON.stringify({ group_id: groupId, copy_example: copyExample }),
  })
}
