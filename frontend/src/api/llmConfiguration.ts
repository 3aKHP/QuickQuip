import { request } from './index'
import type { JsonObject, JsonValue, FieldMetadata } from '../lib/llmConfig'
const ROOT = '/api/llm-configuration'
const post = <T>(path: string, body: unknown) => request<T>(ROOT + path, { method: 'POST', body: JSON.stringify(body) })
export interface ConfigEnvelope { revision: number; document: JsonObject }
export interface ConfigChange { field_path: string; before: JsonValue; after: JsonValue }
export interface ConfigStatus {
  schema_version: number; draft_revision: number; published_revision: number
  bot: { boot_id: string; loaded_revision: number; heartbeat_at: number | string; observed_at: number | string; stale: boolean; components: JsonObject; application_version?: string } | null
}
export interface ConfigOperation {
  id: string; kind: string; target_revision: number; status: 'queued' | 'running' | 'succeeded' | 'failed' | 'cancelled'; stage: string; created_at: number | string; result: JsonValue; error: JsonValue
}
export interface ConfigValidation { valid: boolean; warnings: JsonValue[]; dependencies: JsonValue[] }
export interface ImportPreview extends ConfigValidation { document: JsonObject; changes: ConfigChange[]; expected_draft_revision: number }
export interface ConfigMetadata { fields?: Record<string, FieldMetadata>; settings?: Record<string, Record<string, FieldMetadata>>; protocols?: string[]; route_names?: string[]; parameters?: Record<string, FieldMetadata>; [key: string]: unknown }
export const fetchLlmConfiguration = (source = 'draft') => request<ConfigEnvelope>(`${ROOT}?source=${encodeURIComponent(source)}`)
export const fetchLlmConfigMetadata = () => request<ConfigMetadata>(`${ROOT}/metadata`)
export const fetchLlmConfigStatus = () => request<ConfigStatus>(`${ROOT}/status`)
export const saveLlmConfiguration = (document: JsonObject, revision: number) => request<ConfigEnvelope>(ROOT, { method: 'PUT', body: JSON.stringify({ document, expected_draft_revision: revision }) })
export const validateLlmConfiguration = (document: JsonObject) => post<ConfigValidation>('/validate', { document })
export const previewLlmConfigImport = (document: JsonObject, revision: number) => post<ImportPreview>('/import/preview', { document, expected_draft_revision: revision })
export const importLlmConfiguration = (document: JsonObject, revision: number) => post<ConfigEnvelope>('/import', { document, expected_draft_revision: revision })
export const exportLlmConfiguration = (source: string) => request<JsonObject>(`${ROOT}/export?source=${encodeURIComponent(source)}`)
export const diffLlmConfiguration = () => request<{ changes: ConfigChange[]; components: JsonValue[] }>(`${ROOT}/diff?source=draft&target=published`)
export const applyLlmConfiguration = (revision: number, requestId: string) => post<ConfigOperation>('/apply', { expected_draft_revision: revision, request_id: requestId })
export const fetchLlmConfigOperation = (id: string) => request<ConfigOperation>(`${ROOT}/operations/${encodeURIComponent(id)}`)
export const cancelLlmConfigOperation = (id: string) => post<ConfigOperation>(`/operations/${encodeURIComponent(id)}/cancel`, {})
export const fetchLlmConfigHistory = () => request<{ snapshots: { revision: number; created_at: string | number }[] }>(`${ROOT}/history`)
export const restoreLlmConfigSnapshot = (revision: number, expected: number) => post<ConfigEnvelope>(`/history/${revision}/restore`, { expected_draft_revision: expected })
export const fetchLlmEffectiveParameters = (providerId: string, model: string) => request<{ parameters: Record<string, { configured: JsonValue; value: JsonValue; source: string }> }>(`${ROOT}/providers/${encodeURIComponent(providerId)}/effective?model=${encodeURIComponent(model)}`)
export const fetchLlmConfigEnvironment = (source = 'draft') => request<{ variables: { name: string; configured: boolean | null }[]; available: boolean; stale: boolean }>(`${ROOT}/environment?source=${encodeURIComponent(source)}`)
export const probeLlmConfiguration = (source: string, providerId: string, model: string, requestId: string) => post<ConfigOperation & { may_charge: boolean; automatic_retry: boolean }>('/probe', { source, provider_id: providerId, model, request_id: requestId })

export const fetchLlmConfigOperations = () => request<{ operations: ConfigOperation[] }>(`${ROOT}/operations?limit=20`)
