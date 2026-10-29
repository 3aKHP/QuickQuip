<template>
  <div class="memory-view">
    <UiPageHeader title="记忆管理" subtitle="群内记忆由全群共享，私聊记忆独立保存">
      <template #actions><router-link to="/llm-config?section=context">配置记忆与容量</router-link></template>
    </UiPageHeader>
    <div class="toolbar">
      <label>会话<select v-model="chatType" @change="reset"><option value="group">群聊</option><option value="private">私聊</option></select></label>
      <label>{{ chatType === 'group' ? '群号' : 'QQ 号' }}<input v-model="chatId" :list="chatType === 'group' ? 'memory-groups' : undefined" @change="reset" /></label>
      <datalist id="memory-groups"><option v-for="g in groups" :key="g" :value="g" /></datalist>
      <input v-model="keyword" aria-label="搜索记忆" placeholder="标题、正文、名字或 QQ" @keyup.enter="reset" />
      <UiButton :disabled="!validScope" :loading="loading" @click="reset">查询</UiButton>
      <span v-if="status">已使用 {{ status.count }} / {{ status.capacity }} 条</span>
      <UiButton v-if="loadedScope" variant="danger" @click="clearAll">清空全部</UiButton>
    </div>
    <p v-if="error" role="alert">{{ error }}</p>
    <UiLoading v-if="loading" />
    <UiEmpty v-else-if="!loadedScope" title="请选择会话" description="输入群号或私聊对象的 QQ 号后查询。" />
    <UiEmpty v-else-if="!memories.length" title="没有匹配的记忆" description="可以调整关键词，或在下方添加记忆。" />
    <div class="memory-list">
      <UiCard v-for="item in memories" :key="item.id" padding="md">
        <div class="meta">#{{ item.id }} · {{ item.title }} · {{ item.updated_at.slice(0, 16).replace('T', ' ') }}</div>
        <p>{{ item.description }}</p>
        <p class="meta">{{ writerLabel(item.writer) }}；依据：{{ item.source_user_id || '未知发言者' }}（{{ roleLabel(item.source_role) }}）</p>
        <p v-if="item.user_id" class="meta">历史关联成员：QQ {{ item.user_id }}</p>
        <template v-if="editing === item.id">
          <input v-model="editTitle" aria-label="标题" maxlength="64" />
          <input v-model="editDescription" aria-label="描述" maxlength="160" />
          <RecordContentEditor v-model="editBody" :group-id="loadedScope" />
          <div class="actions"><UiButton :disabled="saving" @click="saveEdit(item)">保存</UiButton><UiButton variant="ghost" @click="editing = null">取消</UiButton></div>
        </template>
        <template v-else>
          <pre>{{ item.content_display || item.content }}</pre>
          <details><summary>查看原文</summary><pre>{{ item.content }}</pre></details>
          <div class="actions"><UiButton @click="startEdit(item)">编辑</UiButton><UiButton variant="danger" @click="remove(item)">删除</UiButton></div>
        </template>
      </UiCard>
    </div>
    <div v-if="loadedScope" class="toolbar">
      <UiButton :disabled="loading || offset === 0" @click="page(-1)">上一页</UiButton>
      <span>第 {{ offset / 50 + 1 }} 页</span>
      <UiButton :disabled="loading || memories.length < 50" @click="page(1)">下一页</UiButton>
    </div>
    <UiCard v-if="loadedScope" padding="md">
      <h3>新增记忆</h3>
      <p>正文支持 Markdown。标题和描述留空时，从正文自动提取。</p>
      <input v-model="newTitle" maxlength="64" aria-label="新记忆标题" placeholder="标题（可选）" />
      <input v-model="newDescription" maxlength="160" aria-label="新记忆描述" placeholder="描述（可选）" />
      <RecordContentEditor v-model="newBody" :group-id="loadedScope" />
      <UiButton :disabled="saving" @click="add">添加</UiButton>
    </UiCard>
  </div>
</template>

<script setup lang="ts">
import { computed, onMounted, ref, toRaw } from 'vue'
import RecordContentEditor from '../components/RecordContentEditor.vue'
import UiPageHeader from '../components/ui/UiPageHeader.vue'
import UiCard from '../components/ui/UiCard.vue'
import UiButton from '../components/ui/UiButton.vue'
import UiLoading from '../components/ui/UiLoading.vue'
import UiEmpty from '../components/ui/UiEmpty.vue'
import { emptyRecordBody, type RecordBody } from '../api/recordContent'
import { fetchKnownGroups } from '../api/groups'
import { fetchMemories, fetchMemoryStatus, createMemory, updateMemory, deleteMemory, clearAllMemories, type MemoryEntry, type MemoryStatus } from '../api/memory'
import { toast } from '../toast'

