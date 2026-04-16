<template>
  <div>
    <UiPageHeader title="记忆管理" />

    <UiCard padding="md" shadow="sm" class="toolbar-card">
      <div class="toolbar-inner">
        <label>群组
          <select v-model="groupId" @change="load">
            <option value="">-- 选择群 --</option>
            <option v-for="g in groups" :key="g" :value="g">{{ g }}</option>
          </select>
        </label>
        <input v-model="keyword" placeholder="关键词过滤" @keyup.enter="load" style="width:180px" />
        <UiButton :loading="loading" icon="RefreshCw" :disabled="!groupId" @click="load">刷新</UiButton>
        <UiButton v-if="groupId" variant="danger" icon="Trash2" @click="clearAll">清空全部</UiButton>
      </div>
    </UiCard>

    <p v-if="error" class="error">{{ error }}</p>
    <UiLoading v-else-if="loading" />
    <UiEmpty v-else-if="groupId && memories.length === 0" icon="Brain" title="暂无记忆条目" />

    <TransitionGroup name="list" tag="div" class="memory-list">
      <UiCard
        v-for="m in memories"
        :key="m.id"
        padding="md"
        shadow="sm"
        class="memory-row"
      >
        <div class="mem-meta">
          <span class="meta-id">#{{ m.id }}</span>
          <UiTag size="sm" :variant="m.scope === 'user' ? 'success' : 'info'">{{ m.scope }}</UiTag>
          <span v-if="m.user_id" class="meta-text">uid {{ m.user_id }}</span>
          <span class="meta-text">conf {{ m.confidence.toFixed(2) }}</span>
          <span class="meta-text">{{ m.updated_at.slice(0, 16).replace('T', ' ') }}</span>
        </div>

        <div v-if="editing !== m.id" class="mem-content">{{ m.content }}</div>
        <div v-if="editing !== m.id && m.tags.length" class="mem-tags">
          <UiTag v-for="t in m.tags" :key="t">{{ t }}</UiTag>
        </div>

        <div v-if="editing === m.id" class="edit-block">
          <textarea v-model="editContent" rows="3" />
          <div class="edit-row">
            <input v-model="editTags" placeholder="标签（逗号分隔）" />
            <input v-model.number="editConf" type="number" step="0.1" min="0" max="1" style="width:90px" />
          </div>
          <div class="edit-actions">
            <UiButton variant="primary" icon="Check" @click="saveEdit(m)">保存</UiButton>
            <UiButton variant="ghost" @click="editing = null">取消</UiButton>
          </div>
        </div>

        <div v-if="editing !== m.id" class="mem-actions">
          <UiButton size="sm" icon="Pencil" @click="startEdit(m)">编辑</UiButton>
          <UiButton size="sm" variant="danger" icon="Trash2" @click="del(m.id)">删除</UiButton>
        </div>
      </UiCard>
    </TransitionGroup>

    <UiCard v-if="groupId" padding="md" shadow="sm" class="add-card">
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
          <UiButton variant="primary" icon="Plus" @click="addMemory">添加</UiButton>
        </div>
      </div>
    </UiCard>
  </div>
</template>

<script>
import UiPageHeader from '../components/ui/UiPageHeader.vue'
import UiCard from '../components/ui/UiCard.vue'
import UiButton from '../components/ui/UiButton.vue'
import UiTag from '../components/ui/UiTag.vue'
import UiIcon from '../components/ui/UiIcon.vue'
import UiLoading from '../components/ui/UiLoading.vue'
import UiEmpty from '../components/ui/UiEmpty.vue'
import { fetchKnownGroups } from '../api/groups.js'
import { fetchMemories, createMemory, updateMemory, deleteMemory, clearAllMemories } from '../api/memory.js'
import { toast } from '../toast.js'

