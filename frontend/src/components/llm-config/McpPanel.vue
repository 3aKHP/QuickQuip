<template>
  <div class="mcp-panel">
    <UiCard padding="lg">
      <SettingsForm section="mcp" :fields="['enabled']" />
      <p class="mcp-panel__note">MCP 服务为机器人提供外部工具。修改后应用配置会触发重连。</p>
    </UiCard>

    <UiCard v-for="(server, index) in servers" :key="index" padding="lg" :accent="server.enabled === false ? undefined : 'cyan'">
      <header class="server-head">
        <input
          class="server-head__id"
          :value="String(server.id ?? '')"
          placeholder="服务 ID"
          autocomplete="off"
          spellcheck="false"
          @input="patch(index, { id: ($event.target as HTMLInputElement).value })"
        />
        <UiTag size="sm" variant="info">{{ server.transport || 'stdio' }}</UiTag>
        <UiToggle size="sm" :model-value="server.enabled !== false" @update:model-value="patch(index, { enabled: $event })" />
        <button type="button" class="server-remove" title="删除该服务" @click="remove(index)"><UiIcon name="Trash2" :size="14" /></button>
      </header>

      <div class="server-grid">
        <SettingField label="传输方式" :model-value="String(server.transport ?? 'stdio')" :options="transportOptions" @update:model-value="patch(index, { transport: String($event) })" />
        <SettingField label="超时" unit="秒" :meta="{ type: 'number', minimum: 0 }" :model-value="numberOr(server.timeout_seconds, 30)" @update:model-value="patch(index, { timeout_seconds: $event })" />
        <SettingField label="工具名前缀" :model-value="String(server.tool_prefix ?? '')" hint="给该服务的工具名加前缀，避免撞名。留空不加。" @update:model-value="patch(index, { tool_prefix: $event === '' ? null : $event })" />

        <template v-if="transportOf(server) === 'stdio'">
          <SettingField class="server-grid__wide" label="启动命令" :model-value="String(server.command ?? '')" placeholder="npx 或 /path/to/server" @update:model-value="patch(index, { command: String($event) })" />
          <div class="server-grid__wide">
            <p class="sub-label">命令参数</p>
            <StringListEditor :model-value="stringList(server.args)" @update:model-value="patch(index, { args: $event })" />
          </div>
          <SettingField label="工作目录" :model-value="String(server.cwd ?? '')" hint="留空使用 Bot 进程目录。" @update:model-value="patch(index, { cwd: $event === '' ? null : $event })" />
          <div class="server-grid__wide">
            <p class="sub-label">环境变量 <UiInfoTip text="密钥值必须写成 ${变量名} 引用，不能直接填写。" /></p>
            <KeyValueEditor :model-value="objectValue(server.env)" @update:model-value="patch(index, { env: $event })" />
          </div>
        </template>

        <template v-else-if="transportOf(server) === 'docker'">
          <SettingField class="server-grid__wide" label="镜像" :model-value="String(server.image ?? '')" placeholder="org/mcp-server:latest" @update:model-value="patch(index, { image: String($event) })" />
          <SettingField label="Docker 命令" :model-value="String(server.docker_command ?? 'docker')" @update:model-value="patch(index, { docker_command: String($event) })" />
          <SettingField label="拉取策略" :model-value="String(server.pull_policy ?? 'missing')" :options="pullPolicyOptions" @update:model-value="patch(index, { pull_policy: String($event) })" />
          <div class="server-grid__wide">
            <p class="sub-label">Docker 参数</p>
            <StringListEditor :model-value="stringList(server.docker_args)" @update:model-value="patch(index, { docker_args: $event })" />
          </div>
          <div class="server-grid__wide">
            <p class="sub-label">挂载</p>
            <StringListEditor :model-value="stringList(server.mounts)" placeholder="宿主路径:容器路径" @update:model-value="patch(index, { mounts: $event })" />
          </div>
          <SettingField label="网络" :model-value="String(server.network ?? '')" @update:model-value="patch(index, { network: $event === '' ? null : $event })" />
          <SettingField label="容器工作目录" :model-value="String(server.container_workdir ?? '')" @update:model-value="patch(index, { container_workdir: $event === '' ? null : $event })" />
        </template>

        <template v-else>
          <SettingField class="server-grid__wide" label="服务地址" :model-value="String(server.url ?? '')" placeholder="https://example.com/mcp" @update:model-value="patch(index, { url: String($event) })" />
          <div class="server-grid__wide">
            <p class="sub-label">请求头 <UiInfoTip text="密钥值必须写成 ${变量名} 引用，不能直接填写。" /></p>
            <KeyValueEditor :model-value="objectValue(server.headers)" @update:model-value="patch(index, { headers: $event })" />
          </div>
        </template>

        <template v-if="String(server.transport ?? '') === 'http'">
          <SettingField label="协议协商" :model-value="String(server.negotiation ?? 'legacy')" :options="negotiationOptions" hint="自动/现代模式要求填写支持的协议版本。" @update:model-value="patch(index, { negotiation: String($event) })" />
          <SettingField label="协议版本" :model-value="String(server.protocol_version ?? '2025-03-26')" @update:model-value="patch(index, { protocol_version: String($event) })" />
          <div v-if="server.negotiation === 'auto' || server.negotiation === 'modern'" class="server-grid__wide">
            <p class="sub-label">支持的协议版本</p>
            <StringListEditor :model-value="stringList(server.supported_protocol_versions)" placeholder="2025-03-26" @update:model-value="patch(index, { supported_protocol_versions: $event })" />
          </div>
        </template>

        <div class="server-grid__wide">
          <p class="sub-label">只装载这些工具 <UiInfoTip text="留空不限制。" /></p>
          <StringListEditor :model-value="stringList(server.include_tools)" @update:model-value="patch(index, { include_tools: $event })" />
        </div>
        <div class="server-grid__wide">
          <p class="sub-label">排除这些工具</p>
          <StringListEditor :model-value="stringList(server.exclude_tools)" @update:model-value="patch(index, { exclude_tools: $event })" />
        </div>
      </div>
    </UiCard>

    <div class="mcp-panel__add">
      <UiButton icon="Plus" @click="add">添加 MCP 服务</UiButton>
      <UiEmpty v-if="!servers.length" icon="Network" title="暂无 MCP 服务" description="添加后机器人即可调用外部工具" />
    </div>
  </div>
