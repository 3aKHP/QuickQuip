<template>
  <div>
    <div class="toolbar">
      <label>群组
        <select v-model="groupId" @change="loadList">
          <option value="">-- 选择群 --</option>
          <option v-for="g in groups" :key="g" :value="g">{{ g }}</option>
        </select>
      </label>
      <button @click="loadList" :disabled="!groupId || loading">刷新</button>
    </div>

    <p v-if="error" class="error">{{ error }}</p>

    <div v-if="!selected" class="summary-list">
      <div v-for="s in list" :key="s.summary_date" class="card summary-item">
        <div class="sum-header">
          <span class="sum-date">{{ s.summary_date }}</span>
          <span class="muted">{{ s.model_used || '—' }} &nbsp;·&nbsp; {{ s.char_count }} 字</span>
          <span v-if="s.published_at" class="muted">已发布</span>
          <span v-else class="tag-unpub">未发布</span>
        </div>
        <div class="sum-actions">
          <button class="small" @click="open(s.summary_date)">阅读</button>
          <button class="small btn-off" @click="del(s.summary_date)">删除</button>
        </div>
      </div>
      <p v-if="groupId && !loading && list.length === 0" class="muted">暂无总结记录</p>
    </div>

    <div v-if="selected" class="card">
      <div class="sum-detail-header">
        <strong>{{ groupId }} / {{ selected }}</strong>
        <button class="small" @click="selected = null; detail = null">← 返回</button>
      </div>
      <div v-if="detail" class="sum-body">{{ detail.content }}</div>
      <p v-else class="muted">加载中…</p>
    </div>
  </div>
</template>

<script>
import { apiFetch } from '../api.js'
import { toast } from '../toast.js'

export default {
  data: () => ({
    groups: [], groupId: '',
    list: [], loading: false, error: null,
    selected: null, detail: null,
  }),
  async mounted() {
    try {
      this.groups = await apiFetch('/api/summaries-groups')
    } catch (e) {
      this.error = `加载群组列表失败: ${e.message}`
    }
  },
  methods: {
    async loadList() {
      if (!this.groupId) return
      this.loading = true; this.error = null; this.selected = null; this.detail = null
      try {
        this.list = await apiFetch(`/api/summaries/${this.groupId}`)
      } catch (e) { this.error = e.message }
      finally { this.loading = false }
    },
    async open(date) {
      this.selected = date; this.detail = null
      try {
        this.detail = await apiFetch(`/api/summaries/${this.groupId}/${date}`)
      } catch (e) { toast(e.message, 'error'); this.selected = null }
    },
    async del(date) {
      if (!confirm(`删除 ${this.groupId} / ${date} 的总结？`)) return
      try {
        await apiFetch(`/api/summaries/${this.groupId}/${date}`, { method: 'DELETE' })
        this.list = this.list.filter(s => s.summary_date !== date)
        if (this.selected === date) { this.selected = null; this.detail = null }
        toast('已删除')
      } catch (e) { toast(e.message, 'error') }
    },
  },
}
</script>

<style scoped>
.summary-list { display: flex; flex-direction: column; gap: 8px; }
.summary-item {}
.sum-header { display: flex; align-items: center; gap: 12px; margin-bottom: 8px; flex-wrap: wrap; }
.sum-date { font-weight: 600; color: #e6edf3; }
.sum-actions { display: flex; gap: 6px; }
.tag-unpub {
  background: #f8514922;
  border: 1px solid #f8514955;
  color: #f85149;
  border-radius: 3px;
  padding: 1px 6px;
  font-size: 11px;
}
.sum-detail-header {
  display: flex;
  justify-content: space-between;
  align-items: center;
  margin-bottom: 12px;
}
.sum-body {
  white-space: pre-wrap;
  font-size: 13px;
  line-height: 1.7;
  word-break: break-all;
}
</style>
