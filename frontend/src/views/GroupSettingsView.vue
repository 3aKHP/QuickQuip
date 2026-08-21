<template>
  <div class="gs-view">
    <UiPageHeader title="群组 LLM 设置" subtitle="按群覆盖 provider / model / persona / 触发方式等运行时参数">
      <template #actions>
        <UiButton icon="RefreshCw" :disabled="loading" @click="reloadAll">刷新</UiButton>
        <UiButton variant="primary" icon="Plus" @click="startAdd">添加群</UiButton>
      </template>
    </UiPageHeader>

    <p v-if="loadError" class="error">{{ loadError }}</p>
    <p v-if="options && options.load_error" class="warn-text">
      <UiIcon name="AlertTriangle" :size="14" />
      llm.toml 加载失败：{{ options.load_error }}；provider/persona 下拉可能为空
    </p>

    <div class="settings-shell">
      <aside class="group-panel">
        <div class="panel-head">
          <span class="panel-title">覆盖对象</span>
          <span class="panel-count">{{ groupList.length }}</span>
        </div>

        <UiLoading v-if="loading && !groupList.length" />
        <UiEmpty v-else-if="!groupList.length" icon="Users" title="尚无群级 override" />
        <div v-else class="group-list">
          <button
            v-for="g in groupList"
            :key="g.group_id"
            class="group-item"
            :class="{ active: g.group_id === selectedGroupId }"
            @click="selectGroup(g.group_id)"
          >
            <span class="group-item__top">
              <UiTag size="sm" :variant="g.type === 'private' ? 'success' : 'info'">
                {{ g.type === 'private' ? '私聊' : '群聊' }}
              </UiTag>
              <span class="mono group-id">{{ displayId(g.group_id) }}</span>
              <UiTag v-if="g.enabled === true" size="sm" variant="success">LLM 开</UiTag>
              <UiTag v-else-if="g.enabled === false" size="sm" variant="danger">LLM 关</UiTag>
            </span>
            <span class="group-item__meta">
              <span v-if="g.persona_id">{{ g.persona_id }}</span>
              <span v-if="g.provider_id">{{ g.provider_id }}</span>
              <span v-if="g.model" class="mono">{{ g.model }}</span>
              <span v-if="!g.persona_id && !g.provider_id && !g.model">仅覆盖开关或触发方式</span>
            </span>
          </button>
        </div>
      </aside>

      <main class="editor-panel">
        <div v-if="!selectedGroupId" class="empty-editor">
          <UiEmpty icon="Settings" title="选择或添加一个群来编辑覆盖设置" />
        </div>

        <template v-else>
          <div class="editor-head">
            <div>
              <span class="editor-kicker">当前对象</span>
              <h3>
                <UiTag size="sm" :variant="selectedIsPrivate ? 'success' : 'info'">
                  {{ selectedIsPrivate ? '私聊' : '群聊' }}
                </UiTag>
                <span class="mono">{{ displayId(selectedGroupId) }}</span>
              </h3>
            </div>
            <div class="editor-actions">
              <UiButton variant="danger" icon="Trash2" :disabled="saving" @click="onClear">清空全部 override</UiButton>
              <UiButton variant="primary" icon="Save" :loading="saving" :disabled="!hasChanges" @click="onSave">保存</UiButton>
            </div>
          </div>

          <p v-if="saveError" class="error">{{ saveError }}</p>

          <section class="default-strip">
            <div class="default-item">
              <span>默认 Provider</span>
              <strong>{{ defaults.provider_id || '未设置' }}</strong>
            </div>
            <div class="default-item">
              <span>默认 Persona</span>
              <strong>{{ defaults.persona_id || '未设置' }}</strong>
            </div>
            <div class="default-item">
              <span>默认触发前缀</span>
              <strong>{{ defaults.trigger_prefix || '/ai' }}</strong>
            </div>
            <div class="default-item">
              <span>默认历史</span>
              <strong>{{ defaults.history_limit ?? 10 }}</strong>
            </div>
          </section>

          <section class="form-section">
            <h4>运行状态</h4>
            <div class="form-grid form-grid--three">
              <div class="field">
                <label>LLM 启用</label>
                <select v-model="draftTriState.enabled">
                  <option :value="null">跟随默认（{{ defaultHint('enabled') }}）</option>
                  <option :value="true">开</option>
                  <option :value="false">关</option>
                </select>
              </div>
              <div class="field">
                <label>记忆启用</label>
                <select v-model="draftTriState.memory_enabled">
                  <option :value="null">跟随默认（{{ defaultHint('memory_enabled') }}）</option>
                  <option :value="true">开</option>
                  <option :value="false">关</option>
                </select>
              </div>
              <div class="field">
                <label>自动记忆抽取</label>
                <select v-model="draftTriState.auto_memory_enabled">
                  <option :value="null">跟随默认（{{ defaultHint('auto_memory_enabled') }}）</option>
                  <option :value="true">开</option>
                  <option :value="false">关</option>
                </select>
              </div>
            </div>
          </section>

          <section class="form-section">
            <h4>模型与人格</h4>
            <div class="form-grid">
              <div class="field">
                <label>Provider</label>
                <select v-model="draftTriState.provider_id">
                  <option :value="null">跟随默认（{{ defaults.provider_id || '未设置' }}）</option>
                  <option v-for="p in providers" :key="p.id" :value="p.id">{{ p.id }}</option>
                </select>
              </div>
              <div class="field">
                <label>Model</label>
                <div class="field-row">
                  <input v-model="modelInput" :placeholder="modelPlaceholder" list="model-suggestions" />
                  <datalist id="model-suggestions">
                    <option v-for="m in modelSuggestions" :key="m" :value="m" />
                  </datalist>
                  <UiButton v-if="draftTriState.model !== null" size="sm" variant="ghost" icon="X" @click="clearModel">跟随</UiButton>
                </div>
              </div>
              <div class="field">
                <label>Persona</label>
                <select v-model="draftTriState.persona_id">
                  <option :value="null">跟随默认（{{ defaults.persona_id || '未设置' }}）</option>
                  <option v-for="p in personas" :key="p.id" :value="p.id">
                    {{ p.display_name || p.id }}（{{ p.id }}）
                  </option>
                </select>
              </div>
            </div>
          </section>

          <section class="form-section">
            <h4>触发方式</h4>
            <div class="form-grid">
              <div class="field">
                <label>触发前缀</label>
                <div class="field-row">
                  <input v-model="prefixInput" :placeholder="defaults.trigger_prefix || '/ai'" />
                  <UiButton v-if="draftTriState.trigger_prefix !== null" size="sm" variant="ghost" icon="X" @click="clearPrefix">跟随</UiButton>
                </div>
              </div>
              <div class="field">
                <label>允许前缀触发</label>
                <select v-model="draftTriState.allow_prefix">
                  <option :value="null">跟随默认（{{ defaultHint('allow_prefix') }}）</option>
                  <option :value="true">开</option>
                  <option :value="false">关</option>
                </select>
              </div>
              <div class="field">
                <label>允许 @ 触发</label>
                <select v-model="draftTriState.allow_at">
                  <option :value="null">跟随默认（{{ defaultHint('allow_at') }}）</option>
                  <option :value="true">开</option>
                  <option :value="false">关</option>
                </select>
              </div>
              <div class="field">
                <label>历史条数</label>
                <div class="field-row">
                  <input v-model.number="historyInput" type="number" min="0" max="200" :placeholder="String(defaults.history_limit ?? 10)" />
                  <UiButton v-if="draftTriState.history_limit !== null" size="sm" variant="ghost" icon="X" @click="clearHistory">跟随</UiButton>
                </div>
              </div>
            </div>
          </section>
        </template>
      </main>
    </div>
  </div>
