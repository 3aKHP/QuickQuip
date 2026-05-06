import { request } from './index'

export async function listWordcloudGroups() {
  return request('/api/wordcloud/groups')
}

export async function renderWordcloud(group: string, window: string = 'today', topK: number = 50) {
  const params = new URLSearchParams({ group, window, top_k: String(topK) })
  return request(`/api/wordcloud/render?${params.toString()}`)
}
