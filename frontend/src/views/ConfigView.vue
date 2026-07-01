<template>
  <div class="config-view">
    <UiPageHeader title="配置" subtitle="在线编辑常规 TOML 配置文件，保存后部分自动重载，其余需手动 reload 或重启">
      <template #actions>
        <span v-if="current && current.missing" class="warn">
          <UiIcon name="Info" :size="14" />
          {{ currentFilename }} 不存在，保存后将创建
        </span>
        <span class="hint">
          <UiIcon name="Info" :size="14" />
          保存后会提示具体生效方式
        </span>
        <UiButton icon="RefreshCw" :disabled="saving" @click="load(currentKey)">重置</UiButton>
        <UiButton variant="primary" :loading="saving" icon="Save" @click="save">保存</UiButton>
      </template>
    </UiPageHeader>

    <p v-if="listError" class="error">{{ listError }}</p>

    <div class="config-shell">
      <aside class="config-list">
        <div class="panel-head">
          <span class="panel-title">配置文件</span>
          <span class="panel-count">{{ configs.length }}</span>
        </div>
        <UiLoading v-if="!configs.length && !listError" />
        <button
          v-for="c in configs"
          :key="c.key"
          class="config-item"
          :class="{ active: c.key === currentKey }"
          @click="switchTo(c.key)"
        >
          <span class="config-item__label">{{ c.label }}</span>
          <span class="config-item__file">{{ c.filename }}</span>
          <span v-if="c.missing" class="config-item__flag">缺失</span>
        </button>
      </aside>

      <main class="config-editor">
        <p v-if="loadError" class="error">{{ loadError }}</p>
        <p v-if="saveError" class="error">{{ saveError }}</p>
        <UiLoading v-else-if="!loaded && currentKey" />

        <template v-if="loaded">
          <div class="editor-head">
            <div class="editor-meta">
              <span class="editor-kicker">当前文件</span>
              <h3>{{ currentFilename }}</h3>
            </div>
            <div class="editor-state">
              <span v-if="current && current.missing" class="state-pill state-pill--warn">将创建新文件</span>
              <span v-else-if="dirty" class="state-pill state-pill--info">未保存</span>
              <span v-else class="state-pill state-pill--ok">已同步</span>
            </div>
          </div>
          <textarea v-model="content" class="toml-editor" spellcheck="false" autocomplete="off" />
        </template>

        <div v-else class="empty-editor">
          <UiEmpty icon="Settings" title="从左侧选择一个配置文件开始编辑" />
        </div>
      </main>

      <aside class="config-side">
        <div class="side-card">
          <h4>保存说明</h4>
          <p>配置文件会直接写回仓库内的常规 TOML 文件。敏感词表等高敏文件只在服务器本地维护。</p>
        </div>
        <div class="side-card">
          <h4>常见文件</h4>
          <ul>
            <li>llm.toml</li>
            <li>generation.toml</li>
            <li>chat_rules.toml</li>
            <li>games.toml</li>
            <li>niuniu_text.toml</li>
            <li>niuniu_text_safe.toml</li>
          </ul>
        </div>
      </aside>
    </div>
  </div>
</template>

<script setup lang="ts">
import { computed, onMounted, ref } from 'vue'
import UiPageHeader from '../components/ui/UiPageHeader.vue'
import UiButton from '../components/ui/UiButton.vue'
import UiEmpty from '../components/ui/UiEmpty.vue'
import UiIcon from '../components/ui/UiIcon.vue'
import UiLoading from '../components/ui/UiLoading.vue'
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
    const data = await listConfigs()
    configs.value = data.configs || []
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
    const data = await fetchConfig(key)
    content.value = data.content
    originalContent.value = data.content
    const entry = configs.value.find(c => c.key === key)
    if (entry) entry.missing = data.missing || false
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
    const res = await saveConfig(currentKey.value, content.value)
    originalContent.value = content.value
    const entry = configs.value.find(c => c.key === currentKey.value)
    if (entry) entry.missing = false
    const effect = res?.effect
    if (effect === 'auto_reloading') {
      toast('已保存，正在自动重载（诊断页「最近动作」查看结果）')
    } else if (effect === 'manual_reload') {
      toast('已保存。请到诊断页点「重载 LLM」或群内 /llm reload 生效')
    } else if (effect === 'restart_needed') {
      toast('已保存。此项需重启 bot 生效')
    } else {
      toast('配置已保存')
    }
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
  flex: 1;
  min-height: 0;
  flex-direction: column;
}

.error {
  color: var(--qq-danger);
  font-size: var(--qq-text-sm);
}