</template>

<script setup lang="ts">
import { computed } from 'vue'
import UiButton from '../ui/UiButton.vue'
import UiCard from '../ui/UiCard.vue'
import UiEmpty from '../ui/UiEmpty.vue'
import UiIcon from '../ui/UiIcon.vue'
import UiInfoTip from '../ui/UiInfoTip.vue'
import UiTag from '../ui/UiTag.vue'
import UiToggle from '../ui/UiToggle.vue'
import SettingField from './SettingField.vue'
import StringListEditor from './StringListEditor.vue'
import KeyValueEditor from './KeyValueEditor.vue'
import SettingsForm from './SettingsForm.vue'
import { injectLlmConfigStore } from '../../composables/useLlmConfigStore'
import { MCP_NEGOTIATION_OPTIONS, MCP_PULL_POLICY_OPTIONS, MCP_TRANSPORT_OPTIONS, fieldTemplate, isObject, type JsonObject, type JsonValue } from '../../lib/llmConfig'

const store = injectLlmConfigStore()

const servers = computed<JsonObject[]>(() => {
  const settings = store.document.value?.settings
  const mcp = isObject(settings) && isObject(settings.mcp) ? settings.mcp : {}
  return Array.isArray(mcp.servers) ? mcp.servers.filter(isObject) : []
})

const transportOptions = MCP_TRANSPORT_OPTIONS.map(value => ({ value, label: value }))
const pullPolicyOptions = MCP_PULL_POLICY_OPTIONS.map(value => ({ value, label: { always: '总是拉取', missing: '缺失才拉取', never: '从不拉取' }[value]! }))
const negotiationOptions = MCP_NEGOTIATION_OPTIONS.map(value => ({ value, label: { legacy: '旧版（固定版本）', auto: '自动协商', modern: '现代（仅新版本）' }[value]! }))

function mcpSection(): JsonObject {
  const settings = store.document.value?.settings
  return isObject(settings) && isObject(settings.mcp) ? settings.mcp : {}
}
function commit(next: JsonObject[]) { store.updateSettingsSection('mcp', { ...mcpSection(), servers: next }) }
function patch(index: number, fields: JsonObject) { commit(servers.value.map((server, i) => i === index ? { ...server, ...fields } : server)) }
function remove(index: number) { if (confirm(`确定删除 MCP 服务「${servers.value[index]?.id || '未命名'}」？`)) commit(servers.value.filter((_, i) => i !== index)) }
function add() { commit([...servers.value, structuredClone(fieldTemplate('servers'))]) }

function transportOf(server: JsonObject) { const value = String(server.transport ?? 'stdio'); return value === 'sse' ? 'http' : value }
function stringList(value: JsonValue | undefined): string[] { return Array.isArray(value) ? value.map(String) : [] }
function objectValue(value: JsonValue | undefined): JsonObject { return isObject(value) ? value : {} }
function numberOr(value: JsonValue | undefined, fallback: number) { return typeof value === 'number' ? value : fallback }
</script>

<style scoped>
.mcp-panel {
  display: grid;
  gap: var(--qq-gap-md);
}

.mcp-panel__note {
  margin: var(--qq-gap-sm) 0 0;
  color: var(--qq-text-muted);
  font-size: var(--qq-text-sm);
}

.server-head {
  display: flex;
  align-items: center;
  gap: 10px;
  margin-bottom: var(--qq-gap-md);
}

.server-head__id {
  flex: 1;
  min-width: 0;
  max-width: 260px;
  padding: 7px 10px;
  border: 1px solid var(--qq-border);
  border-radius: var(--qq-radius-md);
  background: var(--qq-bg);
  color: var(--qq-text);
  font: inherit;
  font-size: var(--qq-text-sm);
  font-family: var(--qq-font-mono);
  font-weight: 600;
}

.server-remove {
  margin-left: auto;
  display: inline-flex;
  align-items: center;
  justify-content: center;
  width: 26px;
  height: 26px;
  border: 0;
  border-radius: var(--qq-radius-sm);
  background: transparent;
  color: var(--qq-text-muted);
  cursor: pointer;
}

.server-remove:hover {
  background: var(--qq-danger-soft);
  color: var(--qq-danger);
}

.server-grid {
  display: grid;
  grid-template-columns: repeat(2, minmax(0, 1fr));
  gap: var(--qq-gap-md);
}

.server-grid__wide {
  grid-column: 1 / -1;
}

.sub-label {
  margin: 0 0 6px;
  color: var(--qq-text);
  font-size: var(--qq-text-sm);
  font-weight: 500;
  display: flex;
  align-items: center;
  gap: 4px;
}

.mcp-panel__add {
  display: grid;
  gap: var(--qq-gap-md);
  justify-items: start;
}

@media (max-width: 760px) {
  .server-grid { grid-template-columns: 1fr; }
}
</style>
