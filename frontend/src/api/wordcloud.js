import { request } from './index.js'

export async function listWordcloudGroups() {
  return request('/api/wordcloud/groups')
}

export async function renderWordcloud(group, window = 'today', topK = 50) {
  const params = new URLSearchParams({ group, window, top_k: topK })
  return request(`/api/wordcloud/render?${params.toString()}`)
}
