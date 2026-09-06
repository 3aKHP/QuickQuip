<template>
  <div class="llm-about-view page-view-fill">
    <UiPageHeader title="资料"><template #actions><span class="hint"><UiIcon name="Info" :size="14" />保存后执行 /llm reload 或重启 bot 生效</span><span v-if="basePath" class="hint mono">{{ basePath }}</span><UiButton icon="RefreshCw" :disabled="listing" @click="loadList">刷新</UiButton><UiButton variant="primary" icon="Plus" @click="startCreateGroup">新建群资料</UiButton></template></UiPageHeader>
    <p v-if="listError" class="error">{{ listError }}</p>

    <div class="split">
      <nav class="list-panel">
        <UiLoading v-if="listing && !scopes.length" />
        <UiEmpty v-else-if="!scopes.length" icon="BookUser" title="暂无资料文件" />
        <div v-else class="list-scroll">
          <button v-for="scope in scopes" :key="scope.scope" class="list-item qq-selectable" :class="{ active: scope.scope === selectedScope }" @click="selectScope(scope.scope)">
            <div class="list-item-head"><span>{{ scope.label }}</span><UiTag v-if="scope.global" size="sm" variant="info">全局</UiTag><UiTag v-if="scope.existing_files < scope.total_files" size="sm" variant="warn">缺失</UiTag></div>
            <div class="list-item-meta"><span class="mono">{{ scope.path }}</span><span>{{ scope.existing_files }}/{{ scope.total_files }}</span></div>
          </button>
        </div>
      </nav>

      <div class="editor-col">
        <UiTabs
          v-if="selectedScope"
          :model-value="selectedKind"
          :tabs="kindTabs"
          class="kind-tabs"
          @change="selectKind"
        />
        <div v-if="!selectedScope" class="hint-panel"><UiEmpty icon="BookUser" title="从左侧选择全局或群级资料" /></div>
        <template v-else>
          <div class="editor-bar">
            <div class="editor-bar-title"><span class="mono">{{ currentPath }}</span><UiTag v-if="currentFile?.exists === false" size="sm" variant="warn">保存后创建</UiTag></div>
            <div class="editor-bar-actions"><UiButton icon="RefreshCw" :disabled="saving || loadingContent" @click="loadFile">重置</UiButton><UiButton variant="primary" icon="Save" :loading="saving" @click="save">保存</UiButton></div>
          </div>
          <p v-if="loadError" class="error">{{ loadError }}</p><p v-if="saveError" class="error">{{ saveError }}</p>
          <UiLoading v-if="loadingContent" />
          <div v-else class="editor-wrap">
            <textarea v-model="content" class="yaml-editor" spellcheck="false" autocomplete="off" />
          </div>
        </template>
      </div>
    </div>
  </div>
</template>

<script setup lang="ts">
import { computed, ref } from 'vue'
import UiPageHeader from '../components/ui/UiPageHeader.vue'
import UiButton from '../components/ui/UiButton.vue'
import UiTag from '../components/ui/UiTag.vue'
import UiIcon from '../components/ui/UiIcon.vue'
import UiLoading from '../components/ui/UiLoading.vue'
import UiEmpty from '../components/ui/UiEmpty.vue'
import UiTabs from '../components/ui/UiTabs.vue'
import { listLlmAbout, fetchLlmAboutFile, saveLlmAboutFile, createLlmAboutGroup } from '../api/llmAbout'
import { toast } from '../toast'

interface AboutKind { kind: string; filename: string; label: string; description: string }
interface AboutFile { scope: string; kind: string; filename: string; label: string; path: string; exists: boolean }
interface AboutScope { scope: string; label: string; global: boolean; path: string; files: AboutFile[]; existing_files: number; total_files: number }

const basePath = ref(''); const scopes = ref<AboutScope[]>([]); const kinds = ref<AboutKind[]>([]); const listing = ref(false); const listError = ref<string | null>(null)
const selectedScope = ref(''); const selectedKind = ref('vocab'); const loadingContent = ref(false); const loadError = ref<string | null>(null); const saveError = ref<string | null>(null); const saving = ref(false); const content = ref(''); const originalContent = ref('')
const currentScope = computed(() => scopes.value.find(s => s.scope === selectedScope.value) || null)
const kindTabs = computed(() => kinds.value.map((k) => ({ key: k.kind, label: k.label, sub: k.filename })))
const currentFile = computed(() => currentScope.value?.files.find(f => f.kind === selectedKind.value) || null)
const currentPath = computed(() => currentFile.value?.path || '')
const dirty = computed(() => content.value !== originalContent.value)