</template>

<script setup lang="ts">
import { computed, ref, watch } from 'vue'
import UiButton from '../components/ui/UiButton.vue'
import UiEmpty from '../components/ui/UiEmpty.vue'
import UiIcon from '../components/ui/UiIcon.vue'
import UiLoading from '../components/ui/UiLoading.vue'
import UiPageHeader from '../components/ui/UiPageHeader.vue'
import UiTag from '../components/ui/UiTag.vue'
import {
  clearGroupSettings,
  fetchGroupSettings,
  fetchOptions,
  listGroupSettings,
  saveGroupSettings,
} from '../api/groupSettings'
import type {
  GroupOverrideEntry,
  GroupSettingsDefaults,
  GroupSettingsOptions,
} from '../api/groupSettings'
import { useGroupOverrideDraft } from '../composables/useGroupOverrideDraft'
import { toast } from '../toast'

const options = ref<GroupSettingsOptions | null>(null)
const groupList = ref<GroupOverrideEntry[]>([])
const loading = ref(false)
const loadError = ref<string | null>(null)
const selectedGroupId = ref('')
const saving = ref(false)
const saveError = ref<string | null>(null)

const {
  draft: draftTriState,
  hasChanges,
  modelInput,
  prefixInput,
  historyInput,
  clearModel,
  clearPrefix,
  clearHistory,
  applyData,
  resetDraft,
  buildPatch,
} = useGroupOverrideDraft()

