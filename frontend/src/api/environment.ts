import { request } from './index'

export interface Variable {
  name: string
  assigned: boolean
  mode: 'hot' | 'credential' | 'restart'
  states?: Record<string, string>
  references?: string[]
  warning: string
}
export interface Consumer {
  version: string
  boot_id: string
  updated_at: number
  names: string[]
}
export interface EnvironmentList {
  enabled: boolean
  restart_required: boolean
  backend_available: boolean
  reason: string | null
  suggestions?: string[]
  version: string
  variables: Variable[]
  consumers: Record<string, Consumer | null>
}
export interface Edit {
  name: string
  action: 'create' | 'replace' | 'empty' | 'delete'
  value?: string
}
export interface Operation {
  id: string
  phase: string
  version: string
  changes: Variable[]
  states?: Record<string, Record<string, string>>
  consumers: Record<string, Consumer | null>
}
export const loadEnvironment = () => request<EnvironmentList>('/api/environment')
export const previewEnvironment = (expected_version: string, changes: Edit[]) =>
  request<Operation>('/api/environment/preview', {
    method: 'POST', body: JSON.stringify({ expected_version, changes }),
  })
export const saveEnvironment = (expected_version: string, changes: Edit[], password: string, request_id: string) =>
  request<Operation>('/api/environment/changes', {
    method: 'POST', body: JSON.stringify({ expected_version, changes, password, request_id }),
  })
export const getEnvironmentOperation = (id: string) =>
  request<Operation>(`/api/environment/operations/${encodeURIComponent(id)}`)