.warn,
.hint {
  display: inline-flex;
  align-items: center;
  gap: 6px;
  font-size: var(--qq-text-sm);
}

.warn {
  color: var(--qq-warn);
}

.hint {
  color: var(--qq-text-muted);
}

.config-shell {
  display: grid;
  flex: 1;
  min-height: 0;
  grid-template-columns: 220px minmax(0, 1fr) 180px;
  gap: var(--qq-gap-md);
}

.config-list,
.config-editor,
.config-side {
  min-width: 0;
  min-height: 0;
  background: var(--qq-surface);
  border: 1px solid var(--qq-border);
  border-radius: var(--qq-radius-card);
  box-shadow: var(--qq-shadow-card);
}

.config-list {
  display: flex;
  flex-direction: column;
  overflow-y: auto;
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

.config-item {
  display: flex;
  flex-direction: column;
  gap: 3px;
  width: 100%;
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

.config-item:hover {
  background: var(--qq-surface-hover);
}

.config-item.active {
  background: var(--qq-primary-soft);
  box-shadow: inset 3px 0 0 var(--qq-primary);
}

.config-item__label {
  font-size: var(--qq-text-sm);
  font-weight: 700;
}

.config-item__file,
.config-item__flag {
  color: var(--qq-text-muted);
  font-family: var(--qq-font-mono);
  font-size: var(--qq-text-xs);
}

.config-item__flag {
  color: var(--qq-warn);
}

.config-editor {
  display: flex;
  flex-direction: column;
  gap: var(--qq-gap-xs);
  overflow: hidden;
  padding: var(--qq-gap-sm);
}

.editor-head {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: var(--qq-gap-sm);
  padding: 0 var(--qq-gap-xs);
}

.editor-meta {
  min-width: 0;
  display: flex;
  align-items: baseline;
  gap: var(--qq-gap-sm);
}

.editor-kicker {
  color: var(--qq-primary);
  font-size: var(--qq-text-xs);
  font-weight: 700;
  flex-shrink: 0;
}

.editor-meta h3 {
  margin: 0;
  color: var(--qq-text);
  font-size: var(--qq-text-base);
  line-height: 1.2;
  word-break: break-all;
  font-family: var(--qq-font-mono);
}

.editor-state {
  display: flex;
  gap: var(--qq-gap-xs);
}

.state-pill {
  display: inline-flex;
  align-items: center;
  height: 24px;
  padding: 0 10px;
  border-radius: var(--qq-radius-full);
  font-size: var(--qq-text-xs);
  font-weight: 700;
  white-space: nowrap;
}

.state-pill--warn {
  background: var(--qq-warn-soft);
  color: var(--qq-warn);
}

.state-pill--info {
  background: var(--qq-primary-soft);
  color: var(--qq-primary);
}

.state-pill--ok {
  background: var(--qq-success-soft);
  color: var(--qq-success);
}

.toml-editor {
  flex: 1;
  width: 100%;
  min-height: 360px;
  padding: var(--qq-gap-sm);
  border: 0;
  border-top: 1px solid var(--qq-border);
  background: var(--qq-surface-strong);
  color: var(--qq-text);
  font-family: var(--qq-font-mono);
  font-size: var(--qq-text-sm);
  line-height: 1.7;
  resize: none;
  outline: none;
  tab-size: 2;
}

.toml-editor:focus {
  box-shadow: inset 0 0 0 1px var(--qq-primary);
}

.empty-editor {
  flex: 1;
  display: grid;
  place-items: center;
}

.config-side {
  display: flex;
  flex-direction: column;
  gap: var(--qq-gap-sm);
  padding: var(--qq-gap-md);
}

.side-card {
  padding: var(--qq-gap-sm);
  border-radius: var(--qq-radius-sm);
  background: var(--qq-surface-strong);
}

.side-card h4 {
  margin: 0 0 6px;
  color: var(--qq-text);
  font-size: var(--qq-text-sm);
}

.side-card p,
.side-card li {
  color: var(--qq-text-muted);
  font-size: var(--qq-text-xs);
  line-height: 1.6;
}

.side-card ul {
  margin: 0;
  padding-left: 18px;
}

@media (max-width: 1100px) {
  .config-shell {
    grid-template-columns: 200px minmax(0, 1fr);
  }

  .config-side {
    display: none;
  }
}

@media (max-width: 767px) {
  .config-shell {
    grid-template-columns: 1fr;
    grid-template-rows: auto minmax(360px, 1fr);
  }

  .config-list {
    max-height: 160px;
  }

  .editor-head {
    align-items: flex-start;
    flex-direction: column;
  }
}
</style>
