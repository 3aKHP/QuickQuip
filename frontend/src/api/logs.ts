import { request } from './index'

export async function fetchLogIndex() {
  return request('/api/logs')
}

export async function fetchLogTail(name: string, lines: number = 200) {
  return request(`/api/logs/files/${encodeURIComponent(name)}/tail?lines=${lines}`)
}

export function buildLogDownloadUrl(name: string) {
  return `/ops/api/logs/files/${encodeURIComponent(name)}/download`
}

export function buildLogStreamUrl(tail: number = 200) {
  return `/ops/api/logs/stream?tail=${tail}`
}

export function buildTraceStreamUrl(tail: number = 50) {
  return `/ops/api/logs/trace/stream?tail=${tail}`
}
