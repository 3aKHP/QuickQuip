import { request } from './index'

export async function fetchLlmHealth(verbose = false, scopeKey = '__web_admin__') {
  return request('/api/llm-runtime/health', {
    method: 'POST',
    body: JSON.stringify({ verbose, scope_key: scopeKey }),
  })
}

export async function reloadLlmRuntime() {
  return request('/api/llm-runtime/reload', { method: 'POST' })
}

export async function reloadMcpRuntime() {
  return request('/api/llm-runtime/mcp/reload', { method: 'POST' })
}

export async function reloadPersonas() {
  return request('/api/llm-runtime/personas/reload', { method: 'POST' })
}

export async function reloadRules() {
  return request('/api/llm-runtime/rules/reload', { method: 'POST' })
}

export async function clearLlmContext(scopeKey: string) {
  return request('/api/llm-runtime/context/clear', {
    method: 'POST',
    body: JSON.stringify({ scope_key: scopeKey }),
  })
}

export async function deleteLlmContextMessage(scopeKey: string, messageId: string) {
  return request('/api/llm-runtime/context/delete-message', {
    method: 'POST',
    body: JSON.stringify({ scope_key: scopeKey, message_id: messageId }),
  })
}

export async function fetchLlmRuntimeActions(limit = 20) {
  return request(`/api/llm-runtime/actions?limit=${encodeURIComponent(String(limit))}`)
}
