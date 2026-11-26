<template>
  <div class="memory-view">
    <UiPageHeader title="记忆管理" subtitle="群内记忆由全群共享，私聊记忆独立保存">
      <template #actions>
        <router-link to="/llm-config?section=context" custom v-slot="{ navigate }">
          <UiButton variant="ghost" size="sm" icon="SlidersHorizontal" @click="navigate">配置记忆与容量</UiButton>
        </router-link>
      </template>
    </UiPageHeader>
    <div class="toolbar">
      <label class="field-inline">
        <span>会话</span>
        <select v-model="chatType" @change="reset">
          <option value="group">群聊</option>
          <option value="private">私聊</option>
        </select>
      </label>
      <label class="field-inline">
        <span>{{ chatType === 'group' ? '群号' : 'QQ 号' }}</span>
        <input v-model="chatId" :list="chatType === 'group' ? 'memory-groups' : undefined" @change="reset" />
      </label>
      <datalist id="memory-groups"><option v-for="g in groups" :key="g" :value="g" /></datalist>
      <input v-model="keyword" aria-label="搜索记忆" placeholder="标题、正文、名字或 QQ" @keyup.enter="reset" />
      <UiButton :disabled="!validScope || loading" :loading="loading" @click="reset">查询</UiButton>
      <span v-if="status" class="capacity-note">已使用 {{ status.count }} / {{ status.capacity }} 条</span>
      <UiButton
        v-if="loadedScope && memories.length"
        size="sm"
        variant="ghost"
        :icon="markdownPreview ? 'FileCode' : 'FileText'"
        @click="markdownPreview = !markdownPreview"
      >{{ markdownPreview ? '切换纯文本' : 'Markdown 预览' }}</UiButton>
      <UiButton
        v-if="loadedScope && (status?.count ?? 0) > 0"
        variant="danger"
        :disabled="clearing || loading"
        :loading="clearing"
        @click="clearAll"
      >清空全部</UiButton>
    </div>
    <p v-if="error" role="alert">{{ error }}</p>
    <UiLoading v-if="loading" />
    <UiEmpty v-else-if="!loadedScope" title="请选择会话" description="输入群号或私聊对象的 QQ 号后查询。" />
    <UiEmpty v-else-if="!memories.length" title="没有匹配的记忆" description="可以调整关键词，或在下方添加记忆。" />
    <div class="memory-list">
      <UiCard v-for="item in memories" :key="item.id" padding="md" class="memory-card">
        <div class="memory-head">
          <span class="memory-title">#{{ item.id }} · {{ item.title }}</span>
          <span class="meta">{{ item.updated_at.slice(0, 16).replace('T', ' ') }}</span>
        </div>
        <p v-if="item.description" class="memory-desc">{{ item.description }}</p>
        <p class="meta">{{ writerLabel(item.writer) }}；依据：{{ item.source_user_id || '未知发言者' }}（{{ roleLabel(item.source_role) }}）</p>
        <p v-if="item.user_id" class="meta">历史关联成员：QQ {{ item.user_id }}</p>
        <template v-if="editing === item.id">
          <div class="memory-form">
            <label class="form-field">
              <span>标题（留空将自动提取）</span>
              <input v-model="editTitle" aria-label="标题" maxlength="64" placeholder="标题（可选）" />
            </label>
            <label class="form-field">
              <span>描述（留空将自动提取）</span>
              <input v-model="editDescription" aria-label="描述" maxlength="160" placeholder="描述（可选）" />
            </label>
            <div class="form-field">
              <span>正文</span>
              <RecordContentEditor v-model="editBody" :group-id="loadedScope" />
            </div>
            <div class="actions">
              <UiButton :disabled="saving" :loading="saving" @click="saveEdit(item)">保存</UiButton>
              <UiButton variant="ghost" :disabled="saving" @click="editing = null">取消</UiButton>
            </div>
          </div>
        </template>
        <template v-else>
          <div
            class="memory-body"
            :class="{ 'memory-body--collapsed': isLongBody(displayText(item)) && !expandedIds[item.id] }"
          >
            <!-- eslint-disable-next-line vue/no-v-html -- DOMPurify sanitized in useMarkdown -->
            <div v-if="markdownPreview" class="md-content" v-html="renderMarkdown(displayText(item))" />
            <pre v-else>{{ displayText(item) }}</pre>
          </div>
          <UiButton
            v-if="isLongBody(displayText(item))"
            size="sm"
            variant="ghost"
            class="expand-btn"
            :icon="expandedIds[item.id] ? 'ChevronUp' : 'ChevronDown'"
            @click="toggleExpand(item.id)"
          >{{ expandedIds[item.id] ? '收起正文' : '展开全文' }}</UiButton>
          <details class="raw-detail"><summary>查看原文</summary><pre>{{ item.content }}</pre></details>
          <div class="actions">
            <UiButton :disabled="deletingId !== null || clearing" @click="startEdit(item)">编辑</UiButton>
            <UiButton
              variant="danger"
              :disabled="deletingId !== null || clearing"
              :loading="deletingId === item.id"
              @click="remove(item)"
            >删除</UiButton>
          </div>
        </template>
      </UiCard>
    </div>
    <div v-if="loadedScope" class="toolbar">
      <UiButton :disabled="loading || offset === 0" @click="page(-1)">上一页</UiButton>
      <span>第 {{ offset / 50 + 1 }} 页</span>
      <UiButton :disabled="loading || memories.length < 50" @click="page(1)">下一页</UiButton>
    </div>
    <UiCard v-if="loadedScope" padding="md" class="create-card">
      <h3>新增记忆</h3>
      <p class="meta">正文支持 Markdown。标题和描述留空时，从正文自动提取。</p>
      <div class="memory-form">
        <label class="form-field">
          <span>标题（可选）</span>
          <input v-model="newTitle" maxlength="64" aria-label="新记忆标题" placeholder="标题（可选）" />
        </label>
        <label class="form-field">
          <span>描述（可选）</span>
          <input v-model="newDescription" maxlength="160" aria-label="新记忆描述" placeholder="描述（可选）" />
        </label>
        <div class="form-field">
          <span>正文</span>
          <RecordContentEditor v-model="newBody" :group-id="loadedScope" />
        </div>
        <div class="actions">
          <UiButton :disabled="saving" :loading="saving" @click="add">添加</UiButton>
        </div>
      </div>
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
import { renderMarkdown } from '../composables/useMarkdown'
import { toast } from '../toast'

