import { request } from './index'

/** 后端 _diagnostics_payload 统一产出的诊断项 */
export interface SkillDiagnostic {
  kind: string
  message: string
}

/** GET /skills 列表项：含扫描静默跳过的坏项（ok=false 时 diagnostics 携带诊断） */
export interface SkillSummary {
  name: string
  ok: boolean
  description: string
  diagnostics: SkillDiagnostic[]
  resource_count: number
  has_scripts: boolean
  total_bytes: number
  mtime: number
  /** 预置态：current / diverged / null（非预置） */
  preset_state: 'current' | 'diverged' | null
}

/** GET /skills/{name} 的资源条目 */
export interface SkillResource {
  path: string
  kind: string
  size_bytes: number
  sha256?: string
}

/** 后端 dataclasses.asdict(SkillMetadata) 的原始结构 */
export interface SkillMetadataPayload {
  name: string
  description: string
  /** 可为空字符串 */
  license: string
  /** 可为空字符串 */
  compatibility: string
  metadata: Record<string, string>
  unknown_fields: string[]
}

export interface SkillDetail {
  name: string
  metadata: SkillMetadataPayload
  body: string
  resources: SkillResource[]
  diagnostics: SkillDiagnostic[]
}

export interface SkillFileContent {
  path: string
  content: string
  size_bytes: number
}

export type PresetSyncState = 'current' | 'diverged' | 'missing' | 'conflict'

/** GET /skills/presets 的预置行；label 为后端给好的中文文案，直接展示 */
export interface PresetRow {
  name: string
  state: PresetSyncState
  label: string
}

export interface PresetsResponse {
  presets: PresetRow[]
  local_only: string[]
}

export interface PresetApplyOutcome {
  name: string
  backup: string | null
}

export interface PresetApplyResponse {
  outcomes: PresetApplyOutcome[]
  failures: string[]
}

/** inspect 返回的安装候选（zip/文件夹/GitHub 三来源同构） */
export interface ImportCandidate {
  /** 候选根在归档内的相对路径，"" 表示根 */
  root: string
  ok: boolean
  name: string
  description: string
  has_scripts: boolean
  script_files: string[]
  file_count: number
  total_bytes: number
  diagnostics: SkillDiagnostic[]
  /** 与现有同名 skill 冲突 */
  conflict: boolean
}

export interface ImportInspectResponse {
  token: string
  candidates: ImportCandidate[]
}

export interface ImportZipInspectPayload {
  kind: 'zip'
  archive_b64: string
}

export interface ImportFolderInspectPayload {
  kind: 'folder'
  files: Record<string, string>
}

export interface ImportConfirmResponse {
  name: string
  backup: string | null
}

export async function listSkills() {
  return request<{ skills: SkillSummary[] }>('/api/skills')
}

export async function createSkill(name: string, content: string) {
  return request('/api/skills', {
    method: 'POST',
    body: JSON.stringify({ name, content }),
  })
}

export async function fetchSkill(name: string) {
  return request<SkillDetail>(`/api/skills/${encodeURIComponent(name)}`)
}

export async function deleteSkill(name: string) {
  return request(`/api/skills/${encodeURIComponent(name)}`, {
    method: 'DELETE',
  })
}

export async function fetchSkillFile(name: string, path: string) {
  return request<SkillFileContent>(
    `/api/skills/${encodeURIComponent(name)}/file?path=${encodeURIComponent(path)}`,
  )
}

export async function saveSkillFile(name: string, path: string, content: string) {
  return request(`/api/skills/${encodeURIComponent(name)}/file`, {
    method: 'PUT',
    body: JSON.stringify({ path, content }),
  })
}

export async function deleteSkillFile(name: string, path: string) {
  return request(
    `/api/skills/${encodeURIComponent(name)}/file?path=${encodeURIComponent(path)}`,
    { method: 'DELETE' },
  )
}

export async function listSkillPresets() {
  return request<PresetsResponse>('/api/skills/presets')
}

/** names 省略或为空数组 = 同步全部 missing+diverged */
export async function applySkillPresets(names?: string[]) {
  return request<PresetApplyResponse>('/api/skills/presets/apply', {
    method: 'POST',
    body: JSON.stringify(names && names.length ? { names } : {}),
  })
}

export async function inspectSkillImport(payload: ImportZipInspectPayload | ImportFolderInspectPayload) {
  return request<ImportInspectResponse>('/api/skills/import/inspect', {
    method: 'POST',
    body: JSON.stringify(payload),
  })
}

export async function inspectGithubImport(url: string) {
  return request<ImportInspectResponse>('/api/skills/import/github/inspect', {
    method: 'POST',
    body: JSON.stringify({ url }),
  })
}

export async function confirmSkillImport(token: string, root: string, overwrite?: boolean) {
  return request<ImportConfirmResponse>('/api/skills/import/confirm', {
    method: 'POST',
    body: JSON.stringify({ token, root, overwrite: overwrite === true }),
  })
}
