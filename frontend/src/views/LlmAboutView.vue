<template>
  <div class="llm-about-view">
    <UiPageHeader title="资料">
      <template #actions>
        <span class="hint">
          <UiIcon name="Info" :size="14" />
          保存后执行 /llm reload 或重启 bot 生效
        </span>
        <span v-if="basePath" class="hint mono">{{ basePath }}</span>
        <UiButton icon="RefreshCw" :disabled="listing" @click="loadList">刷新</UiButton>
        <UiButton variant="primary" icon="Plus" @click="startCreateGroup">新建群资料</UiButton>
      </template>
    </UiPageHeader>

    <p v-if="listError" class="error">{{ listError }}</p>

    <div class="split">
      <UiCard padding="none" shadow="sm" class="scope-card">
        <UiLoading v-if="listing && !scopes.length" />
        <UiEmpty v-else-if="!scopes.length" icon="BookUser" title="暂无资料文件" />
        <ul v-else class="scope-list">
          <li
            v-for="scope in scopes"
            :key="scope.scope"
            class="scope-item"
            :class="{ active: scope.scope === selectedScope }"
            @click="selectScope(scope.scope)"
          >
            <div class="scope-title">
              <span>{{ scope.label }}</span>
              <UiTag v-if="scope.global" size="sm" variant="info">全局</UiTag>
              <UiTag v-if="scope.existing_files < scope.total_files" size="sm" variant="warn">缺失</UiTag>
            </div>
            <div class="scope-meta">
              <span class="mono">{{ scope.path }}</span>
              <span>{{ scope.existing_files }}/{{ scope.total_files }}</span>
            </div>
          </li>
        </ul>
      </UiCard>

      <div class="editor-col">
        <div v-if="selectedScope" class="kind-tabs">
          <button
            v-for="kind in kinds"
            :key="kind.kind"
            class="kind-tab"
            :class="{ active: kind.kind === selectedKind }"
            @click="selectKind(kind.kind)"
          >
            <span class="kind-label">{{ kind.label }}</span>
            <span class="kind-file">{{ kind.filename }}</span>
          </button>
        </div>

        <UiCard v-if="!selectedScope" padding="lg" shadow="sm" class="hint-card">
          <UiEmpty icon="BookUser" title="从左侧选择全局或群级资料" />
        </UiCard>

        <template v-else>
          <div class="editor-header">
            <div class="editor-title">
              <span class="mono">{{ currentPath }}</span>
              <UiTag v-if="currentFile?.exists === false" size="sm" variant="warn">保存后创建</UiTag>
            </div>
            <div class="editor-actions">
              <UiButton icon="RotateCcw" :disabled="saving || loadingContent" @click="loadFile">重置</UiButton>
              <UiButton variant="primary" icon="Save" :loading="saving" @click="save">保存</UiButton>
            </div>
          </div>

          <p v-if="loadError" class="error">{{ loadError }}</p>
          <p v-if="saveError" class="error save-error">{{ saveError }}</p>

          <UiLoading v-if="loadingContent" />
          <UiCard v-else padding="none" shadow="md" class="editor-card">
            <textarea
              v-model="content"
              class="yaml-editor"
              spellcheck="false"
              autocomplete="off"
            />
          </UiCard>
        </template>
      </div>
    </div>
  </div>
</template>

<script setup lang="ts">
import { computed, ref } from 'vue'
import UiPageHeader from '../components/ui/UiPageHeader.vue'
import UiButton from '../components/ui/UiButton.vue'
import UiCard from '../components/ui/UiCard.vue'
import UiTag from '../components/ui/UiTag.vue'
import UiIcon from '../components/ui/UiIcon.vue'
import UiLoading from '../components/ui/UiLoading.vue'
import UiEmpty from '../components/ui/UiEmpty.vue'
import {
  listLlmAbout,
  fetchLlmAboutFile,
  saveLlmAboutFile,
  createLlmAboutGroup,
} from '../api/llmAbout'
import { toast } from '../toast'

