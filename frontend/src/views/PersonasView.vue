<template>
  <div class="personas-view">
    <UiPageHeader title="人格管理" subtitle="管理 config/personas/*.toml 人格档案（支持 Persona v3 结构化设定），按群在「群 LLM 设置」选用">
      <template #subtitle>
        <UiInfoTip text="人格在加载 LLM 配置时读入，保存后可点击右上角「重载人格」或在群内执行 /llm reload 生效。" />
      </template>
      <template #actions>
        <router-link to="/llm-config?section=conversation" custom v-slot="{ navigate }">
          <UiButton variant="ghost" icon="SlidersHorizontal" @click="navigate">默认人格与对话设置</UiButton>
        </router-link>
        <UiButton variant="ghost" icon="RotateCw" :loading="reloading" :disabled="reloading" @click="onReloadPersonas">重载人格</UiButton>
        <UiButton icon="RefreshCw" :disabled="listing" @click="onRefresh">刷新</UiButton>
        <UiButton variant="primary" icon="Plus" @click="startCreate">新建</UiButton>
      </template>
    </UiPageHeader>
    <p v-if="listError" class="error">{{ listError }}</p>

    <div class="split">
      <nav class="list-panel">
        <UiLoading v-if="listing && !personas.length" />
        <UiEmpty v-else-if="!personas.length" icon="Users" title="暂无人格文件" />
        <div v-else class="list-scroll">
          <button
            v-for="p in personas"
            :key="p.name"
            class="list-item qq-selectable"
            :class="{ active: p.name === selectedName }"
            @click="selectPersona(p.name)"
          >
            <div class="list-item-head">
              <span class="display-name">{{ p.display_name || p.name }}</span>
              <UiTag v-if="p.protected" size="sm" variant="info">共享</UiTag>
              <UiInfoTip
                v-if="p.protected"
                text="_shared.toml 不是可选人格，而是按作用域（group / private）自动注入所有人格的共享行为与风格准则（Persona v3 注入为 shared_host_rules / shared_style_rules），因此不可删除。"
              />
              <UiTag v-else-if="scopeBadge(p.scope)" size="sm" :variant="scopeBadge(p.scope)!.variant">{{ scopeBadge(p.scope)!.label }}</UiTag>
            </div>
            <div class="list-item-meta"><span class="mono">{{ p.name }}.toml</span></div>
          </button>
        </div>
      </nav>

      <div class="editor-col">
        <div v-if="!selectedName" class="hint-panel">
          <UiEmpty icon="FileText" title="选择一个人格开始编辑" description="从列表中选择一个人格查看与编辑其 TOML 内容。" />
        </div>
        <template v-else>
          <div class="editor-bar">
            <div class="editor-bar-title">
              <span class="mono">{{ selectedName }}.toml</span>
              <UiTag v-if="isCreating" size="sm" variant="success">待创建</UiTag>
              <UiTag v-else-if="dirty" size="sm" variant="warn">未保存</UiTag>
              <UiTag v-if="isProtected" size="sm" variant="info">不可删除</UiTag>
              <UiInfoTip v-if="isProtected" text="受保护的保留文件名（当前仅 _shared），后端拒绝删除与同名创建。" />
            </div>
            <div class="editor-bar-actions">
              <UiButton v-if="!isCreating && !isProtected" variant="danger" icon="Trash2" :disabled="saving" @click="onDelete">删除</UiButton>
              <UiButton variant="primary" icon="Save" :loading="saving" :disabled="!content || loadingContent || (!dirty && !isCreating)" @click="onSave">
                {{ isCreating ? '创建' : '保存' }}
              </UiButton>
            </div>
          </div>
          <p v-if="loadError" class="error">{{ loadError }}</p>
          <p v-if="saveError" class="error">{{ saveError }}</p>
          <UiLoading v-if="loadingContent" />
          <div v-else class="editor-wrap">
            <textarea v-model="content" class="toml-editor" spellcheck="false" autocomplete="off" />
          </div>
        </template>
      </div>
    </div>
  </div>
</template>

<script setup lang="ts">
import { computed, onMounted, onUnmounted, ref } from 'vue'
import { onBeforeRouteLeave } from 'vue-router'
import UiPageHeader from '../components/ui/UiPageHeader.vue'
import UiButton from '../components/ui/UiButton.vue'
import UiTag from '../components/ui/UiTag.vue'
import UiLoading from '../components/ui/UiLoading.vue'
import UiEmpty from '../components/ui/UiEmpty.vue'
import UiInfoTip from '../components/ui/UiInfoTip.vue'
import { listPersonas, fetchPersona, updatePersona, createPersona, deletePersona } from '../api/personas'
import { reloadPersonas } from '../api/llmRuntime'
import { toast } from '../toast'

