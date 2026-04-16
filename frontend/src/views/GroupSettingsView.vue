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

    <div class="split">
      <UiCard padding="none" shadow="sm" class="list-card">
        <UiLoading v-if="loading && !groupList.length" />
        <UiEmpty
          v-else-if="!groupList.length"
          icon="Users"
          title="尚无群级 override"
        />
        <ul v-else class="group-list">
          <li
            v-for="g in groupList"
            :key="g.group_id"
            class="group-item"
            :class="{ active: g.group_id === selectedGroupId }"
            @click="selectGroup(g.group_id)"
          >
            <div class="group-head">
              <span class="mono group-id">{{ g.group_id }}</span>
              <UiTag v-if="g.enabled === true" size="sm" variant="success">LLM 开</UiTag>
              <UiTag v-else-if="g.enabled === false" size="sm" variant="danger">LLM 关</UiTag>
            </div>
            <div class="group-meta">
              <span v-if="g.persona_id">{{ g.persona_id }}</span>
              <span v-if="g.provider_id">· {{ g.provider_id }}</span>
              <span v-if="g.model" class="mono">· {{ g.model }}</span>
            </div>
          </li>
        </ul>
      </UiCard>

      <div class="main-col">
        <UiCard v-if="!selectedGroupId" padding="lg" shadow="sm" class="hint-card">
          <UiEmpty icon="Settings" title="选择或添加一个群来编辑覆盖设置" />
        </UiCard>

        <template v-else>
          <UiCard padding="md" shadow="sm" class="form-card">
            <div class="form-title">
              <span class="mono">群 {{ selectedGroupId }}</span>
              <div class="form-actions">
                <UiButton
                  variant="danger"
                  icon="Trash2"
                  :disabled="saving"
                  @click="onClear"
                >清空全部 override</UiButton>
                <UiButton
                  variant="primary"
                  icon="Save"
                  :loading="saving"
                  :disabled="!hasChanges"
                  @click="onSave"
                >保存</UiButton>
              </div>
            </div>

            <p v-if="saveError" class="error">{{ saveError }}</p>

            <div class="form-grid">
              <!-- enabled -->
              <div class="field">
                <label>LLM 启用</label>
                <select v-model="draftTriState.enabled">
                  <option :value="null">跟随默认（{{ defaultHint('enabled') }}）</option>
                  <option :value="true">开</option>
                  <option :value="false">关</option>
                </select>
              </div>

              <!-- memory_enabled -->
              <div class="field">
                <label>记忆启用</label>
                <select v-model="draftTriState.memory_enabled">
                  <option :value="null">跟随默认（{{ defaultHint('memory_enabled') }}）</option>
                  <option :value="true">开</option>
                  <option :value="false">关</option>
                </select>
              </div>

              <!-- provider_id -->
              <div class="field">
                <label>Provider</label>
                <select v-model="draftTriState.provider_id">
                  <option :value="null">跟随默认（{{ defaults.provider_id || '未设置' }}）</option>
                  <option v-for="p in providers" :key="p.id" :value="p.id">{{ p.id }}</option>
                </select>
              </div>

              <!-- model -->
              <div class="field">
                <label>Model</label>
                <div class="model-row">
                  <input
                    v-model="modelInput"
                    :placeholder="modelPlaceholder"
                    list="model-suggestions"
                  />
                  <datalist id="model-suggestions">
                    <option v-for="m in modelSuggestions" :key="m" :value="m" />
                  </datalist>
                  <UiButton
                    v-if="draftTriState.model !== null"
                    size="sm"
                    variant="ghost"
                    icon="X"
                    @click="clearModel"
                  >跟随</UiButton>
                </div>
              </div>

              <!-- persona_id -->
              <div class="field">
                <label>Persona</label>
                <select v-model="draftTriState.persona_id">
                  <option :value="null">跟随默认（{{ defaults.persona_id || '未设置' }}）</option>
                  <option v-for="p in personas" :key="p.id" :value="p.id">
                    {{ p.display_name || p.id }}（{{ p.id }}）
                  </option>
                </select>
              </div>

              <!-- trigger_prefix -->
              <div class="field">
                <label>触发前缀</label>
                <div class="model-row">
                  <input v-model="prefixInput" :placeholder="defaults.trigger_prefix || '/ai'" />
                  <UiButton
                    v-if="draftTriState.trigger_prefix !== null"
                    size="sm"
                    variant="ghost"
                    icon="X"
                    @click="clearPrefix"
                  >跟随</UiButton>
                </div>
              </div>

              <!-- allow_prefix -->
              <div class="field">
                <label>允许前缀触发</label>
                <select v-model="draftTriState.allow_prefix">
                  <option :value="null">跟随默认（{{ defaultHint('allow_prefix') }}）</option>
                  <option :value="true">开</option>
                  <option :value="false">关</option>
                </select>
              </div>

              <!-- allow_at -->
              <div class="field">
                <label>允许 @ 触发</label>
                <select v-model="draftTriState.allow_at">
                  <option :value="null">跟随默认（{{ defaultHint('allow_at') }}）</option>
                  <option :value="true">开</option>
                  <option :value="false">关</option>
                </select>
              </div>

              <!-- history_limit -->
              <div class="field">
                <label>历史条数</label>
                <div class="model-row">
                  <input
                    v-model.number="historyInput"
                    type="number"
                    min="0"
                    max="200"
                    :placeholder="String(defaults.history_limit ?? 10)"
                  />
                  <UiButton
                    v-if="draftTriState.history_limit !== null"
                    size="sm"
                    variant="ghost"
                    icon="X"
                    @click="clearHistory"
                  >跟随</UiButton>
                </div>
              </div>
            </div>
          </UiCard>
        </template>
      </div>
    </div>
  </div>
