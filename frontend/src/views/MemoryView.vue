<template>
  <div class="mem-view">
    <UiPageHeader title="记忆管理" />
    <div class="toolbar">
      <label>群组<select v-model="groupId" @change="load"><option value="">-- 选择群 --</option><option v-for="g in groups" :key="g" :value="g">{{ g }}</option></select></label>
      <input v-model="keyword" placeholder="关键词过滤" class="kw-input" @keyup.enter="load" />
      <UiButton :loading="loading" icon="RefreshCw" :disabled="!groupId" @click="load">刷新</UiButton>
      <UiButton v-if="groupId" variant="danger" icon="Trash2" @click="clearAll">清空全部</UiButton>
    </div>
    <p v-if="error" class="error">{{ error }}</p>
    <UiLoading v-else-if="loading" />
    <UiEmpty v-else-if="groupId && memories.length === 0" icon="Brain" title="暂无记忆条目" />

    <TransitionGroup name="list" tag="div" class="mem-list">
      <UiCard v-for="m in memories" :key="m.id" padding="md" shadow="sm">
        <div class="mem-meta"><span class="meta-id">#{{ m.id }}</span><UiTag size="sm" :variant="m.scope === 'user' ? 'success' : 'info'">{{ m.scope }}</UiTag><span v-if="m.user_id" class="meta-text">uid {{ m.user_id }}</span><span class="meta-text">conf {{ m.confidence.toFixed(2) }}</span><span class="meta-text">{{ m.updated_at.slice(0, 16).replace('T', ' ') }}</span></div>
        <div v-if="editing !== m.id" class="mem-content">{{ m.content }}</div>
        <div v-if="editing !== m.id && m.tags.length" class="mem-tags"><UiTag v-for="t in m.tags" :key="t">{{ t }}</UiTag></div>
        <div v-if="editing === m.id" class="edit-block">
          <textarea v-model="editContent" rows="3" />
          <div class="edit-row"><input v-model="editTags" placeholder="标签（逗号分隔）" /><input v-model.number="editConf" type="number" step="0.1" min="0" max="1" style="width:90px" /></div>
          <div class="edit-actions"><UiButton variant="primary" icon="Check" @click="saveEdit(m)">保存</UiButton><UiButton variant="ghost" @click="editing = null">取消</UiButton></div>
        </div>
        <div v-if="editing !== m.id" class="mem-actions"><UiButton size="sm" icon="Pencil" @click="startEdit(m)">编辑</UiButton><UiButton size="sm" variant="danger" icon="Trash2" @click="del(m.id)">删除</UiButton></div>
      </UiCard>
    </TransitionGroup>

    <UiCard v-if="groupId" padding="md" shadow="sm" class="add-card">
      <h3 class="section-title">新增记忆<UiInfoTip text="scope 选 group 对全群生效；选 user 需填 user_id，仅在涉及该用户的对话中被引用。条目的置信度（0–1）是可信度标记：手动添加为 1.0，自动抽取固定 0.5，编辑时可调整。" /></h3>
      <div class="add-form">
        <textarea v-model="newContent" rows="2" placeholder="内容" />
        <div class="add-row"><select v-model="newScope"><option value="group">group</option><option value="user">user</option></select><input v-model="newUserId" placeholder="user_id（可选）" style="width:120px" /><input v-model="newTags" placeholder="标签（逗号分隔）" /><UiButton variant="primary" icon="Plus" @click="addMemory">添加</UiButton></div>
      </div>
    </UiCard>
  </div>
</template>

<script setup lang="ts">
import { onMounted, ref } from 'vue'
import UiPageHeader from '../components/ui/UiPageHeader.vue'; import UiCard from '../components/ui/UiCard.vue'; import UiButton from '../components/ui/UiButton.vue'; import UiTag from '../components/ui/UiTag.vue'; import UiLoading from '../components/ui/UiLoading.vue'; import UiEmpty from '../components/ui/UiEmpty.vue'; import UiInfoTip from '../components/ui/UiInfoTip.vue'
import { fetchKnownGroups } from '../api/groups'; import { fetchMemories, createMemory, updateMemory, deleteMemory, clearAllMemories } from '../api/memory'; import { toast } from '../toast'

const groups = ref<string[]>([]); const groupId = ref(''); const keyword = ref(''); const memories = ref<any[]>([]); const loading = ref(false); const error = ref<string | null>(null); const editing = ref<number | null>(null); const editContent = ref(''); const editTags = ref(''); const editConf = ref(1.0); const newContent = ref(''); const newScope = ref('group'); const newUserId = ref(''); const newTags = ref('')

