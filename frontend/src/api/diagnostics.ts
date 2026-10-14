import { request } from './index'
import type { TraceCallDetail } from './logs'
import type { ConfigOperation, ConfigVersion } from './llmConfiguration'

/** GET /api/diagnostics/providers 列表元素 */
export interface DiagnosticsProvider {
  id: string
  models: string[]
  default_model: string
}

export interface DiagnosticOperation<T> extends Omit<ConfigOperation, 'result'> {
  result: T | null
  may_charge?: boolean
  automatic_retry?: boolean
}

export interface ProbeRequestBody {
  source: number
  provider_id: string
  model: string
  request_id: string
}

export interface ProbeOperationResult {
  probe: ProviderProbeResult
  revision: number
}

/** 对应 ProviderHealth.as_dict()；status ∈ ok / error / skipped（skipped 不产生计费） */
export interface ProviderProbeResult {
  provider_id: string
  model: string
  status: string
  latency_ms: number | null
  error: string
}

/** GET /api/diagnostics/trace-status */
export interface TraceStatus {
  active: boolean
  flag_file: string
  entry_count: number
  latest_event_id: number | null
  storage_bytes: number
}

/**
 * POST /api/diagnostics/sample-request body。
 * 目标与 request_id 固定到一次提交；配置来源为选定的已发布快照。
 */
export interface SampleRequestBody extends ProbeRequestBody {
  system_prompt?: string
  user_prompt?: string
  stream?: boolean
  max_output_tokens?: number
}

/** POST /api/diagnostics/sample-request 响应：解析后的 LLMResponse + 该次调用的完整 trace */
export interface SampleRequestResult {
  text: string
  model: string
  finish_reason: string | null
  input_tokens: number | null
  output_tokens: number | null
  thinking_blocks: Array<Record<string, unknown>>
  duration_ms: number
  trace_calls: TraceCallDetail[]
}

/** POST /api/diagnostics/regression 的单条样本输入；label 后端默认空串 */
export interface RegressionSampleInput {
  text: string
  label?: string
}

export interface RegressionRuleMatch {
  name: string
  patterns: string[]
  priority: number
}

export interface RegressionResult {
  label: string
  text: string
  matched: boolean
  rules: RegressionRuleMatch[]
}

export async function fetchProviders(): Promise<{ revision: number; version: ConfigVersion; providers: DiagnosticsProvider[] }> {
  return request('/api/diagnostics/providers', { signal: AbortSignal.timeout(10_000) })
}

export async function probeProviders(body: ProbeRequestBody): Promise<DiagnosticOperation<ProbeOperationResult>> {
  return request('/api/diagnostics/providers/probe', {
    method: 'POST', body: JSON.stringify(body), signal: AbortSignal.timeout(10_000),
  })
}

export async function fetchDiagnosticOperation<T>(id: string): Promise<DiagnosticOperation<T>> {
  return request(`/api/llm-configuration/operations/${encodeURIComponent(id)}`, {
    signal: AbortSignal.timeout(10_000),
  })
}

export async function fetchTraceStatus(): Promise<TraceStatus> {
  return request('/api/diagnostics/trace-status')
}

export async function setTraceStatus(enabled: boolean): Promise<{ active: boolean }> {
  return request('/api/diagnostics/trace-status', {
    method: 'POST',
    body: JSON.stringify({ enabled }),
  })
}

export async function clearTraces(): Promise<{ cleared: number }> {
  return request('/api/diagnostics/trace/clear', { method: 'POST' })
}

export async function runSampleRequest(body: SampleRequestBody): Promise<DiagnosticOperation<SampleRequestResult>> {
  return request('/api/diagnostics/sample-request', {
    method: 'POST',
    body: JSON.stringify(body),
    signal: AbortSignal.timeout(10_000),
  })
}

export async function runRegression(
  samples: RegressionSampleInput[],
): Promise<{ samples: RegressionResult[] }> {
  return request('/api/diagnostics/regression', {
    method: 'POST',
    body: JSON.stringify({ samples }),
  })
}