interface PersonaSummary {
  name: string
  display_name?: string | null
  id?: string | null
  source?: string | null
  scope?: string[] | string | null
  size?: number
  mtime?: number
  protected?: boolean
}

const personas = ref<PersonaSummary[]>([])
const listing = ref(false)
const listError = ref<string | null>(null)
const selectedName = ref('')
const isCreating = ref(false)
const content = ref('')
const originalContent = ref('')
const loadingContent = ref(false)
const loadError = ref<string | null>(null)
const saveError = ref<string | null>(null)
const saving = ref(false)
const reloading = ref(false)
let requestSeq = 0

const dirty = computed(() => Boolean(selectedName.value) && (isCreating.value || content.value !== originalContent.value))
const isProtected = computed(() => {
  const p = personas.value.find(x => x.name === selectedName.value)
  return p?.protected === true
})

function scopeBadge(rawScope: string[] | string | null | undefined): { label: string; variant?: 'info' | 'warn' } | null {
  const scopes = (Array.isArray(rawScope) ? rawScope : typeof rawScope === 'string' ? [rawScope] : [])
    .map(item => String(item).trim().toLowerCase())
    .filter(item => item === 'group' || item === 'private')
  const set = new Set(scopes)
  if (set.size === 1 && set.has('group')) return { label: '群聊', variant: 'info' }
  if (set.size === 1 && set.has('private')) return { label: '私聊', variant: 'warn' }
  return { label: '通用' }
}

function confirmDiscard(): boolean {
  if (!dirty.value) return true
  return confirm('当前人格有未保存修改，切换后将丢失。是否继续？')
}

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

async function onRefresh() {
  if (!confirmDiscard()) return
  await loadList()
  if (selectedName.value && !isCreating.value) {
    if (personas.value.some(p => p.name === selectedName.value)) {
      await fetchPersonaContent(selectedName.value)
    } else {
      selectedName.value = ''
      content.value = ''
      originalContent.value = ''
    }
  }
}

async function fetchPersonaContent(name: string) {
  const seq = ++requestSeq
  loadingContent.value = true
  loadError.value = null
  saveError.value = null
  try {
    const data = await fetchPersona(name)
    if (seq !== requestSeq || selectedName.value !== name) return
    content.value = data.content || ''
    originalContent.value = data.content || ''
  } catch (e: unknown) {
    if (seq !== requestSeq || selectedName.value !== name) return
    loadError.value = (e as Error).message
  } finally {
    if (seq === requestSeq) loadingContent.value = false
  }
}

async function selectPersona(name: string) {
  if (name === '__new__') return
  if (name === selectedName.value && !isCreating.value) return
  if (!confirmDiscard()) return
  selectedName.value = name
  isCreating.value = false
  await fetchPersonaContent(name)
}

function newPersonaTemplate(name: string): string {
  return [
    `id = "${name}"`,
    `display_name = "${name}"`,
    'scope = ["group"]',
    'schema_version = 3',
    '',
    '[identity]',
    `name = "${name}"`,
    'role = ""',
    'scenario = ""',
    'self_reference = "第一人称「我」"',
    'addressing = "直接称呼对方「你」或群昵称"',
    '',
    '[voice]',
    'register = ""',
    'rhythm = ""',
    '',
    '[topology]',
    'baseline_stance = ""',
    'taboos = []',
    '',
  ].join('\n')
}

function startCreate() {
  if (!confirmDiscard()) return
  const raw = prompt('文件名（[A-Za-z0-9_]开头，不带 .toml）')
  if (!raw) return
  const name = raw.trim()
  if (!/^[A-Za-z0-9_][A-Za-z0-9_\-]{0,63}$/.test(name)) {
    toast('文件名不合法', 'error')
    return
  }
  if (personas.value.some(p => p.name === name)) {
    toast('同名已存在', 'error')
    return
  }
  ++requestSeq
  selectedName.value = name
  isCreating.value = true
  loadingContent.value = false
  loadError.value = null
  saveError.value = null
  originalContent.value = ''
  content.value = newPersonaTemplate(name)
}

async function onSave() {
  if (!selectedName.value || !content.value || saving.value || loadingContent.value) return
  const targetName = selectedName.value
  const creating = isCreating.value
  const savedContent = content.value
  saving.value = true
  saveError.value = null
  try {
    if (creating) {
      await createPersona(targetName, savedContent)
      toast('已创建')
      if (selectedName.value === targetName) isCreating.value = false
    } else {
      await updatePersona(targetName, savedContent)
      toast('已保存')
    }
    if (selectedName.value === targetName) originalContent.value = savedContent
    await loadList()
  } catch (e: unknown) {
    saveError.value = (e as Error).message
    toast('保存失败', 'error')
  } finally {
    saving.value = false
  }
}

