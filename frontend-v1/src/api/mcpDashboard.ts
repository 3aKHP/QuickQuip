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
  tools: McpTool[]
  runtime_available?: boolean
}

export interface McpDashboardResponse {
  servers: McpServer[]
}

export async function fetchMcpDashboard(): Promise<McpDashboardResponse> {
  return request('/api/mcp-dashboard')
}
