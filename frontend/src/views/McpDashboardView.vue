<template>
  <div>
    <UiPageHeader title="MCP 服务器" subtitle="MCP 服务器连接状态与工具清单" />
    <UiLoading v-if="loading" />
    <div v-else-if="error" class="err-block"><p>{{ error }}</p><UiButton icon="RefreshCw" size="sm" @click="load">重试</UiButton></div>
    <UiEmpty v-else-if="!servers.length" icon="Bot" title="暂无 MCP 服务器" description="在 config/llm.toml 中配置 [mcp.servers] 后即可在此查看状态" />
    <div v-else class="server-grid">
      <UiCard v-for="s in servers" :key="s.id" padding="md" shadow="sm">
        <div class="s-head"><div class="s-title"><span class="s-name">{{ s.id }}</span><span v-if="s.detail" class="s-detail">{{ s.detail }}</span></div><div class="s-status"><span class="dot" :class="dotClass(s)" /><span class="muted">{{ statusText(s) }}</span></div></div>
        <div class="s-meta"><UiTag size="sm" variant="info">{{ s.transport }}</UiTag><UiTag v-if="eraTag(s)" size="sm" variant="info">{{ eraTag(s) }}</UiTag><span v-if="s.negotiated_protocol_version" class="muted">v{{ s.negotiated_protocol_version }}</span><span class="muted">{{ s.tool_count }} 个工具</span></div>
        <div v-if="s.error" class="s-error">{{ s.error }}</div>
        <div v-if="s.tools.length" class="s-tools">
          <button class="tools-toggle" @click="toggle(s.id)"><UiIcon :name="expanded.has(s.id) ? 'ChevronDown' : 'ChevronRight'" :size="14" /><span>工具列表 ({{ s.tools.length }})</span></button>
          <div v-show="expanded.has(s.id)" class="tools-list"><div v-for="t in s.tools" :key="t.name" class="tool"><span class="tool-name">{{ t.name }}</span><span class="muted tool-desc">{{ t.description }}</span></div></div>
        </div>
      </UiCard>
    </div>
  </div>
</template>

<script setup lang="ts">
import { onMounted, ref } from 'vue'
import UiPageHeader from '../components/ui/UiPageHeader.vue'; import UiCard from '../components/ui/UiCard.vue'; import UiLoading from '../components/ui/UiLoading.vue'; import UiEmpty from '../components/ui/UiEmpty.vue'; import UiTag from '../components/ui/UiTag.vue'; import UiButton from '../components/ui/UiButton.vue'; import UiIcon from '../components/ui/UiIcon.vue'
import { fetchMcpDashboard, type McpServer } from '../api/mcpDashboard'

const servers = ref<McpServer[]>([]); const loading = ref(true); const error = ref<string | null>(null); const expanded = ref(new Set<string>())
function statusText(s: McpServer): string { if (s.connected) return '已连接'; if (s.runtime_available === false) return '状态未知'; if (!s.enabled) return '已禁用'; return '连接失败' }
function dotClass(s: McpServer): string { if (s.connected) return 'dot-ok'; if (!s.enabled) return 'dot-off'; if (s.runtime_available === false) return 'dot-unk'; return 'dot-err' }
function toggle(id: string) { const n = new Set(expanded.value); n.has(id) ? n.delete(id) : n.add(id); expanded.value = n }
// Era tag de-duplication; keep semantics in sync with format_mcp_status
// (src/quickquip/llm/service_parts/health.py).
function eraTag(s: McpServer): string { const neg = s.negotiation || 'legacy'; const era = s.era || 'unknown'; if (neg === era) return neg === 'legacy' ? '' : neg; if (neg === 'legacy' && era === 'unknown') return ''; return `${neg}/${era}` }
async function load() { loading.value = true; error.value = null; try { servers.value = ((await fetchMcpDashboard()).servers || []) as any } catch (e: unknown) { error.value = (e as Error).message || '加载失败' } finally { loading.value = false } }
onMounted(() => load())
</script>

<style scoped>
.err-block { display: flex; align-items: center; gap: var(--qq-gap-sm); color: var(--qq-danger); font-size: var(--qq-text-sm); }
.server-grid { display: grid; grid-template-columns: repeat(auto-fill, minmax(280px, 1fr)); gap: var(--qq-gap-md); }
.s-head { display: flex; align-items: flex-start; justify-content: space-between; gap: var(--qq-gap-sm); }
.s-title { display: flex; flex-direction: column; gap: 2px; }
.s-name { font-size: 15px; font-weight: 600; color: var(--qq-text); font-family: var(--qq-font-mono); }
.s-detail { font-size: 11px; color: var(--qq-text-muted); font-family: var(--qq-font-mono); }
.s-status { display: flex; align-items: center; gap: 6px; white-space: nowrap; }
.dot { width: 8px; height: 8px; border-radius: 50%; }
.dot-ok { background: var(--qq-success); } .dot-err { background: var(--qq-danger); } .dot-off { background: var(--qq-text-muted); } .dot-unk { background: var(--qq-warn); }
.s-meta { display: flex; align-items: center; gap: var(--qq-gap-sm); margin-top: var(--qq-gap-sm); }
.muted { color: var(--qq-text-muted); font-size: 12px; }
.s-error { font-size: 12px; color: var(--qq-danger); padding: var(--qq-gap-xs) var(--qq-gap-sm); background: var(--qq-danger-soft); border-radius: var(--qq-radius-sm); margin-top: var(--qq-gap-xs); }
.s-tools { margin-top: var(--qq-gap-sm); }
.tools-toggle { display: inline-flex; align-items: center; gap: 4px; padding: 4px 8px; border: none; border-radius: var(--qq-radius-sm); background: var(--qq-surface-strong); color: var(--qq-text-muted); font-size: 12px; font-family: var(--qq-font-base); cursor: pointer; transition: all var(--qq-transition-fast); }
.tools-toggle:hover { color: var(--qq-text); }
.tools-list { margin-top: var(--qq-gap-xs); padding-left: var(--qq-gap-sm); border-left: 2px solid var(--qq-border); display: flex; flex-direction: column; gap: var(--qq-gap-xs); }
.tool { display: flex; flex-direction: column; gap: 2px; }
.tool-name { font-size: 12px; font-weight: 600; color: var(--qq-text); font-family: var(--qq-font-mono); }
.tool-desc { font-size: 11px; }
</style>