async function onDelete() {
  if (!selectedName.value || saving.value) return
  if (!confirm(`确定删除 ${selectedName.value}.toml？`)) return
  try {
    await deletePersona(selectedName.value)
    toast('已删除')
    ++requestSeq
    selectedName.value = ''
    isCreating.value = false
    content.value = ''
    originalContent.value = ''
    await loadList()
  } catch (e: unknown) {
    toast((e as Error).message, 'error')
  }
}

async function onReloadPersonas() {
  reloading.value = true
  try {
    await reloadPersonas()
    toast('已提交重载人格任务')
  } catch (e: unknown) {
    toast((e as Error).message || '重载人格失败', 'error')
  } finally {
    reloading.value = false
  }
}

function beforeUnload(event: BeforeUnloadEvent) {
  if (dirty.value) {
    event.preventDefault()
    event.returnValue = ''
  }
}

function onKeydown(event: KeyboardEvent) {
  if ((event.ctrlKey || event.metaKey) && event.key.toLowerCase() === 's') {
    event.preventDefault()
    if (selectedName.value && content.value && !saving.value && !loadingContent.value && (dirty.value || isCreating.value)) {
      void onSave()
    }
  }
}

onBeforeRouteLeave(() => !dirty.value || confirm('当前人格有未保存修改，是否离开？'))
onMounted(() => {
  void loadList()
  window.addEventListener('beforeunload', beforeUnload)
  window.addEventListener('keydown', onKeydown)
})
onUnmounted(() => {
  window.removeEventListener('beforeunload', beforeUnload)
  window.removeEventListener('keydown', onKeydown)
})
</script>

<style scoped>
.personas-view { display: flex; flex-direction: column; }
.error { color: var(--qq-danger); font-size: var(--qq-text-sm); }
.split { display: flex; gap: var(--qq-gap-md); }

.list-panel {
  width: 260px;
  flex-shrink: 0;
  align-self: flex-start;
  position: sticky;
  top: var(--qq-gap-lg);
  max-height: calc(100vh - var(--qq-gap-lg) * 2);
  background: var(--qq-surface);
  border-radius: var(--qq-radius-card);
  box-shadow: var(--qq-shadow-card);
  overflow: hidden;
  display: flex;
  flex-direction: column;
}
.list-scroll { overflow-y: auto; flex: 1; }
.list-item { display: block; width: 100%; text-align: left; padding: var(--qq-gap-sm) var(--qq-gap-md); border: none; background: transparent; cursor: pointer; font-family: var(--qq-font-base); transition: background var(--qq-transition-fast); }
.list-item-head { display: flex; align-items: center; gap: var(--qq-gap-xs); flex-wrap: wrap; margin-bottom: 2px; }
.display-name { font-size: var(--qq-text-base); font-weight: 500; color: var(--qq-text); }
.list-item-meta { font-size: var(--qq-text-xs); color: var(--qq-text-muted); }
.mono { font-family: var(--qq-font-mono); }

.editor-col { display: flex; flex-direction: column; flex: 1; min-width: 0; gap: var(--qq-gap-sm); }
/* 桌面端人格列表可长达数千 px，hint 贴顶对齐，避免垂直居中后被推到首屏视口外 */
.hint-panel { flex: 1; display: flex; align-items: flex-start; justify-content: center; background: var(--qq-surface); border-radius: var(--qq-radius-card); box-shadow: var(--qq-shadow-card); }
.editor-bar { display: flex; align-items: center; justify-content: space-between; gap: var(--qq-gap-md); flex-wrap: wrap; }
.editor-bar-title { display: flex; align-items: center; gap: var(--qq-gap-sm); flex-wrap: wrap; color: var(--qq-text); font-size: var(--qq-text-base); }
.editor-bar-actions { display: flex; gap: var(--qq-gap-sm); }
.editor-wrap { border-radius: var(--qq-radius-card); overflow: hidden; box-shadow: var(--qq-shadow-card); }
.toml-editor { display: block; width: 100%; min-height: 60vh; background: var(--qq-surface); color: var(--qq-text); font-family: var(--qq-font-mono); font-size: var(--qq-text-sm); line-height: 1.7; padding: var(--qq-gap-md); resize: vertical; outline: none; border: none; }
.toml-editor:focus { box-shadow: inset 0 0 0 1px var(--qq-primary); }

@media (max-width: 900px) {
  .split { flex-direction: column; }
  .list-panel { width: 100%; max-height: 220px; position: static; }
  .toml-editor { min-height: 55vh; }
}
</style>
