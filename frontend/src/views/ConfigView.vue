<template>
  <div class="config-view">
    <UiPageHeader title="LLM 配置">
      <template #actions>
        <span v-if="missing" class="warn">
          <UiIcon name="AlertTriangle" :size="14" />
          config/llm.toml 不存在，保存后将创建
        </span>
        <UiButton icon="RotateCcw" :disabled="saving" @click="load">重置</UiButton>
        <UiButton variant="primary" :loading="saving" icon="Save" @click="save">保存</UiButton>
      </template>
    </UiPageHeader>

    <p v-if="loadError" class="error">{{ loadError }}</p>
    <p v-if="saveError" class="error save-error">{{ saveError }}</p>
    <UiLoading v-else-if="!loaded" />

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
import { fetchLlmConfig, saveLlmConfig } from '../api/config.js'
import { toast } from '../toast.js'

export default {
  components: { UiPageHeader, UiButton, UiIcon, UiLoading, UiCard },
  data: () => ({
    loaded: false,
    loadError: null,
    saveError: null,
    saving: false,
    missing: false,
    content: '',
  }),
  async mounted() { await this.load() },
  methods: {
    async load() {
      this.loadError = null
      this.saveError = null
      try {
        const d = await fetchLlmConfig()
        this.content = d.content
        this.missing = d.missing || false
        this.loaded = true
      } catch (e) {
        this.loadError = e.message
      }
    },
    async save() {
      this.saving = true
      this.saveError = null
      try {
        await saveLlmConfig(this.content)
        this.missing = false
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
  height: calc(100vh - 92px);
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
  border: 1px solid var(--qq-border);
  border-radius: var(--qq-radius-md);
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
