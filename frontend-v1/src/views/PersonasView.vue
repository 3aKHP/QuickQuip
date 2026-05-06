<template>
  <div class="personas-view">
    <UiPageHeader title="人格管理">
      <template #actions>
        <UiButton icon="RefreshCw" :disabled="listing" @click="loadList">刷新</UiButton>
        <UiButton variant="primary" icon="Plus" @click="startCreate">新建</UiButton>
      </template>
    </UiPageHeader>

    <p v-if="listError" class="error">{{ listError }}</p>

    <div class="split">
      <UiCard padding="none" shadow="sm" class="list-card">
        <UiLoading v-if="listing && !personas.length" />
        <UiEmpty v-else-if="!personas.length" icon="Users" title="暂无人格文件" />
        <ul v-else class="persona-list">
          <li
            v-for="p in personas"
            :key="p.name"
            class="persona-item"
            :class="{ active: p.name === selectedName, creating: p.name === '__new__' }"
            @click="selectPersona(p.name)"
          >
            <div class="persona-title">
              <span class="persona-display">{{ p.display_name || p.name }}</span>
              <UiTag v-if="p.protected" size="sm" variant="info">共享</UiTag>
              <UiTag v-if="p.scope" size="sm">{{ p.scope }}</UiTag>
            </div>
            <div class="persona-meta">
              <span class="mono">{{ p.name }}.toml</span>
              <span v-if="p.source" class="source">· {{ p.source }}</span>
            </div>
          </li>
        </ul>
      </UiCard>

      <div class="editor-col">
        <UiCard v-if="!selectedName" padding="lg" shadow="sm" class="hint-card">
          <UiEmpty icon="FileText" title="从左侧选择一个人格开始编辑" />
        </UiCard>

        <template v-else>
          <div class="editor-header">
            <div class="editor-title">
              <span class="mono">{{ selectedName }}.toml</span>
              <UiTag v-if="isCreating" size="sm" variant="success">待创建</UiTag>
              <UiTag v-else-if="isProtected" size="sm" variant="info">共享（不可删除）</UiTag>
            </div>
            <div class="editor-actions">
              <UiButton
                v-if="!isCreating && !isProtected"
                variant="danger"
                icon="Trash2"
                :disabled="saving"
                @click="onDelete"
              >删除</UiButton>
              <UiButton
                variant="primary"
                icon="Save"
                :loading="saving"
                :disabled="!content || content.length === 0"
                @click="onSave"
              >{{ isCreating ? '创建' : '保存' }}</UiButton>
            </div>
          </div>

          <p v-if="loadError" class="error">{{ loadError }}</p>
          <p v-if="saveError" class="error save-error">{{ saveError }}</p>

          <UiLoading v-if="loadingContent" />
          <UiCard v-else padding="none" shadow="md" class="editor-card">
            <textarea
              v-model="content"
              class="toml-editor"
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
import UiLoading from '../components/ui/UiLoading.vue'
import UiEmpty from '../components/ui/UiEmpty.vue'
import {
  listPersonas,
  fetchPersona,
  updatePersona,
  createPersona,
  deletePersona,
} from '../api/personas'
import { toast } from '../toast'

const personas = ref<any[]>([])
const listing = ref(false)
const listError = ref<string | null>(null)

const selectedName = ref('')
const isCreating = ref(false)
const content = ref('')
const loadingContent = ref(false)
const loadError = ref<string | null>(null)
const saveError = ref<string | null>(null)
const saving = ref(false)

const isProtected = computed(() => {
  const p = personas.value.find(x => x.name === selectedName.value)
  return p?.protected === true
})

async function loadList() {
  listing.value = true
  listError.value = null
  try {
    const data = await listPersonas()
    personas.value = data.personas || []
  } catch (e: unknown) {
    listError.value = (e as Error).message
  } finally {
    listing.value = false
  }
}