function displayId(key: string): string {
  if (!key) return ''
  return key.startsWith('private:') ? key.slice('private:'.length) : key
}

const selectedIsPrivate = computed(() => selectedGroupId.value.startsWith('private:'))
const providers = computed(() => options.value?.providers || [])
const personas = computed(() => options.value?.personas || [])
const defaults = computed(() => options.value?.defaults || {})

function defaultHint(field: keyof GroupSettingsDefaults): string {
  const value = defaults.value[field]
  if (value === true) return '开'
  if (value === false) return '关'
  if (value == null) return '未设置'
  return String(value)
}

const modelPlaceholder = computed(() => {
  const providerId = draftTriState.value.provider_id ?? defaults.value.provider_id
  const provider = providers.value.find(p => p.id === providerId)
  return provider?.default_model || '默认 model'
})

const modelSuggestions = computed(() => {
  const providerId = draftTriState.value.provider_id ?? defaults.value.provider_id
  const provider = providers.value.find(p => p.id === providerId)
  return provider?.models || []
})

async function reloadAll() {
  loading.value = true
  loadError.value = null
  try {
    const [optsData, listData] = await Promise.all([
      fetchOptions(),
      listGroupSettings(),
    ])
    options.value = optsData
    groupList.value = listData.groups || []
    if (selectedGroupId.value) {
      await loadOne(selectedGroupId.value)
    }
  } catch (e: unknown) {
    loadError.value = (e as Error).message
  } finally {
    loading.value = false
  }
}

async function loadOne(groupId: string) {
  saveError.value = null
  try {
    const data = await fetchGroupSettings(groupId)
    applyData(data)
  } catch (e: unknown) {
    saveError.value = (e as Error).message
  }
}

async function selectGroup(groupId: string) {
  if (groupId === selectedGroupId.value) return
  if (hasChanges.value && !confirm('当前群的修改未保存，切换会丢失。是否继续？')) return
  selectedGroupId.value = groupId
  await loadOne(groupId)
}

function startAdd() {
  const raw = prompt('新增覆盖对象：\n- 群聊请填 5-12 位群号\n- 私聊请填 private:USER_ID（例 private:123456789）')
  if (!raw) return
  const key = raw.trim()
  if (!/^(?:\d{5,12}|private:\d{5,15})$/.test(key)) {
    toast('格式不合法', 'error')
    return
  }
  if (hasChanges.value && !confirm('当前修改未保存，切换会丢失。是否继续？')) return
  selectedGroupId.value = key
  resetDraft()
}

async function onSave() {
  const diff = buildPatch()
  if (!Object.keys(diff).length) return
  saving.value = true
  saveError.value = null
  try {
    await saveGroupSettings(selectedGroupId.value, diff)
    toast('已保存')
    await reloadAll()
  } catch (e: unknown) {
    saveError.value = (e as Error).message
    toast('保存失败', 'error')
  } finally {
    saving.value = false
  }
}

async function onClear() {
  const label = (selectedIsPrivate.value ? '私聊 ' : '群 ') + displayId(selectedGroupId.value)
  if (!confirm(`清空 ${label} 的全部 override？该会话将恢复到默认配置。`)) return
  try {
    await clearGroupSettings(selectedGroupId.value)
    toast('已清空')
    selectedGroupId.value = ''
    resetDraft()
    await reloadAll()
  } catch (e: unknown) {
    toast((e as Error).message, 'error')
  }
}

watch(selectedGroupId, () => { saveError.value = null })

reloadAll()
</script>

<style scoped>
.gs-view {
  display: flex;
  min-height: 0;
  flex: 1;
  flex-direction: column;
}

.error {
  color: var(--qq-danger);
  font-size: var(--qq-text-sm);
}

.warn-text {
  display: inline-flex;
  align-items: center;
  gap: 6px;
  color: var(--qq-warn);
  font-size: var(--qq-text-sm);
  margin-bottom: var(--qq-gap-sm);
}

.mono {
  font-family: var(--qq-font-mono);
}

.settings-shell {
  display: grid;
  min-height: 0;
  flex: 1;
  grid-template-columns: 300px minmax(0, 1fr);
  gap: var(--qq-gap-md);
}

.group-panel,
.editor-panel {
  min-width: 0;
  min-height: 0;
  background: var(--qq-surface);
  border: 1px solid var(--qq-border);
  border-radius: var(--qq-radius-card);
  box-shadow: var(--qq-shadow-card);
}

.group-panel {
  display: flex;
  flex-direction: column;
  overflow: hidden;
}