const chatType = ref('group'), chatId = ref(''), keyword = ref(''), loadedScope = ref(''), loadedKeyword = ref('')
const groups = ref<string[]>([]), memories = ref<MemoryEntry[]>([])
const offset = ref(0), status = ref<MemoryStatus | null>(null)
const loading = ref(false), saving = ref(false), deletingId = ref<number | null>(null), clearing = ref(false), error = ref('')
const editing = ref<number | null>(null), editVersion = ref(0)
const editTitle = ref(''), editDescription = ref(''), newTitle = ref(''), newDescription = ref('')
const editBody = ref<RecordBody>(emptyRecordBody()), newBody = ref<RecordBody>(emptyRecordBody())
const markdownPreview = ref(true)
const expandedIds = ref<Record<number, boolean>>({})

const trimmedChatId = computed(() => chatId.value.trim())
const validScope = computed(() => /^\d{5,12}$/.test(trimmedChatId.value))
const scope = computed(() => `${chatType.value === 'private' ? 'private:' : ''}${trimmedChatId.value}`)
let loadSequence = 0
const errorText = (e: unknown) => e instanceof Error ? e.message : String(e)
const roleLabel = (role: string) => ({ GLOBAL_ADMIN: '全局管理员', GROUP_OWNER: '群主', GROUP_ADMIN: '群管理员', MEMBER: '普通成员' }[role] || '角色未知')
const writerLabel = (writer: string) => ({ model: '模型维护', command: '群内指令', web: '管理页编辑', legacy: '历史条目' }[writer] || writer)

function displayText(item: MemoryEntry): string {
  return item.content_display || item.content || ''
}

function isLongBody(text: string): boolean {
  return text.split('\n').length > 6 || text.length > 360
}

function toggleExpand(id: number) {
  expandedIds.value = { ...expandedIds.value, [id]: !expandedIds.value[id] }
}