interface AboutKind {
  kind: string
  filename: string
  label: string
  description: string
}

interface AboutFile {
  scope: string
  kind: string
  filename: string
  label: string
  path: string
  exists: boolean
}

interface AboutScope {
  scope: string
  label: string
  global: boolean
  path: string
  files: AboutFile[]
  existing_files: number
  total_files: number
}

const basePath = ref('')
const scopes = ref<AboutScope[]>([])
const kinds = ref<AboutKind[]>([])
const listing = ref(false)
const listError = ref<string | null>(null)

const selectedScope = ref('')
const selectedKind = ref('vocab')
const loadingContent = ref(false)
const loadError = ref<string | null>(null)
const saveError = ref<string | null>(null)
const saving = ref(false)
const content = ref('')
const originalContent = ref('')

const currentScope = computed(() => scopes.value.find(scope => scope.scope === selectedScope.value) || null)
const currentFile = computed(() => currentScope.value?.files.find(file => file.kind === selectedKind.value) || null)
const currentPath = computed(() => currentFile.value?.path || '')
const dirty = computed(() => content.value !== originalContent.value)

async function loadList() {
  listing.value = true
  listError.value = null
  try {
    const data = await listLlmAbout()
    basePath.value = data.base_path || ''
    scopes.value = data.scopes || []
    kinds.value = data.kinds || []
    if (!selectedScope.value && scopes.value.length) {
      selectedScope.value = scopes.value[0].scope
    }
    if (!selectedKind.value && kinds.value.length) {
      selectedKind.value = kinds.value[0].kind
    }
    if (selectedScope.value) await loadFile()
  } catch (e: unknown) {
    listError.value = (e as Error).message
  } finally {
    listing.value = false
  }
}

async function selectScope(scope: string) {
  if (scope === selectedScope.value) return
  if (dirty.value && !confirm('当前文件有未保存的修改，切换后将丢失。是否继续？')) return
  selectedScope.value = scope
  await loadFile()
}

async function selectKind(kind: string) {
  if (kind === selectedKind.value) return
  if (dirty.value && !confirm('当前文件有未保存的修改，切换后将丢失。是否继续？')) return
  selectedKind.value = kind
  await loadFile()
}

async function loadFile() {
  if (!selectedScope.value || !selectedKind.value) return
  loadingContent.value = true
  loadError.value = null
  saveError.value = null
  try {
    const data = await fetchLlmAboutFile(selectedScope.value, selectedKind.value)
    content.value = data.content || ''
    originalContent.value = data.content || ''
    if (currentFile.value) currentFile.value.exists = !data.missing
  } catch (e: unknown) {
    loadError.value = (e as Error).message
  } finally {
    loadingContent.value = false
  }
}

async function save() {
  if (!selectedScope.value || !selectedKind.value) return
  saving.value = true
  saveError.value = null
  try {
    await saveLlmAboutFile(selectedScope.value, selectedKind.value, content.value)
    originalContent.value = content.value
    toast('资料已保存')
    await loadList()
  } catch (e: unknown) {
    saveError.value = (e as Error).message
    toast('保存失败', 'error')
  } finally {
    saving.value = false
  }
}

async function startCreateGroup() {
  const raw = prompt('群号（5-12 位数字）')
  if (!raw) return
  const groupId = raw.trim()
  if (!/^\d{5,12}$/.test(groupId)) {
    toast('群号格式不合法', 'error')
    return
  }
  if (scopes.value.some(scope => scope.scope === groupId)) {
    toast('该群资料已存在', 'error')
    selectedScope.value = groupId
    await loadFile()
    return
  }
  try {
    await createLlmAboutGroup(groupId, true)
    toast('群资料已创建')
    selectedScope.value = groupId
    await loadList()
  } catch (e: unknown) {
    toast((e as Error).message, 'error')
  }
}

loadList()
</script>

<style scoped>
.llm-about-view {
  display: flex;
  flex-direction: column;
  flex: 1;
  min-height: 0;
}