</template>

<script setup>
import { computed, ref, watch } from 'vue'
import UiPageHeader from '../components/ui/UiPageHeader.vue'
import UiButton from '../components/ui/UiButton.vue'
import UiCard from '../components/ui/UiCard.vue'
import UiTag from '../components/ui/UiTag.vue'
import UiIcon from '../components/ui/UiIcon.vue'
import UiLoading from '../components/ui/UiLoading.vue'
import UiEmpty from '../components/ui/UiEmpty.vue'
import {
  fetchOptions,
  listGroupSettings,
  fetchGroupSettings,
  saveGroupSettings,
  clearGroupSettings,
} from '../api/groupSettings.js'
import { toast } from '../toast.js'

const FIELDS = [
  'enabled', 'memory_enabled', 'provider_id', 'model', 'persona_id',
  'trigger_prefix', 'allow_prefix', 'allow_at', 'history_limit',
]

const options = ref(null)
const groupList = ref([])
const loading = ref(false)
const loadError = ref(null)

const selectedGroupId = ref('')
const original = ref(emptyDraft())
const draftTriState = ref(emptyDraft())
const saving = ref(false)
const saveError = ref(null)

function emptyDraft() {
  return Object.fromEntries(FIELDS.map(f => [f, null]))
}

const providers = computed(() => options.value?.providers || [])
const personas = computed(() => options.value?.personas || [])
const defaults = computed(() => options.value?.defaults || {})

function defaultHint(field) {
  const v = defaults.value[field]
  if (v === true) return '开'
  if (v === false) return '关'
  if (v == null) return '未设置'
  return String(v)
}

const modelInput = computed({
  get: () => draftTriState.value.model ?? '',
  set: (v) => { draftTriState.value.model = v === '' ? null : v },
})

const prefixInput = computed({
  get: () => draftTriState.value.trigger_prefix ?? '',
  set: (v) => { draftTriState.value.trigger_prefix = v === '' ? null : v },
})

const historyInput = computed({
  get: () => draftTriState.value.history_limit ?? '',
  set: (v) => {
    if (v === '' || v == null || Number.isNaN(Number(v))) {
      draftTriState.value.history_limit = null
    } else {
      draftTriState.value.history_limit = Number(v)
    }
  },
})

const modelPlaceholder = computed(() => {
  const pid = draftTriState.value.provider_id ?? defaults.value.provider_id
  const provider = providers.value.find(p => p.id === pid)
  return provider?.default_model || '默认 model'
})

const modelSuggestions = computed(() => {
  const pid = draftTriState.value.provider_id ?? defaults.value.provider_id
  const provider = providers.value.find(p => p.id === pid)
  return provider?.models || []
})

const hasChanges = computed(() => {
  for (const f of FIELDS) {
    if (draftTriState.value[f] !== original.value[f]) return true
  }
  return false
})

function clearModel() { draftTriState.value.model = null }
function clearPrefix() { draftTriState.value.trigger_prefix = null }
function clearHistory() { draftTriState.value.history_limit = null }

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
  } catch (e) {
    loadError.value = e.message
  } finally {
    loading.value = false
  }
}

async function loadOne(groupId) {
  saveError.value = null
  try {
    const data = await fetchGroupSettings(groupId)
    const snapshot = emptyDraft()
    for (const f of FIELDS) {
      if (data[f] !== undefined) snapshot[f] = data[f]
    }
    original.value = snapshot
    draftTriState.value = { ...snapshot }
  } catch (e) {
    saveError.value = e.message
  }
}

async function selectGroup(groupId) {
  if (groupId === selectedGroupId.value) return
  if (hasChanges.value && !confirm('当前群的修改未保存，切换会丢失。是否继续？')) return
  selectedGroupId.value = groupId
  await loadOne(groupId)
}

