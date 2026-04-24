<template>
  <div class="conv-view">
    <UiPageHeader title="对话日志">
      <template #actions>
        <UiButton icon="RefreshCw" :disabled="listing" @click="loadConversations">刷新</UiButton>
      </template>
    </UiPageHeader>

    <p v-if="listError" class="error">{{ listError }}</p>

    <div class="split">
      <UiCard padding="none" shadow="sm" class="list-card">
        <UiLoading v-if="listing && !conversations.length" />
        <UiEmpty
          v-else-if="!conversations.length"
          icon="Inbox"
          title="暂无对话记录"
        />
        <ul v-else class="conv-list">
          <li
            v-for="c in conversations"
            :key="c.group_id"
            class="conv-item"
            :class="{ active: c.group_id === selectedKey }"
            @click="selectConversation(c.group_id)"
          >
            <div class="conv-title">
              <UiTag size="sm" :variant="typeVariant(c.type)">{{ typeLabel(c.type) }}</UiTag>
              <span class="mono conv-id">{{ displayGroupId(c) }}</span>
            </div>
            <div class="conv-meta">
              <span>{{ c.count }} 条</span>
              <span>·</span>
              <span>{{ formatTime(c.latest) }}</span>
            </div>
          </li>
        </ul>
      </UiCard>

      <div class="main-col">
        <UiCard v-if="!selectedKey" padding="lg" shadow="sm" class="hint-card">
          <UiEmpty icon="MousePointerClick" title="从左侧选择一个会话查看消息" />
        </UiCard>

        <template v-else>
          <UiCard padding="md" shadow="sm" class="filter-card">
            <div class="filter-row">
              <span class="mono selected-id">{{ selectedKey }}</span>
              <input
                v-model="keyword"
                placeholder="按内容关键词过滤"
                @keyup.enter="reload"
              />
              <UiButton icon="Search" :loading="loadingMessages" @click="reload">查询</UiButton>
              <UiButton
                v-if="keyword"
                variant="ghost"
                icon="X"
                @click="clearKeyword"
              >清空</UiButton>
            </div>
          </UiCard>

          <p v-if="loadError" class="error">{{ loadError }}</p>

          <UiCard padding="none" shadow="sm" class="messages-card">
            <UiLoading v-if="loadingMessages && !messages.length" />
            <UiEmpty
              v-else-if="!messages.length"
              icon="Inbox"
              title="没有匹配的消息"
            />
            <div v-else class="messages">
              <div
                v-for="m in messages"
                :key="m.id"
                class="msg"
                :class="[`msg--${m.role}`]"
              >
                <div class="msg-head">
                  <UiTag size="sm" :variant="roleVariant(m.role)">{{ m.role }}</UiTag>
                  <span v-if="m.sender_name" class="sender">{{ m.sender_name }}</span>
                  <span v-else-if="m.user_id" class="mono sender">uid {{ m.user_id }}</span>
                  <span v-if="m.canonical_name && m.canonical_name !== m.sender_name" class="canonical">
                    （{{ m.canonical_name }}）
                  </span>
                  <span class="mono msg-id">#{{ m.id }}</span>
                  <span class="msg-time">{{ formatTime(m.created_at) }}</span>
                  <button class="msg-delete" title="删除此条" @click="onDelete(m)">
                    <UiIcon name="Trash2" :size="13" />
                  </button>
                </div>
                <div class="msg-body">{{ m.content }}</div>
              </div>
              <div class="load-more-wrap">
                <UiButton
                  v-if="hasMore"
                  :loading="loadingMore"
                  icon="ArrowUp"
                  @click="loadMore"
                >加载更早</UiButton>
                <span v-else class="muted">已到最早</span>
              </div>
            </div>
          </UiCard>
        </template>
      </div>
    </div>
  </div>
</template>

