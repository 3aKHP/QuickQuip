import { request } from './index'

export interface Variable {
  name: string
  assigned: boolean
  mode: 'hot' | 'credential' | 'restart' | 'unknown'
  states?: Record<string, string>
  references?: string[]
  warning: string
}
export interface Relation {
  component: string
  object_id: string | null
  field_path: string
  config_scope: 'draft' | 'published' | 'file' | 'code' | 'template'
  enabled: boolean | null
  required: boolean | null
  name_kind: 'fixed' | 'configured_name' | 'interpolation' | 'computed_name'
  source_name: string
  raw_expression: string
  target_service: string
  target_kind: string
  target_name: string | null
  resolution: string
  delivery: string
  required_action: string
  observation: string
  default_present?: boolean
}
export interface DirectorySource {
  kind: string
  context: string
  path: string
  raw_expression: string | null
  resolution_context: string
  evidence_scope: string
  observation: string
  override_kind?: string
  target_name?: string
}
export interface Definition {
  present: boolean
  value_state: 'bare' | 'empty' | 'nonempty' | 'missing'
  managed_literal: boolean
  deletion_marker: boolean
  conflict?: boolean
}
export interface DirectoryEntry {
  name: string
  assigned: boolean
  mode: Variable['mode']
  references: string[]
  warning: string
  states: Record<string, string>
  groups: string[]
  relations: Relation[]
  sources: DirectorySource[]
  evidence_flags: Record<string, boolean>
  definition?: Definition
  allowed_actions?: Edit['action'][]
  description?: string
  value_type?: string
  alias_of?: string
  suggest?: boolean
  default_present?: boolean
  default_origin?: string
}
export interface TaxonomyGroup { id: string, label: string }
export interface TaxonomyDomain { id: string, label: string, groups: TaxonomyGroup[] }
export interface DirectoryError { component: string, code: string }
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
  taxonomy?: TaxonomyDomain[]
  directory?: DirectoryEntry[]
  directory_errors?: DirectoryError[]
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
export const loadEnvironment = (includeDirectory = false) =>
  request<EnvironmentList>(`/api/environment${includeDirectory ? '?include_directory=true' : ''}`)
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
