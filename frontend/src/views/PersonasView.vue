<template>
  <div class="personas-view">
    <UiPageHeader title="人格管理"><template #actions><UiButton icon="RefreshCw" :disabled="listing" @click="loadList">刷新</UiButton><UiButton variant="primary" icon="Plus" @click="startCreate">新建</UiButton></template></UiPageHeader>
    <p v-if="listError" class="error">{{ listError }}</p>

    <div class="split">
      <nav class="list-panel">
        <UiLoading v-if="listing && !personas.length" />
        <UiEmpty v-else-if="!personas.length" icon="Users" title="暂无人格文件" />
        <div v-else class="list-scroll">
          <button v-for="p in personas" :key="p.name" class="list-item qq-selectable" :class="{ active: p.name === selectedName }" @click="selectPersona(p.name)">
            <div class="list-item-head"><span class="display-name">{{ p.display_name || p.name }}</span><UiTag v-if="p.protected" size="sm" variant="info">共享</UiTag></div>
            <div class="list-item-meta"><span class="mono">{{ p.name }}.toml</span></div>
          </button>
        </div>
      </nav>

      <div class="editor-col">
        <div v-if="!selectedName" class="hint-panel"><UiEmpty icon="FileText" title="从左侧选择一个人格开始编辑" /></div>
        <template v-else>
          <div class="editor-bar">
            <div class="editor-bar-title"><span class="mono">{{ selectedName }}.toml</span><UiTag v-if="isCreating" size="sm" variant="success">待创建</UiTag><UiTag v-else-if="isProtected" size="sm" variant="info">不可删除</UiTag></div>
            <div class="editor-bar-actions">
              <UiButton v-if="!isCreating && !isProtected" variant="danger" icon="Trash2" :disabled="saving" @click="onDelete">删除</UiButton>
              <UiButton variant="primary" icon="Save" :loading="saving" :disabled="!content" @click="onSave">{{ isCreating ? '创建' : '保存' }}</UiButton>
            </div>
          </div>
          <p v-if="loadError" class="error">{{ loadError }}</p><p v-if="saveError" class="error">{{ saveError }}</p>
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
import { computed, ref } from 'vue'
import UiPageHeader from '../components/ui/UiPageHeader.vue'
import UiButton from '../components/ui/UiButton.vue'
import UiTag from '../components/ui/UiTag.vue'
import UiLoading from '../components/ui/UiLoading.vue'
import UiEmpty from '../components/ui/UiEmpty.vue'
import { listPersonas, fetchPersona, updatePersona, createPersona, deletePersona } from '../api/personas'
import { toast } from '../toast'

const personas = ref<any[]>([]); const listing = ref(false); const listError = ref<string | null>(null)
const selectedName = ref(''); const isCreating = ref(false); const content = ref('')
const loadingContent = ref(false); const loadError = ref<string | null>(null); const saveError = ref<string | null>(null); const saving = ref(false)
const isProtected = computed(() => { const p = personas.value.find(x => x.name === selectedName.value); return p?.protected === true })

async function loadList() { listing.value = true; listError.value = null; try { const data = await listPersonas(); personas.value = data.personas || [] } catch (e: unknown) { listError.value = (e as Error).message } finally { listing.value = false } }
async function selectPersona(name: string) { if (name === '__new__') return; if (isCreating.value && content.value) { if (!confirm('未保存的内容将丢失。是否继续？')) return } selectedName.value = name; isCreating.value = false; loadingContent.value = true; loadError.value = null; saveError.value = null; try { content.value = (await fetchPersona(name)).content } catch (e: unknown) { loadError.value = (e as Error).message } finally { loadingContent.value = false } }
function startCreate() { const raw = prompt('文件名（[A-Za-z0-9_]开头，不带 .toml）'); if (!raw) return; const name = raw.trim(); if (!/^[A-Za-z0-9_][A-Za-z0-9_\-]{0,63}$/.test(name)) { toast('文件名不合法', 'error'); return } if (personas.value.some(p => p.name === name)) { toast('同名已存在', 'error'); return } selectedName.value = name; isCreating.value = true; loadError.value = null; saveError.value = null; content.value = `id = "${name}"\ndisplay_name = "${name}"\n\nsystem_prompt = """\n\n"""\n\nstyle_prompt = """\n\n"""\n` }
async function onSave() { saving.value = true; saveError.value = null; try { if (isCreating.value) { await createPersona(selectedName.value, content.value); toast('已创建'); isCreating.value = false } else { await updatePersona(selectedName.value, content.value); toast('已保存') }; await loadList() } catch (e: unknown) { saveError.value = (e as Error).message; toast('保存失败', 'error') } finally { saving.value = false } }
async function onDelete() { if (!confirm(`确定删除 ${selectedName.value}.toml？`)) return; try { await deletePersona(selectedName.value); toast('已删除'); selectedName.value = ''; content.value = ''; await loadList() } catch (e: unknown) { toast((e as Error).message, 'error') } }
loadList()
</script>

<style scoped>
.personas-view { display: flex; flex-direction: column; flex: 1; min-height: 0; overflow: hidden; }
.error { color: var(--qq-danger); font-size: var(--qq-text-sm); }
.split { display: flex; gap: var(--qq-gap-md); flex: 1; min-height: 0; }

.list-panel { width: 260px; flex-shrink: 0; background: var(--qq-surface); border-radius: var(--qq-radius-card); box-shadow: var(--qq-shadow-card); overflow: hidden; display: flex; flex-direction: column; }
.list-scroll { overflow-y: auto; flex: 1; }
.list-item { display: block; width: 100%; text-align: left; padding: var(--qq-gap-sm) var(--qq-gap-md); border: none; background: transparent; cursor: pointer; font-family: var(--qq-font-base); transition: background var(--qq-transition-fast); }
.list-item-head { display: flex; align-items: center; gap: var(--qq-gap-xs); margin-bottom: 2px; }
.display-name { font-size: var(--qq-text-base); font-weight: 500; color: var(--qq-text); }
.list-item-meta { font-size: var(--qq-text-xs); color: var(--qq-text-muted); }
.mono { font-family: var(--qq-font-mono); }

.editor-col { display: flex; flex-direction: column; flex: 1; min-width: 0; min-height: 0; gap: var(--qq-gap-sm); }
.hint-panel { flex: 1; display: flex; align-items: center; justify-content: center; background: var(--qq-surface); border-radius: var(--qq-radius-card); box-shadow: var(--qq-shadow-card); }
.editor-bar { display: flex; align-items: center; justify-content: space-between; gap: var(--qq-gap-md); flex-wrap: wrap; }
.editor-bar-title { display: flex; align-items: center; gap: var(--qq-gap-sm); color: var(--qq-text); font-size: var(--qq-text-base); }
.editor-bar-actions { display: flex; gap: var(--qq-gap-sm); }
.editor-wrap { flex: 1; min-height: 0; border-radius: var(--qq-radius-card); overflow: hidden; box-shadow: var(--qq-shadow-card); }
.toml-editor { display: block; width: 100%; height: 100%; min-height: 300px; background: var(--qq-surface); color: var(--qq-text); font-family: var(--qq-font-mono); font-size: var(--qq-text-sm); line-height: 1.7; padding: var(--qq-gap-md); resize: none; outline: none; border: none; }
.toml-editor:focus { box-shadow: inset 0 0 0 1px var(--qq-primary); }

@media (max-width: 900px) { .split { flex-direction: column; } .list-panel { width: 100%; max-height: 200px; } }
</style>