async function loadList() { listing.value = true; listError.value = null; try { const data = await listLlmAbout(); basePath.value = data.base_path || ''; scopes.value = data.scopes || []; kinds.value = data.kinds || []; if (!selectedScope.value && scopes.value.length) selectedScope.value = scopes.value[0].scope; if (!selectedKind.value && kinds.value.length) selectedKind.value = kinds.value[0].kind; if (selectedScope.value) await loadFile() } catch (e: unknown) { listError.value = (e as Error).message } finally { listing.value = false } }
async function selectScope(scope: string) { if (scope === selectedScope.value) return; if (dirty.value && !confirm('未保存的修改将丢失。是否继续？')) return; selectedScope.value = scope; await loadFile() }
async function selectKind(kind: string) { if (kind === selectedKind.value) return; if (dirty.value && !confirm('未保存的修改将丢失。是否继续？')) return; selectedKind.value = kind; await loadFile() }
async function loadFile() { if (!selectedScope.value || !selectedKind.value) return; loadingContent.value = true; loadError.value = null; saveError.value = null; try { const data = await fetchLlmAboutFile(selectedScope.value, selectedKind.value); content.value = data.content || ''; originalContent.value = data.content || ''; if (currentFile.value) currentFile.value.exists = !data.missing } catch (e: unknown) { loadError.value = (e as Error).message } finally { loadingContent.value = false } }
async function save() { if (!selectedScope.value || !selectedKind.value) return; saving.value = true; saveError.value = null; try { await saveLlmAboutFile(selectedScope.value, selectedKind.value, content.value); originalContent.value = content.value; toast('已保存'); await loadList() } catch (e: unknown) { saveError.value = (e as Error).message; toast('保存失败', 'error') } finally { saving.value = false } }
async function startCreateGroup() { const raw = prompt('群号（5-12 位数字）'); if (!raw) return; const gid = raw.trim(); if (!/^\d{5,12}$/.test(gid)) { toast('格式不合法', 'error'); return } if (scopes.value.some(s => s.scope === gid)) { toast('该群资料已存在', 'error'); selectedScope.value = gid; await loadFile(); return } try { await createLlmAboutGroup(gid, true); toast('已创建'); selectedScope.value = gid; await loadList() } catch (e: unknown) { toast((e as Error).message, 'error') } }
loadList()
</script>

<style scoped>
.llm-about-view { display: flex; flex-direction: column; flex: 1 0 auto; min-height: 0; overflow: hidden; }
.error { color: var(--qq-danger); font-size: var(--qq-text-sm); }
.hint { display: inline-flex; align-items: center; gap: 6px; color: var(--qq-text-muted); font-size: var(--qq-text-xs); }
.split { display: flex; gap: var(--qq-gap-md); flex: 1; min-height: 0; }

.list-panel { width: 280px; flex-shrink: 0; background: var(--qq-surface); border-radius: var(--qq-radius-card); box-shadow: var(--qq-shadow-card); overflow: hidden; display: flex; flex-direction: column; }
.list-scroll { overflow-y: auto; flex: 1; }
.list-item { display: block; width: 100%; text-align: left; padding: var(--qq-gap-sm) var(--qq-gap-md); border: none; background: transparent; cursor: pointer; font-family: var(--qq-font-base); transition: background var(--qq-transition-fast); }
.list-item-head { display: flex; align-items: center; gap: var(--qq-gap-xs); margin-bottom: 2px; color: var(--qq-text); font-size: var(--qq-text-base); font-weight: 500; }
.list-item-meta { font-size: var(--qq-text-xs); color: var(--qq-text-muted); display: flex; gap: var(--qq-gap-xs); }
.mono { font-family: var(--qq-font-mono); }

.editor-col { display: flex; flex-direction: column; flex: 1; min-width: 0; min-height: 0; gap: var(--qq-gap-sm); }
.hint-panel { flex: 1; display: flex; align-items: center; justify-content: center; background: var(--qq-surface); border-radius: var(--qq-radius-card); box-shadow: var(--qq-shadow-card); }

.kind-tabs { align-self: flex-start; max-width: 100%; }

.editor-bar { display: flex; align-items: center; justify-content: space-between; gap: var(--qq-gap-md); flex-wrap: wrap; }
.editor-bar-title { display: flex; align-items: center; gap: var(--qq-gap-sm); color: var(--qq-text); font-size: var(--qq-text-base); }
.editor-bar-actions { display: flex; gap: var(--qq-gap-sm); }
.editor-wrap { flex: 1; min-height: 0; border-radius: var(--qq-radius-card); overflow: hidden; box-shadow: var(--qq-shadow-card); }
.yaml-editor { display: block; width: 100%; height: 100%; min-height: 300px; background: var(--qq-surface); color: var(--qq-text); font-family: var(--qq-font-mono); font-size: var(--qq-text-sm); line-height: 1.7; padding: var(--qq-gap-md); resize: none; outline: none; border: none; }
.yaml-editor:focus { box-shadow: inset 0 0 0 1px var(--qq-primary); }

@media (max-width: 900px) { .split { flex-direction: column; } .list-panel { width: 100%; max-height: 200px; } }
</style>
