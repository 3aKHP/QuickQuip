import { request } from './index'

export async function fetchProviders() {
  return request('/api/diagnostics/providers')
}

export async function probeProviders() {
  return request('/api/diagnostics/providers/probe', { method: 'POST' })
}

export async function fetchTraceStatus() {
  return request('/api/diagnostics/trace-status')
}

export async function setTraceStatus(enabled: boolean) {
  return request('/api/diagnostics/trace-status', {
    method: 'POST',
    body: JSON.stringify({ enabled }),
  })
}

export async function fetchRecentTraces(n: number = 20) {
  return request(`/api/diagnostics/trace/recent?n=${n}`)
}

export async function clearTraces() {
  return request('/api/diagnostics/trace/clear', { method: 'POST' })
}

export async function runSampleRequest(body: string) {
  return request('/api/diagnostics/sample-request', {
    method: 'POST',
    body,
  })
}

export async function runRegression(body: string) {
  return request('/api/diagnostics/regression', {
    method: 'POST',
    body,
  })
}