export default {
  components: { UiPageHeader, UiCard, UiButton, UiTag, UiIcon, UiLoading, UiEmpty },
  data: () => ({
    groups: [], groupId: '', keyword: '',
    memories: [], loading: false, error: null,
    editing: null, editContent: '', editTags: '', editConf: 1.0,
    newContent: '', newScope: 'group', newUserId: '', newTags: '',
  }),
  async mounted() {
    try {
      const d = await fetchKnownGroups()
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
        this.memories = await fetchMemories(this.groupId, this.keyword)
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
        const conf = this.editConf === '' || isNaN(this.editConf) ? null : Number(this.editConf)
        await updateMemory(this.groupId, m.id, {
          content: this.editContent,
          tags: this.editTags.split(',').map(t => t.trim()).filter(Boolean),
          confidence: conf,
        })
        this.editing = null
        toast('已保存')
        await this.load()
      } catch (e) { toast(e.message, 'error') }
    },
    async del(id) {
      if (!confirm(`删除记忆 #${id}？`)) return
      try {
        await deleteMemory(this.groupId, id)
        this.memories = this.memories.filter(m => m.id !== id)
        toast('已删除')
      } catch (e) { toast(e.message, 'error') }
    },
    async clearAll() {
      if (!confirm(`清空群 ${this.groupId} 的全部记忆？`)) return
      try {
        const r = await clearAllMemories(this.groupId)
        this.memories = []
        toast(`已删除 ${r.deleted} 条`)
      } catch (e) { toast(e.message, 'error') }
    },
    async addMemory() {
      if (!this.newContent.trim()) { toast('内容不能为空', 'error'); return }
      try {
        await createMemory(this.groupId, {
          content: this.newContent.trim(),
          scope: this.newScope,
          user_id: this.newUserId.trim() || null,
          tags: this.newTags.split(',').map(t => t.trim()).filter(Boolean),
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
.error {
  color: var(--qq-danger);
}

.toolbar-card {
  margin-bottom: var(--qq-gap-md);
}

.toolbar-inner {
  display: flex;
  align-items: center;
  gap: var(--qq-gap-md);
  flex-wrap: wrap;
}

.toolbar-inner label {
  display: flex;
  align-items: center;
  gap: var(--qq-gap-xs);
  color: var(--qq-text-muted);
  font-size: 13px;
}

.toolbar-inner select,
.toolbar-inner input {
  background: var(--qq-surface-strong);
  border: 1px solid var(--qq-border);
  border-radius: var(--qq-radius-sm);
  color: var(--qq-text);
  padding: 5px 10px;
  font-size: 14px;
  outline: none;
}

.toolbar-inner select:focus,
.toolbar-inner input:focus {
  border-color: var(--qq-accent);
  box-shadow: 0 0 0 3px var(--qq-accent-soft);
}

.memory-list {
  display: flex;
  flex-direction: column;
  gap: var(--qq-gap-sm);
  margin-bottom: var(--qq-gap-md);
}

.memory-row {
  position: relative;
}

.mem-meta {
  display: flex;
  align-items: center;
  flex-wrap: wrap;
  gap: var(--qq-gap-xs);
  font-size: 12px;
  margin-bottom: 8px;
}

.meta-id {
  color: var(--qq-text-muted);
  font-family: var(--qq-font-mono);
}

.meta-text {
  color: var(--qq-text-muted);
}

.mem-content {
  font-size: 14px;
  white-space: pre-wrap;
  word-break: break-all;
  color: var(--qq-text);
  line-height: 1.7;
}

.mem-tags {
  margin-top: 8px;
  display: flex;
  gap: var(--qq-gap-xs);
  flex-wrap: wrap;
}

.mem-actions {
  margin-top: 10px;
  display: flex;
  gap: var(--qq-gap-xs);
}

.edit-block {
  display: flex;
  flex-direction: column;
  gap: var(--qq-gap-sm);
  margin-top: 6px;
}

.edit-block textarea,
.edit-block input {
  background: var(--qq-surface-strong);
  border: 1px solid var(--qq-border);
  border-radius: var(--qq-radius-sm);
  color: var(--qq-text);
  padding: 8px 10px;
  font-size: 13px;
  width: 100%;
  resize: vertical;
  outline: none;
}

.edit-block textarea:focus,
.edit-block input:focus {
  border-color: var(--qq-accent);
  box-shadow: 0 0 0 3px var(--qq-accent-soft);
}

.edit-row {
  display: flex;
  gap: var(--qq-gap-sm);
  flex-wrap: wrap;
}

.edit-actions {
  display: flex;
  gap: var(--qq-gap-xs);
}

.add-card h3 {
  margin: 0 0 var(--qq-gap-sm) 0;
  font-size: 15px;
  color: var(--qq-text);
}

.add-form {
  display: flex;
  flex-direction: column;
  gap: var(--qq-gap-sm);
}

.add-form textarea {
  background: var(--qq-surface-strong);
  border: 1px solid var(--qq-border);
  border-radius: var(--qq-radius-sm);
  color: var(--qq-text);
  padding: 8px 10px;
  font-size: 13px;
  width: 100%;
  resize: vertical;
  outline: none;
}

.add-form textarea:focus {
  border-color: var(--qq-accent);
  box-shadow: 0 0 0 3px var(--qq-accent-soft);
}
</style>
