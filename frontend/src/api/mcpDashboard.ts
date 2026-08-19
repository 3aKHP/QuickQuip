import { request } from './index'

export interface McpTool {
  name: string
  description: string
}

export interface McpServer {
  id: string
  transport: string
  enabled: boolean
  connected: boolean
  tool_count: number
  error: string | null
  detail: string
  server_identity?: string
  negotiation?: string
  era?: string
  /** 服务端 format_mcp_era_tag 下发的唯一 era 标签；config-only 为空字符串 */
  era_tag?: string
  failure_kind?: string
  negotiated_protocol_version?: string
  tools: McpTool[]
  runtime_available?: boolean
}

export interface McpDashboardResponse {
  servers: McpServer[]
}

export async function fetchMcpDashboard(): Promise<McpDashboardResponse> {
  return request('/api/mcp-dashboard')
}
