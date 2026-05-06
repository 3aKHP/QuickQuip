<template>
  <div class="config-view">
    <UiPageHeader title="配置">
      <template #actions>
        <span v-if="current && current.missing" class="warn">
          <UiIcon name="AlertTriangle" :size="14" />
          {{ currentFilename }} 不存在，保存后将创建
        </span>
        <span class="hint">
          <UiIcon name="Info" :size="14" />
          保存后需重启 bot 才会生效
        </span>
        <UiButton icon="RotateCcw" :disabled="saving" @click="load(currentKey)">重置</UiButton>
        <UiButton variant="primary" :loading="saving" icon="Save" @click="save">保存</UiButton>
      </template>
    </UiPageHeader>

    <p v-if="listError" class="error">{{ listError }}</p>

    <div v-if="configs.length" class="tabs">
      <button
        v-for="c in configs"
        :key="c.key"
        class="tab"
        :class="{ active: c.key === currentKey }"
        @click="switchTo(c.key)"
      >
        <span class="tab-label">{{ c.label }}</span>
        <span class="tab-file">{{ c.filename }}</span>
      </button>
    </div>

    <p v-if="loadError" class="error">{{ loadError }}</p>
    <p v-if="saveError" class="error save-error">{{ saveError }}</p>
    <UiLoading v-else-if="!loaded && currentKey" />

    <UiCard v-if="loaded" padding="none" shadow="md" class="editor-card">
      <textarea
        v-model="content"
        class="toml-editor"
        spellcheck="false"
        autocomplete="off"
      />
    </UiCard>
  </div>
</template>

<script setup lang="ts">
import { computed, onMounted, ref } from 'vue'
import UiPageHeader from '../components/ui/UiPageHeader.vue'
import UiButton from '../components/ui/UiButton.vue'
import UiIcon from '../components/ui/UiIcon.vue'
import UiLoading from '../components/ui/UiLoading.vue'
import UiCard from '../components/ui/UiCard.vue'
import { listConfigs, fetchConfig, saveConfig } from '../api/config'
import { toast } from '../toast'

const configs = ref<any[]>([])
const listError = ref<string | null>(null)
const currentKey = ref('')
const loaded = ref(false)
const loadError = ref<string | null>(null)
const saveError = ref<string | null>(null)
const saving = ref(false)
const content = ref('')
const originalContent = ref('')

const current = computed(() => configs.value.find(c => c.key === currentKey.value) || null)
const currentFilename = computed(() => current.value?.filename || '')
const dirty = computed(() => loaded.value && content.value !== originalContent.value)

onMounted(() => loadList())

async function loadList() {
  listError.value = null
  try {
    const d = await listConfigs()
    configs.value = d.configs || []
    if (configs.value.length && !currentKey.value) {
      await load(configs.value[0].key)
    }
  } catch (e: unknown) {
    listError.value = (e as Error).message
  }
}

async function switchTo(key: string) {
  if (key === currentKey.value) return
  if (dirty.value && !confirm('当前文件有未保存的修改，切换后将丢失。是否继续？')) return
  await load(key)
}

async function load(key: string) {
  currentKey.value = key
  loaded.value = false
  loadError.value = null
  saveError.value = null
  try {
    const d = await fetchConfig(key)
    content.value = d.content
    originalContent.value = d.content
    const entry = configs.value.find(c => c.key === key)
    if (entry) entry.missing = d.missing || false
    loaded.value = true
  } catch (e: unknown) {
    loadError.value = (e as Error).message
  }
}

async function save() {
  if (!currentKey.value) return
  saving.value = true
  saveError.value = null
  try {
    await saveConfig(currentKey.value, content.value)
    originalContent.value = content.value
    const entry = configs.value.find(c => c.key === currentKey.value)
    if (entry) entry.missing = false
    toast('配置已保存')
  } catch (e: unknown) {
    saveError.value = (e as Error).message
    toast('保存失败', 'error')
  } finally {
    saving.value = false
  }
}
</script>

<style scoped>
.config-view {
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

.warn {
  display: inline-flex;
  align-items: center;
  gap: 6px;
  color: var(--qq-warn);
  font-size: var(--qq-text-sm);
}

.hint {
  display: inline-flex;
  align-items: center;
  gap: 6px;
  color: var(--qq-text-muted);
  font-size: var(--qq-text-xs);
}

.tabs {
  display: flex;
  gap: var(--qq-gap-xs);
  margin-bottom: var(--qq-gap-md);
  border-bottom: 1px solid var(--qq-border);
  flex-wrap: wrap;
}

.tab {
  display: flex;
  flex-direction: column;
  align-items: flex-start;
  gap: 2px;
  padding: var(--qq-gap-sm) var(--qq-gap-md);
  background: transparent;
  border: 1px solid transparent;
  border-bottom: none;
  border-top-left-radius: var(--qq-radius-sm);
  border-top-right-radius: var(--qq-radius-sm);
  color: var(--qq-text-muted);
  cursor: pointer;
  font-size: var(--qq-text-sm);
  margin-bottom: -1px;
  transition: background var(--qq-transition-fast), color var(--qq-transition-fast), border-color var(--qq-transition-fast);
}

.tab:hover {
  color: var(--qq-text);
  background: var(--qq-surface);
}

.tab.active {
  color: var(--qq-text);
  background: var(--qq-surface-elevated);
  border-color: var(--qq-border);
  border-bottom-color: var(--qq-surface-elevated);
}

.tab-label {
  font-weight: 500;
}

.tab-file {
  font-family: var(--qq-font-mono);
  font-size: var(--qq-text-xs);
  color: var(--qq-text-muted);
}

.editor-card {
  flex: 1;
  overflow: hidden;
  display: flex;
  flex-direction: column;
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
</style>