const chatType = ref('group'), chatId = ref(''), keyword = ref(''), loadedScope = ref('')
const groups = ref<string[]>([]), memories = ref<MemoryEntry[]>([])
const offset = ref(0), status = ref<MemoryStatus | null>(null)
const loading = ref(false), saving = ref(false), error = ref('')
const editing = ref<number | null>(null), editVersion = ref(0)
const editTitle = ref(''), editDescription = ref(''), newTitle = ref(''), newDescription = ref('')
const editBody = ref<RecordBody>(emptyRecordBody()), newBody = ref<RecordBody>(emptyRecordBody())
const validScope = computed(() => /^\d{5,12}$/.test(chatId.value))
const scope = computed(() => `${chatType.value === 'private' ? 'private:' : ''}${chatId.value}`)
let loadSequence = 0
const errorText = (e: unknown) => e instanceof Error ? e.message : String(e)
const roleLabel = (role: string) => ({ GLOBAL_ADMIN: '全局管理员', GROUP_OWNER: '群主', GROUP_ADMIN: '群管理员', MEMBER: '普通成员' }[role] || '角色未知')
const writerLabel = (writer: string) => ({ model: '模型维护', command: '群内指令', web: '管理页编辑', legacy: '历史条目' }[writer] || writer)
onMounted(async () => {
  try { groups.value = (await fetchKnownGroups()).groups || [] }
  catch (e) { error.value = errorText(e) }
})
async function reset() {
  offset.value = 0; editing.value = null; loadedScope.value = ''; status.value = null; memories.value = []
  await load()
}
async function load() {
  const sequence = ++loadSequence
  if (!validScope.value) { loading.value = false; return }
  const target = scope.value
  loading.value = true; error.value = ''
  try {
    const [items, capacity] = await Promise.all([fetchMemories(target, keyword.value, offset.value), fetchMemoryStatus(target)])
    if (sequence !== loadSequence) return
    memories.value = items; status.value = capacity; loadedScope.value = target
  } catch (e) { if (sequence === loadSequence) error.value = errorText(e) }
  finally { if (sequence === loadSequence) loading.value = false }
}
async function page(delta: number) { offset.value = Math.max(0, offset.value + 50 * delta); editing.value = null; await load() }
function startEdit(item: MemoryEntry) {
  editing.value = item.id; editVersion.value = item.version
  editTitle.value = item.title; editDescription.value = item.description
  editBody.value = structuredClone(toRaw(item.content_parts))
}
async function saveEdit(item: MemoryEntry) {
  const target = loadedScope.value
  saving.value = true
  try {
    await updateMemory(target, item.id, { version: editVersion.value, title: editTitle.value, description: editDescription.value, content_parts: editBody.value })
    editing.value = null; toast('已保存'); await load()
  } catch (e) { toast(errorText(e), 'error') }
  finally { saving.value = false }
}
async function add() {
  saving.value = true
  try {
    await createMemory(loadedScope.value, { title: newTitle.value || undefined, description: newDescription.value || undefined, content_parts: newBody.value })
    newBody.value = emptyRecordBody(); newTitle.value = ''; newDescription.value = ''
    toast('已添加'); await reset()
  } catch (e) { toast(errorText(e), 'error') }
  finally { saving.value = false }
}
async function remove(item: MemoryEntry) {
  if (!confirm(`删除记忆 #${item.id}？`)) return
  try { await deleteMemory(loadedScope.value, item.id, item.version); toast('已删除'); await load() }
  catch (e) { toast(errorText(e), 'error') }
}
async function clearAll() {
  if (!confirm('清空当前会话的全部记忆？')) return
  try { const result = await clearAllMemories(loadedScope.value); toast(`已删除 ${result.deleted} 条`); await reset() }
  catch (e) { toast(errorText(e), 'error') }
}
</script>

<style scoped>
.memory-view, .memory-list { display: flex; flex-direction: column; gap: var(--qq-gap-md); }
.toolbar, .actions { display: flex; flex-wrap: wrap; align-items: center; gap: var(--qq-gap-sm); }
.meta { color: var(--qq-text-muted); font-size: var(--qq-text-sm); }
pre { white-space: pre-wrap; overflow-wrap: anywhere; font-family: inherit; }
input { margin: 4px; }
[role="alert"] { color: var(--qq-danger); }
</style>