<script setup lang="ts">
import { ref } from 'vue'
import UiPageHeader from '../components/ui/UiPageHeader.vue'
import UiButton from '../components/ui/UiButton.vue'
import UiCard from '../components/ui/UiCard.vue'
import UiTag from '../components/ui/UiTag.vue'
import UiIcon from '../components/ui/UiIcon.vue'
import UiLoading from '../components/ui/UiLoading.vue'
import UiEmpty from '../components/ui/UiEmpty.vue'
import {
  listConversations,
  fetchMessages,
  deleteMessage,
} from '../api/conversations'
import { toast } from '../toast'

const PAGE_SIZE = 50

const conversations = ref<any[]>([])
const listing = ref(false)
const listError = ref<string | null>(null)

const selectedKey = ref('')
const keyword = ref('')
const messages = ref<any[]>([])
const loadingMessages = ref(false)
const loadingMore = ref(false)
const loadError = ref<string | null>(null)
const hasMore = ref(false)

function typeLabel(type: string): string {
  return { group: '群聊', private: '私聊', archive: '归档' }[type] || type
}

function typeVariant(type: string): string {
  return { group: 'info', private: 'success', archive: 'warn' }[type] || 'info'
}

function roleVariant(role: string): string {
  return { user: 'info', assistant: 'success', system: 'warn', tool: 'warn' }[role] || 'info'
}

function displayGroupId(conv: any): string {
  if (conv.type === 'private') return conv.group_id.slice('private:'.length)
  if (conv.type === 'archive') return conv.group_id.slice('archive:'.length)
  return conv.group_id
}

function formatTime(iso: string): string {
  if (!iso) return ''
  const d = new Date(iso)
  if (Number.isNaN(d.getTime())) return iso
  const pad = (n: number) => String(n).padStart(2, '0')
  return `${d.getFullYear()}-${pad(d.getMonth() + 1)}-${pad(d.getDate())} ${pad(d.getHours())}:${pad(d.getMinutes())}`
}

async function loadConversations() {
  listing.value = true
  listError.value = null
  try {
    const data = await listConversations()
    conversations.value = data.conversations || []
  } catch (e: unknown) {
    listError.value = (e as Error).message
  } finally {
    listing.value = false
  }
}

async function selectConversation(groupKey: string) {
  if (groupKey === selectedKey.value) return
  selectedKey.value = groupKey
  keyword.value = ''
  await reload()
}

async function reload() {
  if (!selectedKey.value) return
  loadingMessages.value = true
  loadError.value = null
  messages.value = []
  hasMore.value = false
  try {
    const data = await fetchMessages(selectedKey.value, {
      keyword: keyword.value || undefined,
      limit: PAGE_SIZE,
    })
    messages.value = data.messages || []
    hasMore.value = !!data.has_more
  } catch (e: unknown) {
    loadError.value = (e as Error).message
  } finally {
    loadingMessages.value = false
  }
}

async function loadMore() {
  if (!messages.value.length) return
  const oldestId = messages.value[messages.value.length - 1].id
  loadingMore.value = true
  try {
    const data = await fetchMessages(selectedKey.value, {
      beforeId: oldestId,
      keyword: keyword.value || undefined,
      limit: PAGE_SIZE,
    })
    messages.value.push(...(data.messages || []))
    hasMore.value = !!data.has_more
  } catch (e: unknown) {
    toast((e as Error).message, 'error')
  } finally {
    loadingMore.value = false
  }
}

function clearKeyword() {
  keyword.value = ''
  reload()
}

async function onDelete(m: any) {
  if (!confirm(`删除消息 #${m.id}？此操作不可撤销。`)) return
  try {
    await deleteMessage(selectedKey.value, m.id)
    messages.value = messages.value.filter(x => x.id !== m.id)
    toast('已删除')
  } catch (e: unknown) {
    toast((e as Error).message, 'error')
  }
}

loadConversations()
</script>

<style scoped>
.conv-view {
  display: flex;
  flex-direction: column;
  flex: 1;
  min-height: 0;
}

.error {
  color: var(--qq-danger);
}

.muted {
  color: var(--qq-text-muted);
  font-size: 13px;
}

.mono {
  font-family: var(--qq-font-mono);
}

.split {
  display: flex;
  gap: var(--qq-gap-md);
  flex: 1;
  min-height: 0;
}

