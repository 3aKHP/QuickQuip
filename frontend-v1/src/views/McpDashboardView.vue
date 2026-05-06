<template>
  <div class="mcp-view">
    <UiPageHeader title="MCP 服务器" subtitle="MCP 服务器连接状态与工具清单" />

    <UiLoading v-if="loading" />

    <div v-else-if="error" class="error-block">
      <p>{{ error }}</p>
      <UiButton icon="RefreshCw" size="sm" @click="load">重试</UiButton>
    </div>

    <UiEmpty
      v-else-if="!servers.length"
      icon="Bot"
      title="暂无 MCP 服务器"
      description="在 config/llm.toml 中配置 [mcp.servers] 后即可在此查看状态"
    />

    <div v-else class="server-grid">
      <UiCard v-for="server in servers" :key="server.id" class="server-card">
        <div class="card-header">
          <div class="card-title-row">
            <span class="card-title">{{ server.id }}</span>
            <span v-if="server.detail" class="card-detail">{{ server.detail }}</span>
          </div>
          <div class="status-row">
            <span
              class="status-dot"
              :class="{
                'status-connected': server.connected,
                'status-error': !server.connected && server.enabled && server.runtime_available !== false,
                'status-disabled': !server.enabled,
                'status-unknown': !server.connected && server.enabled && server.runtime_available === false,
              }"
            />
            <span class="status-text">
              {{ server.connected ? '已连接' : (server.runtime_available === false ? '状态未知' : (server.enabled ? '连接失败' : '已禁用')) }}
            </span>
          </div>
        </div>

        <div class="card-meta">
          <UiTag size="sm" variant="info">{{ server.transport }}</UiTag>
          <span class="tool-count">{{ server.tool_count }} 个工具</span>
        </div>

        <div v-if="server.error" class="server-error">{{ server.error }}</div>

        <div v-if="server.tools.length" class="tools-section">
          <button class="tools-toggle" @click="toggleTools(server.id)">
            <UiIcon
              :name="expandedServers.has(server.id) ? 'ArrowUp' : 'ArrowDown'"
              :size="14"
            />
            <span>工具列表 ({{ server.tools.length }})</span>
          </button>
          <div v-show="expandedServers.has(server.id)" class="tools-list">
            <div v-for="tool in server.tools" :key="tool.name" class="tool-item">
              <span class="tool-name">{{ tool.name }}</span>
              <span class="tool-desc">{{ tool.description }}</span>
            </div>
          </div>
        </div>
      </UiCard>
    </div>
  </div>
</template>

<script setup lang="ts">
import { onMounted, ref } from 'vue'
import UiPageHeader from '../components/ui/UiPageHeader.vue'
import UiCard from '../components/ui/UiCard.vue'
import UiLoading from '../components/ui/UiLoading.vue'
import UiEmpty from '../components/ui/UiEmpty.vue'
import UiTag from '../components/ui/UiTag.vue'
import UiButton from '../components/ui/UiButton.vue'
import UiIcon from '../components/ui/UiIcon.vue'
import { fetchMcpDashboard, type McpServer } from '../api/mcpDashboard'

const servers = ref<McpServer[]>([])
const loading = ref(true)
const error = ref<string | null>(null)
const expandedServers = ref(new Set<string>())

function toggleTools(serverId: string) {
  const next = new Set(expandedServers.value)
  if (next.has(serverId)) {
    next.delete(serverId)
  } else {
    next.add(serverId)
  }
  expandedServers.value = next
}

async function load() {
  loading.value = true
  error.value = null
  try {
    const data = await fetchMcpDashboard()
    servers.value = data.servers || []
  } catch (e: unknown) {
    error.value = (e as Error).message || '加载失败'
  } finally {
    loading.value = false
  }
}

onMounted(() => {
  load()
})
</script>

<style scoped>
.mcp-view {
  display: flex;
  flex-direction: column;
  gap: var(--qq-gap-lg);
  flex: 1;
  min-height: 0;
  overflow-y: auto;
}

.error-block {
  display: flex;
  align-items: center;
  gap: var(--qq-gap-sm);
  color: var(--qq-danger);
  font-size: 13px;
  padding: var(--qq-gap-sm);
  background: var(--qq-surface);
  border-radius: var(--qq-radius-sm);
  border: 1px solid var(--qq-danger);
}

.server-grid {
  display: grid;
  grid-template-columns: repeat(auto-fill, minmax(340px, 1fr));
  gap: var(--qq-gap-md);
}

.server-card {
  display: flex;
  flex-direction: column;
  gap: var(--qq-gap-sm);
}

.card-header {
  display: flex;
  align-items: flex-start;
  justify-content: space-between;
  gap: var(--qq-gap-sm);
}

.card-title-row {
  display: flex;
  flex-direction: column;
  gap: 2px;
}

.card-title {
  font-size: 15px;
  font-weight: 600;
  color: var(--qq-text);
  font-family: var(--qq-font-mono);
  white-space: pre-wrap;
}

.card-detail {
  font-size: 11px;
  color: var(--qq-text-muted);
  font-family: var(--qq-font-mono);
}

.status-row {
  display: flex;
  align-items: center;
  gap: 6px;
  white-space: nowrap;
}

.status-dot {
  width: 8px;
  height: 8px;
  border-radius: 50%;
  flex-shrink: 0;
}

.status-connected {
  background: var(--qq-success);
}

.status-error {
  background: var(--qq-danger);
}

.status-disabled {
  background: var(--qq-text-muted);
}

.status-unknown {
  background: var(--qq-warn);
}

.status-text {
  font-size: 12px;
  color: var(--qq-text-muted);
}

.card-meta {
  display: flex;
  align-items: center;
  gap: var(--qq-gap-sm);
}

.tool-count {
  font-size: 12px;
  color: var(--qq-text-muted);
}

.server-error {
  font-size: 12px;
  color: var(--qq-danger);
  padding: var(--qq-gap-xs) var(--qq-gap-sm);
  background: var(--qq-danger-soft);
  border-radius: var(--qq-radius-sm);
  white-space: pre-wrap;
}

.tools-section {
  display: flex;
  flex-direction: column;
  gap: var(--qq-gap-xs);
}

.tools-toggle {
  display: inline-flex;
  align-items: center;
  gap: 4px;
  padding: 4px 8px;
  border: 1px solid var(--qq-border);
  border-radius: var(--qq-radius-sm);
  background: var(--qq-surface);
  color: var(--qq-text-muted);
  font-size: 12px;
  cursor: pointer;
  transition: border-color var(--qq-transition-fast), color var(--qq-transition-fast);
  align-self: flex-start;
}

.tools-toggle:hover {
  border-color: var(--qq-border-strong);
  color: var(--qq-text);
}

.tools-list {
  display: flex;
  flex-direction: column;
  gap: var(--qq-gap-xs);
  padding-left: var(--qq-gap-sm);
  border-left: 2px solid var(--qq-border);
}

.tool-item {
  display: flex;
  flex-direction: column;
  gap: 2px;
}

.tool-name {
  font-size: 12px;
  font-weight: 600;
  color: var(--qq-text);
  font-family: var(--qq-font-mono);
}

.tool-desc {
  font-size: 11px;
  color: var(--qq-text-muted);
}
</style>
