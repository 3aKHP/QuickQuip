<template>
  <div class="config-view">
    <div class="view-header">
      <h2>LLM 配置</h2>
      <div class="header-actions">
        <span v-if="missing" class="warn">⚠ config/llm.toml 不存在，保存后将创建</span>
        <button @click="load" :disabled="saving">重置</button>
        <button class="btn-primary" @click="save" :disabled="saving">{{ saving ? '保存中…' : '保存' }}</button>
      </div>
    </div>
    <p v-if="loadError" class="error">{{ loadError }}</p>
    <p v-if="saveError" class="error save-error">{{ saveError }}</p>
    <p v-else-if="!loaded">加载中…</p>
    <textarea
      v-if="loaded"
      v-model="content"
      class="toml-editor"
      spellcheck="false"
      autocomplete="off"
    ></textarea>
  </div>
</template>

<script>
import { apiFetch } from '../api.js'
import { toast } from '../toast.js'
export default {
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
        const d = await apiFetch('/ops/api/config/llm')
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
        await apiFetch('/ops/api/config/llm', {
          method: 'PUT',
          body: JSON.stringify({ content: this.content }),
        })
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
.config-view { display: flex; flex-direction: column; height: calc(100vh - 92px); }
.view-header { display: flex; align-items: center; justify-content: space-between; margin-bottom: 12px; flex-shrink: 0; }
.view-header h2 { margin-bottom: 0; }
.header-actions { display: flex; align-items: center; gap: 10px; flex-wrap: wrap; }
.warn { color: #d29922; font-size: 13px; }
.save-error { margin-bottom: 8px; font-size: 13px; }
.btn-primary { background: #1f6feb; border-color: #1f6feb; color: #fff; }
.btn-primary:hover { background: #388bfd; }
.toml-editor {
  flex: 1;
  width: 100%;
  background: #0d1117;
  border: 1px solid #30363d;
  border-radius: 6px;
  color: #c9d1d9;
  font-family: 'Consolas', 'Monaco', monospace;
  font-size: 13px;
  line-height: 1.6;
  padding: 12px;
  resize: none;
  outline: none;
}
.toml-editor:focus { border-color: #58a6ff; }
</style>