.list-card {
  width: 260px;
  flex-shrink: 0;
  overflow-y: auto;
  max-height: calc(100vh - 180px);
}

.conv-list {
  list-style: none;
  margin: 0;
  padding: 0;
}

.conv-item {
  padding: var(--qq-gap-sm) var(--qq-gap-md);
  border-bottom: 1px solid var(--qq-border);
  cursor: pointer;
  transition: background var(--qq-transition-fast);
}

.conv-item:last-child {
  border-bottom: none;
}

.conv-item:hover {
  background: var(--qq-surface-elevated);
}

.conv-item.active {
  background: var(--qq-surface-elevated);
  box-shadow: inset 3px 0 0 var(--qq-accent);
}

.conv-title {
  display: flex;
  align-items: center;
  gap: var(--qq-gap-xs);
  margin-bottom: 3px;
}

.conv-id {
  color: var(--qq-text);
  font-size: 13px;
}

.conv-meta {
  font-size: 12px;
  color: var(--qq-text-muted);
  display: flex;
  gap: 4px;
  flex-wrap: wrap;
}

.main-col {
  display: flex;
  flex-direction: column;
  flex: 1;
  min-width: 0;
  gap: var(--qq-gap-sm);
}

.hint-card {
  flex: 1;
  display: flex;
  align-items: center;
  justify-content: center;
}

.filter-card {
  flex-shrink: 0;
}

.filter-row {
  display: flex;
  align-items: center;
  gap: var(--qq-gap-sm);
  flex-wrap: wrap;
}

.selected-id {
  font-size: 13px;
  color: var(--qq-text-muted);
}

.filter-row input {
  background: var(--qq-surface-strong);
  border: 1px solid var(--qq-border);
  border-radius: var(--qq-radius-sm);
  color: var(--qq-text);
  padding: 5px 10px;
  font-size: 14px;
  outline: none;
  flex: 1;
  min-width: 200px;
}

.filter-row input:focus {
  border-color: var(--qq-accent);
  box-shadow: 0 0 0 3px var(--qq-accent-soft);
}

.messages-card {
  flex: 1;
  overflow: hidden;
  display: flex;
  flex-direction: column;
  min-height: 300px;
}

.messages {
  overflow-y: auto;
  padding: var(--qq-gap-sm);
  display: flex;
  flex-direction: column;
  gap: 6px;
}

.msg {
  padding: 8px 10px;
  border-radius: var(--qq-radius-sm);
  background: var(--qq-surface-strong);
  border-left: 3px solid var(--qq-border);
}

.msg--user {
  border-left-color: var(--qq-accent);
}

.msg--assistant {
  border-left-color: var(--qq-success);
}

.msg--system, .msg--tool {
  border-left-color: var(--qq-warn);
}

.msg-head {
  display: flex;
  align-items: center;
  gap: var(--qq-gap-xs);
  font-size: 12px;
  margin-bottom: 4px;
  flex-wrap: wrap;
}

.sender {
  font-weight: 500;
  color: var(--qq-text);
}

.canonical {
  color: var(--qq-text-muted);
}

.msg-id {
  color: var(--qq-text-muted);
  font-size: 11px;
}

.msg-time {
  color: var(--qq-text-muted);
  font-size: 11px;
  margin-left: auto;
}

.msg-delete {
  background: transparent;
  border: none;
  color: var(--qq-text-muted);
  cursor: pointer;
  padding: 2px 4px;
  border-radius: 3px;
  transition: color var(--qq-transition-fast), background var(--qq-transition-fast);
}

.msg-delete:hover {
  color: var(--qq-danger);
  background: var(--qq-danger-soft);
}

.msg-body {
  font-size: 13px;
  color: var(--qq-text);
  line-height: 1.6;
  white-space: pre-wrap;
  word-break: break-word;
}

.load-more-wrap {
  display: flex;
  justify-content: center;
  padding: var(--qq-gap-sm);
}

@media (max-width: 900px) {
  .split {
    flex-direction: column;
  }
  .list-card {
    width: 100%;
    max-height: 200px;
  }
}
</style>