async function selectPersona(name: string) {
  if (name === '__new__') return
  if (isCreating.value && content.value) {
    if (!confirm('当前正在创建新人格，未保存的内容将丢失。是否继续？')) return
  }
  selectedName.value = name
  isCreating.value = false
  loadingContent.value = true
  loadError.value = null
  saveError.value = null
  content.value = ''
  try {
    const data = await fetchPersona(name)
    content.value = data.content
  } catch (e: unknown) {
    loadError.value = (e as Error).message
  } finally {
    loadingContent.value = false
  }
}

function startCreate() {
  const raw = prompt('新人格的文件名（[A-Za-z0-9_][A-Za-z0-9_-]{0,63}，不带 .toml）')
  if (!raw) return
  const name = raw.trim()
  if (!/^[A-Za-z0-9_][A-Za-z0-9_\-]{0,63}$/.test(name)) {
    toast('文件名不合法', 'error')
    return
  }
  if (personas.value.some(p => p.name === name)) {
    toast('同名人格已存在', 'error')
    return
  }
  selectedName.value = name
  isCreating.value = true
  loadError.value = null
  saveError.value = null
  content.value = `id = "${name}"\ndisplay_name = "${name}"\n\nsystem_prompt = """\n\n"""\n\nstyle_prompt = """\n\n"""\n`
}

async function onSave() {
  saving.value = true
  saveError.value = null
  try {
    if (isCreating.value) {
      await createPersona(selectedName.value, content.value)
      toast('人格已创建')
      isCreating.value = false
      await loadList()
    } else {
      await updatePersona(selectedName.value, content.value)
      toast('人格已保存')
      await loadList()
    }
  } catch (e: unknown) {
    saveError.value = (e as Error).message
    toast('保存失败', 'error')
  } finally {
    saving.value = false
  }
}

async function onDelete() {
  if (!confirm(`确定要删除人格 ${selectedName.value}.toml？此操作不可撤销。`)) return
  try {
    await deletePersona(selectedName.value)
    toast('人格已删除')
    selectedName.value = ''
    content.value = ''
    await loadList()
  } catch (e: unknown) {
    toast((e as Error).message, 'error')
  }
}

loadList()
</script>

<style scoped>
.personas-view {
  display: flex;
  flex-direction: column;
  flex: 1;
  min-height: 0;
}

.error {
  color: var(--qq-danger);
}

.save-error {
  margin-bottom: var(--qq-gap-sm);
  font-size: var(--qq-text-sm);
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

.persona-list {
  list-style: none;
  margin: 0;
  padding: 0;
}

.persona-item {
  padding: var(--qq-gap-sm) var(--qq-gap-md);
  border-bottom: 1px solid var(--qq-border);
  cursor: pointer;
  transition: background var(--qq-transition-fast);
}

.persona-item:last-child {
  border-bottom: none;
}

.persona-item:hover {
  background: var(--qq-surface-elevated);
}

.persona-item.active {
  background: var(--qq-surface-elevated);
  box-shadow: inset 3px 0 0 var(--qq-accent);
}

.persona-title {
  display: flex;
  align-items: center;
  gap: var(--qq-gap-xs);
  margin-bottom: 3px;
}

.persona-display {
  font-size: var(--qq-text-base);
  font-weight: 500;
  color: var(--qq-text);
}

.persona-meta {
  font-size: var(--qq-text-xs);
  color: var(--qq-text-muted);
  display: flex;
  gap: 4px;
  flex-wrap: wrap;
}

.mono {
  font-family: var(--qq-font-mono);
}

.source {
  font-style: italic;
}

.editor-col {
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
  font-size: var(--qq-text-base);
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

.toml-editor {
  flex: 1;
  width: 100%;
  background: var(--qq-surface-strong);
  color: var(--qq-text);
  font-family: var(--qq-font-mono);
  font-size: var(--qq-text-sm);
  line-height: 1.7;
  padding: var(--qq-gap-md);
  resize: none;
  outline: none;
  border: none;
}

.toml-editor:focus {
  box-shadow: inset 0 0 0 1px var(--qq-accent);
}

@media (max-width: 900px) {
  .split {
    flex-direction: column;
  }
  .list-card {
    width: 100%;
    max-height: 240px;
  }
}
</style>
