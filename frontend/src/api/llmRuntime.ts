import { request } from './index'

/** enqueue() 的即时返回：仅含排队占位信息，无 payload/result */
export interface QueuedActionRef {
  id: string
  action_type: string
  status: string
}

/**
 * 运行时操作响应。当前后端（routes/llm_runtime.py）所有写端点一律入队，
 * 返回 { ok, queued, action }。
 *
 * DiagnosticsView 保留了对旧直返形状（text / status / summary / load_error /
 * error / deleted）的防御读取；为零行为变化，这些字段在此列为可选，
 * 待 F5 重组视图时按真实契约收敛。
 */
export interface RuntimeActionResponse {
  ok: boolean
  queued: boolean
  action: QueuedActionRef
  text?: string
  status?: string
  summary?: unknown
  load_error?: string | null
  error?: string
  deleted?: number
}

/** 动作的 result_json：健康检查等动作写 { text }，其余键按动作类型而异 */
export interface RuntimeActionResult {
  text?: string
  [key: string]: unknown
}

/** GET /api/llm-runtime/actions 列表元素（WebAdminAction 的 asdict 投影） */
export interface RuntimeAction {
  id: string
  action_type: string
  payload: Record<string, unknown>
  status: string
  created_at: string
  updated_at: string
  result: RuntimeActionResult | null
  error: string
}

export async function fetchLlmHealth(
  verbose = false,
  scopeKey = '__web_admin__',
): Promise<RuntimeActionResponse> {
  return request('/api/llm-runtime/health', {
    method: 'POST',
    body: JSON.stringify({ verbose, scope_key: scopeKey }),
  })
}

export async function reloadLlmRuntime(): Promise<RuntimeActionResponse> {
  return request('/api/llm-runtime/reload', { method: 'POST' })
}

export async function reloadMcpRuntime(): Promise<RuntimeActionResponse> {
  return request('/api/llm-runtime/mcp/reload', { method: 'POST' })
}

export async function reloadPersonas(): Promise<RuntimeActionResponse> {
  return request('/api/llm-runtime/personas/reload', { method: 'POST' })
}

export async function reloadRules(): Promise<RuntimeActionResponse> {
  return request('/api/llm-runtime/rules/reload', { method: 'POST' })
}

export async function clearLlmContext(scopeKey: string): Promise<RuntimeActionResponse> {
  return request('/api/llm-runtime/context/clear', {
    method: 'POST',
    body: JSON.stringify({ scope_key: scopeKey }),
  })
}

export async function deleteLlmContextMessage(
  scopeKey: string,
  messageId: string,
): Promise<RuntimeActionResponse> {
  return request('/api/llm-runtime/context/delete-message', {
    method: 'POST',
    body: JSON.stringify({ scope_key: scopeKey, message_id: messageId }),
  })
}

export async function fetchLlmRuntimeActions(
  limit = 20,
): Promise<{ actions: RuntimeAction[] }> {
  return request(`/api/llm-runtime/actions?limit=${encodeURIComponent(String(limit))}`)
}
