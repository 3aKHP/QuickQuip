import { request } from './index.js'

export async function fetchProviders() {
  return request('/api/diagnostics/providers')
}

export async function fetchTraceStatus() {
  return request('/api/diagnostics/trace-status')
}

export async function setTraceStatus(enabled) {
  return request('/api/diagnostics/trace-status', {
    method: 'POST',
    body: { enabled },
  })
}

export async function fetchRecentTraces(n = 20) {
  return request(`/api/diagnostics/trace/recent?n=${n}`)
}

export async function clearTraces() {
  return request('/api/diagnostics/trace/clear', { method: 'POST' })
}

export async function runSampleRequest(body) {
  return request('/api/diagnostics/sample-request', {
    method: 'POST',
    body,
  })
}

export async function runRegression(body) {
  return request('/api/diagnostics/regression', {
    method: 'POST',
    body,
  })
}
