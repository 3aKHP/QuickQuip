import { request } from './index'

/** GET /api/llm-effort 的 provider 投影：reasoning_effort 空串 = 模型默认档（不发送思考参数） */
export interface LlmEffortProvider {
  id: string
  default_model: string
  reasoning_effort: string
}

export async function fetchLlmEffort() {
  return request<{ providers: LlmEffortProvider[] }>('/api/llm-effort')
}

/** effort 传空串即删除该 provider 的档位行（回模型默认档） */
export async function saveLlmEffort(providerId: string, effort: string) {
  return request<{ ok: boolean; effect?: string }>(
    `/api/llm-effort/${encodeURIComponent(providerId)}`,
    {
      method: 'PUT',
      body: JSON.stringify({ effort }),
    },
  )
}
