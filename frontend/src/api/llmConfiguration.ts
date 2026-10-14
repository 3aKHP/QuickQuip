import { request } from './index'
import type { JsonObject, JsonValue, FieldMetadata } from '../lib/llmConfig'
const ROOT = '/api/llm-configuration'
const post = <T>(path: string, body: unknown) => request<T>(ROOT + path, { method: 'POST', body: JSON.stringify(body) })
export interface ConfigEnvelope { revision: number; document: JsonObject }
export interface ConfigChange { field_path: string; before: JsonValue; after: JsonValue }
/** 修订的版本标记：保存时刻 + 运维备注，界面显示为「YYYY-MM-DD HH:mm (备注)」 */
export interface ConfigVersion { saved_at: number | null; note: string }
export interface ConfigStatus {
  schema_version: number
  draft_revision: number; draft_version: ConfigVersion
  published_revision: number; published_version: ConfigVersion
  bot: { boot_id: string; loaded_revision: number; loaded_version: ConfigVersion; heartbeat_at: number | string; observed_at: number | string; stale: boolean; components: JsonObject; application_version?: string } | null
}
/** created_at 为快照（应用/探测）时刻，saved_at 为该修订保存时刻 */
export interface ConfigSnapshot { revision: number; created_at: number | string; saved_at: number | null; note: string }
export interface ConfigOperation {
  id: string; kind: string; target_revision: number; status: 'queued' | 'running' | 'succeeded' | 'failed' | 'cancelled'; stage: string; created_at: number | string; result: JsonValue; error: JsonValue
}
export interface ConfigValidation { valid: boolean; warnings: JsonValue[]; dependencies: JsonValue[] }
export interface ImportPreview extends ConfigValidation { document: JsonObject; changes: ConfigChange[]; expected_draft_revision: number }
export interface ConfigMetadata { client_fingerprints?: { id: string; label: string; protocols: string[] }[]; fields?: Record<string, FieldMetadata>; settings?: Record<string, Record<string, FieldMetadata>>; protocols?: string[]; route_names?: string[]; parameters?: Record<string, FieldMetadata>; [key: string]: unknown }
export const fetchLlmConfiguration = (source = 'draft') => request<ConfigEnvelope>(`${ROOT}?source=${encodeURIComponent(source)}`)
export const fetchLlmConfigMetadata = () => request<ConfigMetadata>(`${ROOT}/metadata`)
export const fetchLlmConfigStatus = () => request<ConfigStatus>(`${ROOT}/status`)
// note 为 undefined 时 JSON 序列化省略该字段，后端沿用草稿备注
export const saveLlmConfiguration = (document: JsonObject, revision: number, note?: string) => request<ConfigEnvelope>(ROOT, { method: 'PUT', body: JSON.stringify({ document, expected_draft_revision: revision, note }) })
export const saveLlmConfigNote = (source: string, note: string) => request<ConfigStatus>(`${ROOT}/note`, { method: 'PUT', body: JSON.stringify({ source, note }) })
export const validateLlmConfiguration = (document: JsonObject) => post<ConfigValidation>('/validate', { document })
export const previewLlmConfigImport = (document: JsonObject, revision: number) => post<ImportPreview>('/import/preview', { document, expected_draft_revision: revision })
export const importLlmConfiguration = (document: JsonObject, revision: number) => post<ConfigEnvelope>('/import', { document, expected_draft_revision: revision })
export const exportLlmConfiguration = (source: string) => request<JsonObject>(`${ROOT}/export?source=${encodeURIComponent(source)}`)
export const diffLlmConfiguration = () => request<{ changes: ConfigChange[]; components: JsonValue[] }>(`${ROOT}/diff?source=draft&target=published`)
export const applyLlmConfiguration = (revision: number, requestId: string, note?: string) => post<ConfigOperation>('/apply', { expected_draft_revision: revision, request_id: requestId, note })
export const fetchLlmConfigOperation = (id: string) => request<ConfigOperation>(`${ROOT}/operations/${encodeURIComponent(id)}`)
export const cancelLlmConfigOperation = (id: string) => post<ConfigOperation>(`/operations/${encodeURIComponent(id)}/cancel`, {})
export const fetchLlmConfigHistory = () => request<{ snapshots: ConfigSnapshot[] }>(`${ROOT}/history`)
export const restoreLlmConfigSnapshot = (revision: number, expected: number) => post<ConfigEnvelope>(`/history/${revision}/restore`, { expected_draft_revision: expected })
export const fetchLlmEffectiveParameters = (providerId: string, model: string) => request<{ parameters: Record<string, { configured: JsonValue; value: JsonValue; source: string }> }>(`${ROOT}/providers/${encodeURIComponent(providerId)}/effective?model=${encodeURIComponent(model)}`)
export const fetchLlmConfigEnvironment = (source = 'draft') => request<{ variables: { name: string; configured: boolean | null }[]; available: boolean; stale: boolean }>(`${ROOT}/environment?source=${encodeURIComponent(source)}`)
export const probeLlmConfiguration = (source: string, providerId: string, model: string, requestId: string) => post<ConfigOperation & { may_charge: boolean; automatic_retry: boolean }>('/probe', { source, provider_id: providerId, model, request_id: requestId })

export const fetchLlmConfigOperations = () => request<{ operations: ConfigOperation[] }>(`${ROOT}/operations?limit=20`)
