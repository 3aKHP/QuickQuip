<template>
  <div>
    <div class="toolbar">
      <label>群组
        <select v-model="groupId" @change="load">
          <option value="">-- 选择群 --</option>
          <option v-for="g in groups" :key="g" :value="g">{{ g }}</option>
        </select>
      </label>
      <input v-model="keyword" placeholder="关键词过滤" @keyup.enter="load" style="width:160px" />
      <button @click="load" :disabled="!groupId || loading">刷新</button>
      <button v-if="groupId" class="btn-off small" @click="clearAll">清空全部</button>
    </div>

    <p v-if="error" class="error">{{ error }}</p>
    <p v-else-if="groupId && !loading && memories.length === 0" class="muted">暂无记忆条目</p>

    <div v-for="m in memories" :key="m.id" class="card memory-row">
      <div class="mem-meta muted">
        #{{ m.id }} &nbsp;·&nbsp; {{ m.scope }}
        <span v-if="m.user_id"> &nbsp;·&nbsp; uid {{ m.user_id }}</span>
        &nbsp;·&nbsp; conf {{ m.confidence.toFixed(2) }}
        &nbsp;·&nbsp; {{ m.updated_at.slice(0, 16).replace('T', ' ') }}
      </div>
      <div v-if="editing !== m.id" class="mem-content">{{ m.content }}</div>
      <div v-if="editing !== m.id && m.tags.length" class="mem-tags">
        <span v-for="t in m.tags" :key="t" class="tag">{{ t }}</span>
      </div>
      <div v-if="editing === m.id" class="edit-block">
        <textarea v-model="editContent" rows="3" />
        <input v-model="editTags" placeholder="标签（逗号分隔）" />
        <input v-model.number="editConf" type="number" step="0.1" min="0" max="1" style="width:80px" />
        <div class="edit-actions">
          <button @click="saveEdit(m)">保存</button>
          <button @click="editing = null">取消</button>
        </div>
      </div>
      <div class="mem-actions">
        <button class="small" @click="startEdit(m)" v-if="editing !== m.id">编辑</button>
        <button class="small btn-off" @click="del(m.id)">删除</button>
      </div>
    </div>

    <div v-if="groupId" class="card">
      <h3>新增记忆</h3>
      <div class="add-form">
        <textarea v-model="newContent" rows="2" placeholder="内容" />
        <div class="add-row">
          <select v-model="newScope">
            <option value="group">group</option>
            <option value="user">user</option>
          </select>
          <input v-model="newUserId" placeholder="user_id（可选）" style="width:120px" />
          <input v-model="newTags" placeholder="标签（逗号分隔）" />
          <button @click="addMemory">添加</button>
        </div>
      </div>
    </div>
  </div>
</template>

<script>
import { apiFetch } from '../api.js'
import { toast } from '../toast.js'

export default {
  data: () => ({
    groups: [], groupId: '', keyword: '',
    memories: [], loading: false, error: null,
    editing: null, editContent: '', editTags: '', editConf: 1.0,
    newContent: '', newScope: 'group', newUserId: '', newTags: '',
  }),
  async mounted() {
    try {
      const d = await apiFetch('/api/groups/known')
      this.groups = d.groups || []
    } catch (e) {
      this.error = `加载群组列表失败: ${e.message}`
    }
  },
  methods: {
    async load() {
      if (!this.groupId) return
      this.loading = true; this.error = null
      try {
        const qs = this.keyword ? `?keyword=${encodeURIComponent(this.keyword)}` : ''
        this.memories = await apiFetch(`/api/memory/${this.groupId}${qs}`)
      } catch (e) { this.error = e.message }
      finally { this.loading = false }
    },
    startEdit(m) {
      this.editing = m.id
      this.editContent = m.content
      this.editTags = m.tags.join(', ')
      this.editConf = m.confidence
    },
    async saveEdit(m) {
      try {
        // M9: confidence 为空字符串或 NaN 时传 null，避免 422
        const conf = this.editConf === '' || isNaN(this.editConf) ? null : Number(this.editConf)
        await apiFetch(`/api/memory/${this.groupId}/${m.id}`, {
          method: 'PUT',
          body: JSON.stringify({
            content: this.editContent,
            tags: this.editTags.split(',').map(t => t.trim()).filter(Boolean),
            confidence: conf,
          }),
        })
        this.editing = null
        toast('已保存')
        await this.load()
      } catch (e) { toast(e.message, 'error') }
    },
    async del(id) {
      if (!confirm(`删除记忆 #${id}？`)) return
      try {
        await apiFetch(`/api/memory/${this.groupId}/${id}`, { method: 'DELETE' })
        this.memories = this.memories.filter(m => m.id !== id)
        toast('已删除')
      } catch (e) { toast(e.message, 'error') }
    },
    async clearAll() {
      if (!confirm(`清空群 ${this.groupId} 的全部记忆？`)) return
      try {
        const r = await apiFetch(`/api/memory/${this.groupId}`, { method: 'DELETE' })
        this.memories = []
        toast(`已删除 ${r.deleted} 条`)
      } catch (e) { toast(e.message, 'error') }
    },
    async addMemory() {
      if (!this.newContent.trim()) { toast('内容不能为空', 'error'); return }
      try {
        await apiFetch(`/api/memory/${this.groupId}`, {
          method: 'POST',
          body: JSON.stringify({
            content: this.newContent.trim(),
            scope: this.newScope,
            user_id: this.newUserId.trim() || null,
            tags: this.newTags.split(',').map(t => t.trim()).filter(Boolean),
          }),
        })
        this.newContent = ''; this.newUserId = ''; this.newTags = ''
        toast('已添加')
        await this.load()
      } catch (e) { toast(e.message, 'error') }
    },
  },
}
</script>

<style scoped>
.memory-row { position: relative; }
.mem-meta { font-size: 12px; margin-bottom: 6px; }
.mem-content { font-size: 13px; white-space: pre-wrap; word-break: break-all; }
.mem-tags { margin-top: 6px; display: flex; gap: 4px; flex-wrap: wrap; }
.tag {
  background: #1f6feb22;
  border: 1px solid #1f6feb55;
  color: #58a6ff;
  border-radius: 3px;
  padding: 1px 6px;
  font-size: 11px;
}
.mem-actions { margin-top: 8px; display: flex; gap: 6px; }
.edit-block { display: flex; flex-direction: column; gap: 6px; margin-top: 6px; }
.edit-block textarea, .edit-block input {
  background: #0d1117;
  border: 1px solid #30363d;
  border-radius: 4px;
  color: #c9d1d9;
  padding: 4px 8px;
  font-size: 13px;
  width: 100%;
  resize: vertical;
}
.edit-actions { display: flex; gap: 6px; }
.add-form { display: flex; flex-direction: column; gap: 8px; }
.add-form textarea {
  background: #0d1117;
  border: 1px solid #30363d;
  border-radius: 4px;
  color: #c9d1d9;
  padding: 6px 8px;
  font-size: 13px;
  width: 100%;
  resize: vertical;
}
</style>