.panel-head {
  display: flex;
  align-items: center;
  justify-content: space-between;
  height: 48px;
  padding: 0 var(--qq-gap-md);
  border-bottom: 1px solid var(--qq-border);
}

.panel-title {
  color: var(--qq-text);
  font-size: var(--qq-text-sm);
  font-weight: 700;
}

.panel-count {
  color: var(--qq-text-muted);
  font-family: var(--qq-font-mono);
  font-size: var(--qq-text-xs);
}

.group-list {
  display: flex;
  flex: 1;
  flex-direction: column;
  overflow-y: auto;
}

.group-item {
  width: 100%;
  display: flex;
  flex-direction: column;
  gap: 5px;
  padding: var(--qq-gap-sm) var(--qq-gap-md);
  border: 0;
  border-bottom: 1px solid var(--qq-border);
  background: transparent;
  color: var(--qq-text);
  cursor: pointer;
  font-family: var(--qq-font-base);
  text-align: left;
  transition: background var(--qq-transition-fast);
}

.group-item:hover {
  background: var(--qq-surface-hover);
}

.group-item.active {
  background: var(--qq-primary-soft);
  box-shadow: inset 3px 0 0 var(--qq-primary);
}

.group-item__top {
  display: flex;
  align-items: center;
  gap: var(--qq-gap-xs);
  min-width: 0;
}

.group-id {
  min-width: 0;
  color: var(--qq-text);
  font-size: var(--qq-text-base);
  font-weight: 600;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.group-item__meta {
  display: flex;
  flex-wrap: wrap;
  gap: var(--qq-gap-xs);
  color: var(--qq-text-muted);
  font-size: var(--qq-text-xs);
}

.editor-panel {
  display: flex;
  flex-direction: column;
  gap: var(--qq-gap-md);
  overflow-y: auto;
  padding: var(--qq-gap-md);
}

.empty-editor {
  display: flex;
  min-height: 320px;
  flex: 1;
  align-items: center;
  justify-content: center;
}

.editor-head {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: var(--qq-gap-md);
  padding-bottom: var(--qq-gap-md);
  border-bottom: 1px solid var(--qq-border);
}

.editor-kicker {
  display: block;
  margin-bottom: 4px;
  color: var(--qq-primary);
  font-size: var(--qq-text-xs);
  font-weight: 700;
}

.editor-head h3 {
  display: flex;
  align-items: center;
  gap: var(--qq-gap-sm);
  margin: 0;
  color: var(--qq-text);
  font-size: var(--qq-text-lg);
}

.editor-actions {
  display: flex;
  gap: var(--qq-gap-sm);
  flex-wrap: wrap;
}

.default-strip {
  display: grid;
  grid-template-columns: repeat(4, minmax(0, 1fr));
  gap: var(--qq-gap-sm);
}

.default-item {
  min-width: 0;
  padding: var(--qq-gap-sm);
  border-radius: var(--qq-radius-sm);
  background: var(--qq-surface-strong);
}

.default-item span {
  display: block;
  color: var(--qq-text-muted);
  font-size: var(--qq-text-xs);
}

.default-item strong {
  display: block;
  color: var(--qq-text);
  font-family: var(--qq-font-mono);
  font-size: var(--qq-text-sm);
  font-weight: 700;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.form-section {
  display: flex;
  flex-direction: column;
  gap: var(--qq-gap-sm);
}

.form-section h4 {
  margin: 0;
  color: var(--qq-text);
  font-size: var(--qq-text-base);
}

.form-grid {
  display: grid;
  grid-template-columns: repeat(auto-fit, minmax(260px, 1fr));
  gap: var(--qq-gap-md);
}

.form-grid--three {
  grid-template-columns: repeat(3, minmax(0, 1fr));
}

.field {
  display: flex;
  min-width: 0;
  flex-direction: column;
  gap: var(--qq-gap-xs);
}

.field label {
  color: var(--qq-text-muted);
  font-size: var(--qq-text-xs);
  font-weight: 600;
}

.field-row {
  display: flex;
  align-items: center;
  gap: var(--qq-gap-xs);
}

.field-row input {
  flex: 1;
  min-width: 0;
}

@media (max-width: 1100px) {
  .settings-shell {
    grid-template-columns: 1fr;
  }

  .group-panel {
    max-height: 260px;
  }
}

@media (max-width: 767px) {
  .editor-head {
    align-items: flex-start;
    flex-direction: column;
  }

  .default-strip,
  .form-grid,
  .form-grid--three {
    grid-template-columns: 1fr;
  }
}
</style>
