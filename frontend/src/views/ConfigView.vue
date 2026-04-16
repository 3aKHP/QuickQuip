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

<script>
import UiPageHeader from '../components/ui/UiPageHeader.vue'
import UiButton from '../components/ui/UiButton.vue'
import UiIcon from '../components/ui/UiIcon.vue'
import UiLoading from '../components/ui/UiLoading.vue'
import UiCard from '../components/ui/UiCard.vue'
import { listConfigs, fetchConfig, saveConfig } from '../api/config.js'
import { toast } from '../toast.js'

export default {
  components: { UiPageHeader, UiButton, UiIcon, UiLoading, UiCard },
  data: () => ({
    configs: [],
    listError: null,
    currentKey: '',
    loaded: false,
    loadError: null,
    saveError: null,
    saving: false,
    content: '',
    originalContent: '',
  }),
  computed: {
    current() {
      return this.configs.find(c => c.key === this.currentKey) || null
    },
    currentFilename() {
      return this.current?.filename || ''
    },
    dirty() {
      return this.loaded && this.content !== this.originalContent
    },
  },
  async mounted() {
    await this.loadList()
  },
  methods: {
    async loadList() {
      this.listError = null
      try {
        const d = await listConfigs()
        this.configs = d.configs || []
        if (this.configs.length && !this.currentKey) {
          await this.load(this.configs[0].key)
        }
      } catch (e) {
        this.listError = e.message
      }
    },
    async switchTo(key) {
      if (key === this.currentKey) return
      if (this.dirty && !confirm('当前文件有未保存的修改，切换后将丢失。是否继续？')) return
      await this.load(key)
    },
    async load(key) {
      this.currentKey = key
      this.loaded = false
      this.loadError = null
      this.saveError = null
      try {
        const d = await fetchConfig(key)
        this.content = d.content
        this.originalContent = d.content
        const entry = this.configs.find(c => c.key === key)
        if (entry) entry.missing = d.missing || false
        this.loaded = true
      } catch (e) {
        this.loadError = e.message
      }
    },
    async save() {
      if (!this.currentKey) return
      this.saving = true
      this.saveError = null
      try {
        await saveConfig(this.currentKey, this.content)
        this.originalContent = this.content
        const entry = this.configs.find(c => c.key === this.currentKey)
        if (entry) entry.missing = false
        toast('配置已保存')
      } catch (e) {
        this.saveError = e.message
        toast('保存失败', 'error')
      } finally {
        this.saving = false
      }
    },
  },
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
  margin-bottom: 8px;
  font-size: 13px;
}

.warn {
  display: inline-flex;
  align-items: center;
  gap: 6px;
  color: var(--qq-warn);
  font-size: 13px;
}

.hint {
  display: inline-flex;
  align-items: center;
  gap: 6px;
  color: var(--qq-text-muted);
  font-size: 12px;
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
  font-size: 11px;
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
  font-size: 13px;
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