function startAdd() {
  const raw = prompt('新群号（5-12 位数字）')
  if (!raw) return
  const gid = raw.trim()
  if (!/^\d{5,12}$/.test(gid)) {
    toast('群号不合法', 'error')
    return
  }
  if (hasChanges.value && !confirm('当前群的修改未保存，切换会丢失。是否继续？')) return
  selectedGroupId.value = gid
  original.value = emptyDraft()
  draftTriState.value = emptyDraft()
}

async function onSave() {
  const diff = {}
  for (const f of FIELDS) {
    if (draftTriState.value[f] !== original.value[f]) {
      diff[f] = draftTriState.value[f]
    }
  }
  if (!Object.keys(diff).length) return
  saving.value = true
  saveError.value = null
  try {
    await saveGroupSettings(selectedGroupId.value, diff)
    toast('已保存')
    await reloadAll()
  } catch (e) {
    saveError.value = e.message
    toast('保存失败', 'error')
  } finally {
    saving.value = false
  }
}

async function onClear() {
  if (!confirm(`清空群 ${selectedGroupId.value} 的全部 override？该群将恢复到默认配置。`)) return
  try {
    await clearGroupSettings(selectedGroupId.value)
    toast('已清空')
    selectedGroupId.value = ''
    original.value = emptyDraft()
    draftTriState.value = emptyDraft()
    await reloadAll()
  } catch (e) {
    toast(e.message, 'error')
  }
}

watch(selectedGroupId, () => { saveError.value = null })

reloadAll()
</script>

<style scoped>
.gs-view {
  display: flex;
  flex-direction: column;
  flex: 1;
  min-height: 0;
}

.error {
  color: var(--qq-danger);
}

.warn-text {
  display: inline-flex;
  align-items: center;
  gap: 6px;
  color: var(--qq-warn);
  font-size: 13px;
  margin-bottom: var(--qq-gap-sm);
}

.mono {
  font-family: var(--qq-font-mono);
}

.split {
  display: flex;
  gap: var(--qq-gap-md);
  flex: 1;
  min-height: 0;
}

.list-card {
  width: 280px;
  flex-shrink: 0;
  overflow-y: auto;
  max-height: calc(100vh - 180px);
}

.group-list {
  list-style: none;
  margin: 0;
  padding: 0;
}

.group-item {
  padding: var(--qq-gap-sm) var(--qq-gap-md);
  border-bottom: 1px solid var(--qq-border);
  cursor: pointer;
  transition: background var(--qq-transition-fast);
}

.group-item:last-child {
  border-bottom: none;
}

.group-item:hover {
  background: var(--qq-surface-elevated);
}

.group-item.active {
  background: var(--qq-surface-elevated);
  box-shadow: inset 3px 0 0 var(--qq-accent);
}

.group-head {
  display: flex;
  align-items: center;
  gap: var(--qq-gap-xs);
  margin-bottom: 3px;
}

.group-id {
  font-size: 14px;
  font-weight: 500;
  color: var(--qq-text);
}

.group-meta {
  font-size: 12px;
  color: var(--qq-text-muted);
  display: flex;
  gap: 4px;
  flex-wrap: wrap;
}

.main-col {
  display: flex;
  flex-direction: column;
  flex: 1;
  min-width: 0;
  gap: var(--qq-gap-sm);
}

.hint-card {
  flex: 1;
  display: flex;
  align-items: center;
  justify-content: center;
}

.form-card {
  flex: 1;
}

.form-title {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: var(--qq-gap-md);
  flex-wrap: wrap;
  margin-bottom: var(--qq-gap-md);
  padding-bottom: var(--qq-gap-sm);
  border-bottom: 1px solid var(--qq-border);
}

.form-actions {
  display: flex;
  gap: var(--qq-gap-sm);
}

.form-grid {
  display: grid;
  grid-template-columns: repeat(auto-fit, minmax(260px, 1fr));
  gap: var(--qq-gap-md);
}

.field {
  display: flex;
  flex-direction: column;
  gap: var(--qq-gap-xs);
}

.field label {
  font-size: 12px;
  color: var(--qq-text-muted);
  font-weight: 500;
}

.field select,
.field input {
  background: var(--qq-surface-strong);
  border: 1px solid var(--qq-border);
  border-radius: var(--qq-radius-sm);
  color: var(--qq-text);
  padding: 6px 10px;
  font-size: 13px;
  outline: none;
  width: 100%;
}

.field select:focus,
.field input:focus {
  border-color: var(--qq-accent);
  box-shadow: 0 0 0 3px var(--qq-accent-soft);
}

.model-row {
  display: flex;
  gap: var(--qq-gap-xs);
  align-items: center;
}

.model-row input {
  flex: 1;
}

@media (max-width: 900px) {
  .split {
    flex-direction: column;
  }
  .list-card {
    width: 100%;
    max-height: 200px;
  }
}
</style>
