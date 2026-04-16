import { request } from './index.js'

export async function fetchLlmConfig() {
  return request('/api/config/llm')
}

export async function saveLlmConfig(content) {
  return request('/api/config/llm', {
    method: 'PUT',
    body: JSON.stringify({ content }),
  })
}