.error {
  color: var(--qq-danger);
}

.save-error {
  margin-bottom: 8px;
  font-size: 13px;
}

.hint {
  display: inline-flex;
  align-items: center;
  gap: 6px;
  color: var(--qq-text-muted);
  font-size: 12px;
}

.split {
  display: flex;
  gap: var(--qq-gap-md);
  flex: 1;
  min-height: 0;
}

.scope-card {
  width: 300px;
  flex-shrink: 0;
  overflow-y: auto;
  max-height: calc(100vh - 180px);
}

.scope-list {
  list-style: none;
  margin: 0;
  padding: 0;
}

.scope-item {
  padding: var(--qq-gap-sm) var(--qq-gap-md);
  border-bottom: 1px solid var(--qq-border);
  cursor: pointer;
  transition: background var(--qq-transition-fast);
}

.scope-item:last-child {
  border-bottom: none;
}

.scope-item:hover,
.scope-item.active {
  background: var(--qq-surface-elevated);
}

.scope-item.active {
  box-shadow: inset 3px 0 0 var(--qq-accent);
}

.scope-title {
  display: flex;
  align-items: center;
  gap: var(--qq-gap-xs);
  margin-bottom: 3px;
  color: var(--qq-text);
  font-size: 14px;
  font-weight: 500;
}

.scope-meta {
  color: var(--qq-text-muted);
  font-size: 12px;
}

.editor-col {
  display: flex;
  flex-direction: column;
  flex: 1;
  min-width: 0;
  gap: var(--qq-gap-sm);
}

.kind-tabs {
  display: flex;
  gap: var(--qq-gap-xs);
  border-bottom: 1px solid var(--qq-border);
  flex-wrap: wrap;
}

.kind-tab {
  display: flex;
  flex-direction: column;
  align-items: flex-start;
  gap: 2px;
  padding: 8px 14px;
  background: transparent;
  border: 1px solid transparent;
  border-bottom: none;
  border-top-left-radius: var(--qq-radius-sm);
  border-top-right-radius: var(--qq-radius-sm);
  color: var(--qq-text-muted);
  cursor: pointer;
  font-size: 13px;
  margin-bottom: -1px;
  transition: background var(--qq-transition-fast), color var(--qq-transition-fast), border-color var(--qq-transition-fast);
}

.kind-tab:hover,
.kind-tab.active {
  color: var(--qq-text);
  background: var(--qq-surface-elevated);
}

.kind-tab.active {
  border-color: var(--qq-border);
  border-bottom-color: var(--qq-surface-elevated);
}

.kind-label {
  font-weight: 500;
}

.kind-file,
.mono {
  font-family: var(--qq-font-mono);
}

.kind-file {
  font-size: 11px;
  color: var(--qq-text-muted);
}

.hint-card {
  flex: 1;
  display: flex;
  align-items: center;
  justify-content: center;
}

.editor-header {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: var(--qq-gap-md);
  flex-wrap: wrap;
}

.editor-title {
  display: flex;
  align-items: center;
  gap: var(--qq-gap-sm);
  color: var(--qq-text);
  font-size: 14px;
}

.editor-actions {
  display: flex;
  gap: var(--qq-gap-sm);
}

.editor-card {
  flex: 1;
  overflow: hidden;
  display: flex;
  flex-direction: column;
  min-height: 400px;
}

.yaml-editor {
  flex: 1;
  width: 100%;
  background: var(--qq-surface-strong);
  color: var(--qq-text);
  font-family: var(--qq-font-mono);
  font-size: 13px;
  line-height: 1.7;
  padding: var(--qq-gap-md);
  resize: none;
  outline: none;
  border: none;
}

.yaml-editor:focus {
  box-shadow: inset 0 0 0 1px var(--qq-accent);
}

@media (max-width: 900px) {
  .split {
    flex-direction: column;
  }

  .scope-card {
    width: 100%;
    max-height: 240px;
  }
}
</style>