onMounted(async () => {
  try { groups.value = (await fetchKnownGroups()).groups || [] }
  catch (e) { error.value = errorText(e) }
})
async function reset() {
  offset.value = 0; editing.value = null; loadedScope.value = ''; status.value = null; memories.value = []
  expandedIds.value = {}
  loadedKeyword.value = keyword.value.trim()
  await load(scope.value, loadedKeyword.value)
}
async function load(targetScope = loadedScope.value || scope.value, targetKeyword = loadedKeyword.value) {
  const sequence = ++loadSequence
  if (!targetScope || (targetScope === scope.value && !validScope.value)) { loading.value = false; return }
  loading.value = true; error.value = ''
  try {
    const [items, capacity] = await Promise.all([fetchMemories(targetScope, targetKeyword, offset.value), fetchMemoryStatus(targetScope)])
    if (sequence !== loadSequence) return
    memories.value = items; status.value = capacity; loadedScope.value = targetScope; loadedKeyword.value = targetKeyword
  } catch (e) { if (sequence === loadSequence) error.value = errorText(e) }
  finally { if (sequence === loadSequence) loading.value = false }
}
async function page(delta: number) {
  offset.value = Math.max(0, offset.value + 50 * delta)
  editing.value = null
  await load(loadedScope.value, loadedKeyword.value)
}
function startEdit(item: MemoryEntry) {
  editing.value = item.id; editVersion.value = item.version
  editTitle.value = item.title; editDescription.value = item.description
  editBody.value = structuredClone(toRaw(item.content_parts))
}
async function saveEdit(item: MemoryEntry) {
  const target = loadedScope.value
  saving.value = true
  try {
    await updateMemory(target, item.id, {
      version: editVersion.value,
      title: editTitle.value.trim() || undefined,
      description: editDescription.value.trim() || undefined,
      content_parts: editBody.value,
    })
    editing.value = null; toast('已保存'); await load(target, loadedKeyword.value)
  } catch (e) { toast(errorText(e), 'error') }
  finally { saving.value = false }
}
async function add() {
  const target = loadedScope.value
  saving.value = true
  try {
    await createMemory(target, {
      title: newTitle.value.trim() || undefined,
      description: newDescription.value.trim() || undefined,
      content_parts: newBody.value,
    })
    newBody.value = emptyRecordBody(); newTitle.value = ''; newDescription.value = ''
    offset.value = 0; editing.value = null; expandedIds.value = {}
    toast('已添加'); await load(target, loadedKeyword.value)
  } catch (e) { toast(errorText(e), 'error') }
  finally { saving.value = false }
}
async function remove(item: MemoryEntry) {
  if (deletingId.value !== null || clearing.value) return
  if (!confirm(`删除记忆 #${item.id}？`)) return
  const target = loadedScope.value
  const stepBack = memories.value.length <= 1 && offset.value > 0
  deletingId.value = item.id
  try {
    await deleteMemory(target, item.id, item.version)
    toast('已删除')
    if (stepBack) offset.value = Math.max(0, offset.value - 50)
    await load(target, loadedKeyword.value)
  } catch (e) { toast(errorText(e), 'error') }
  finally { deletingId.value = null }
}
async function clearAll() {
  if (clearing.value) return
  if (!confirm('清空当前会话的全部记忆？')) return
  const target = loadedScope.value
  clearing.value = true
  try {
    const result = await clearAllMemories(target)
    offset.value = 0; editing.value = null; expandedIds.value = {}
    toast(`已删除 ${result.deleted} 条`)
    await load(target, loadedKeyword.value)
  } catch (e) { toast(errorText(e), 'error') }
  finally { clearing.value = false }
}
</script>

<style scoped>
.memory-view, .memory-list { display: flex; flex-direction: column; gap: var(--qq-gap-md); }
.toolbar, .actions { display: flex; flex-wrap: wrap; align-items: center; gap: var(--qq-gap-sm); }
.field-inline { display: inline-flex; align-items: center; gap: 6px; font-size: var(--qq-text-sm); color: var(--qq-text-muted); }
.capacity-note { font-size: var(--qq-text-sm); color: var(--qq-text-muted); font-variant-numeric: tabular-nums; }
.memory-card, .create-card { display: flex; flex-direction: column; gap: var(--qq-gap-xs); }
.memory-head { display: flex; align-items: baseline; justify-content: space-between; gap: var(--qq-gap-sm); flex-wrap: wrap; }
.memory-title { font-weight: 600; color: var(--qq-text); }
.memory-desc { margin: 0; color: var(--qq-text); font-size: var(--qq-text-sm); }
.meta { margin: 0; color: var(--qq-text-muted); font-size: var(--qq-text-sm); }
.memory-body { position: relative; }
.memory-body--collapsed { max-height: 11.5em; overflow: hidden; mask-image: linear-gradient(180deg, #000 72%, transparent 100%); -webkit-mask-image: linear-gradient(180deg, #000 72%, transparent 100%); }
.expand-btn { align-self: flex-start; }
.md-content { font-size: var(--qq-text-sm); line-height: 1.65; color: var(--qq-text); overflow-wrap: anywhere; }
.md-content :deep(p) { margin: 0 0 0.5em; }
.md-content :deep(p:last-child) { margin-bottom: 0; }
.md-content :deep(h1), .md-content :deep(h2), .md-content :deep(h3) { font-size: 1em; font-weight: 600; margin: 0.4em 0; }
.md-content :deep(ul), .md-content :deep(ol) { margin: 0.3em 0 0.5em 1.4em; }
.md-content :deep(pre) { padding: var(--qq-gap-xs) var(--qq-gap-sm); border-radius: var(--qq-radius-sm); background: var(--qq-surface-strong); overflow-x: auto; font-family: var(--qq-font-mono); font-size: var(--qq-text-xs); }
.raw-detail { font-size: var(--qq-text-xs); color: var(--qq-text-muted); }
.raw-detail summary { cursor: pointer; user-select: none; }
pre { margin: 0; white-space: pre-wrap; overflow-wrap: anywhere; font-family: inherit; }
.memory-form { display: flex; flex-direction: column; gap: var(--qq-gap-sm); margin-top: var(--qq-gap-xs); }
.form-field { display: flex; flex-direction: column; gap: 4px; }
.form-field > span { font-size: var(--qq-text-xs); font-weight: 600; color: var(--qq-text-muted); }
.form-field input { width: 100%; }
[role="alert"] { color: var(--qq-danger); }
</style>