onMounted(async () => { try { groups.value = (await fetchKnownGroups()).groups || [] } catch (e: unknown) { error.value = `加载失败: ${(e as Error).message}` } })
async function load() { if (!groupId.value) return; loading.value = true; error.value = null; try { memories.value = await fetchMemories(groupId.value, keyword.value) } catch (e: unknown) { error.value = (e as Error).message } finally { loading.value = false } }
function startEdit(m: any) { editing.value = m.id; editContent.value = m.content; editTags.value = m.tags.join(', '); editConf.value = m.confidence }
async function saveEdit(m: any) { try { await updateMemory(groupId.value, m.id, { content: editContent.value, tags: editTags.value.split(',').map(t => t.trim()).filter(Boolean), confidence: isNaN(editConf.value) ? null : Number(editConf.value) }); editing.value = null; toast('已保存'); await load() } catch (e: unknown) { toast((e as Error).message, 'error') } }
async function del(id: number) { if (!confirm(`删除记忆 #${id}？`)) return; try { await deleteMemory(groupId.value, id); memories.value = memories.value.filter(m => m.id !== id); toast('已删除') } catch (e: unknown) { toast((e as Error).message, 'error') } }
async function clearAll() { if (!confirm(`清空群 ${groupId.value} 全部记忆？`)) return; try { const r = await clearAllMemories(groupId.value); memories.value = []; toast(`已删除 ${r.deleted} 条`) } catch (e: unknown) { toast((e as Error).message, 'error') } }
async function addMemory() { if (!newContent.value.trim()) { toast('内容不能为空', 'error'); return }; try { await createMemory(groupId.value, { content: newContent.value.trim(), scope: newScope.value, user_id: newUserId.value.trim() || null, tags: newTags.value.split(',').map(t => t.trim()).filter(Boolean) }); newContent.value = ''; newUserId.value = ''; newTags.value = ''; toast('已添加'); await load() } catch (e: unknown) { toast((e as Error).message, 'error') } }
</script>

<style scoped>
.mem-view { display: flex; flex-direction: column; flex: 1; min-height: 0; }
.error { color: var(--qq-danger); }
.toolbar { display: flex; align-items: center; gap: var(--qq-gap-md); flex-wrap: wrap; margin-bottom: var(--qq-gap-lg); padding: var(--qq-gap-sm) var(--qq-gap-md); background: var(--qq-surface); border-radius: var(--qq-radius-card); box-shadow: var(--qq-shadow-card); }
.toolbar label { display: flex; align-items: center; gap: var(--qq-gap-xs); color: var(--qq-text-muted); font-size: var(--qq-text-sm); }
.kw-input { width: 180px; }

.mem-list { display: flex; flex-direction: column; gap: var(--qq-gap-sm); margin-bottom: var(--qq-gap-md); }
.mem-meta { display: flex; align-items: center; flex-wrap: wrap; gap: var(--qq-gap-xs); font-size: var(--qq-text-xs); margin-bottom: var(--qq-gap-sm); }
.meta-id { color: var(--qq-text-muted); font-family: var(--qq-font-mono); }
.meta-text { color: var(--qq-text-muted); }
.mem-content { font-size: var(--qq-text-base); white-space: pre-wrap; word-break: break-all; color: var(--qq-text); line-height: 1.7; }
.mem-tags { margin-top: var(--qq-gap-sm); display: flex; gap: var(--qq-gap-xs); flex-wrap: wrap; }
.mem-actions { margin-top: 10px; display: flex; gap: var(--qq-gap-xs); }
.edit-block { display: flex; flex-direction: column; gap: var(--qq-gap-sm); margin-top: 6px; }
.edit-block textarea { width: 100%; resize: vertical; }
.edit-row { display: flex; gap: var(--qq-gap-sm); flex-wrap: wrap; }
.edit-row input { flex: 1; min-width: 120px; }
.edit-actions { display: flex; gap: var(--qq-gap-xs); }
.add-card { margin-bottom: var(--qq-gap-md); }
.add-card h3 { margin: 0 0 var(--qq-gap-sm) 0; }
.add-form { display: flex; flex-direction: column; gap: var(--qq-gap-sm); }
.add-form textarea { width: 100%; resize: vertical; }
.add-row { display: flex; gap: var(--qq-gap-sm); flex-wrap: wrap; align-items: center; }
</style>
