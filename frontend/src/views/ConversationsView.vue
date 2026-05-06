<template>
  <div class="conv-view">
    <UiPageHeader title="对话日志"><template #actions><UiButton icon="RefreshCw" :disabled="listing" @click="loadConversations">刷新</UiButton></template></UiPageHeader>
    <p v-if="listError" class="error">{{ listError }}</p>

    <div class="split">
      <nav class="list-panel">
        <UiLoading v-if="listing && !conversations.length" />
        <UiEmpty v-else-if="!conversations.length" icon="BookOpen" title="暂无对话记录" />
        <div v-else class="list-scroll">
          <button v-for="c in conversations" :key="c.group_id" class="list-item" :class="{ active: c.group_id === selectedKey }" @click="selectConversation(c.group_id)">
            <div class="list-item-head">
              <UiTag size="sm" :variant="typeVariant(c.type)">{{ typeLabel(c.type) }}</UiTag>
              <span class="mono list-item-id">{{ displayGroupId(c) }}</span>
            </div>
            <div class="list-item-meta"><span>{{ c.count }} 条</span><span>·</span><span>{{ formatTime(c.latest) }}</span></div>
          </button>
        </div>
      </nav>

      <div class="main-col">
        <div v-if="!selectedKey" class="hint-panel"><UiEmpty icon="BookOpen" title="从左侧选择一个会话查看消息" /></div>
        <template v-else>
          <div class="filter-bar">
            <span class="mono selected-id">{{ selectedKey }}</span>
            <input v-model="keyword" placeholder="按内容关键词过滤" class="filter-input" @keyup.enter="reload" />
            <UiButton icon="Search" :loading="loadingMessages" @click="reload">查询</UiButton>
            <UiButton v-if="keyword" variant="ghost" icon="X" @click="clearKeyword">清空</UiButton>
          </div>
          <p v-if="loadError" class="error">{{ loadError }}</p>
          <div class="messages-panel">
            <UiLoading v-if="loadingMessages && !messages.length" />
            <UiEmpty v-else-if="!messages.length" icon="BookOpen" title="没有匹配的消息" />
            <div v-else class="messages-scroll">
              <div v-for="m in messages" :key="m.id" class="msg" :class="`msg--${m.role}`">
                <div class="msg-head">
                  <UiTag size="sm" :variant="roleVariant(m.role)">{{ m.role }}</UiTag>
                  <span v-if="m.sender_name" class="sender">{{ m.sender_name }}</span>
                  <span v-else-if="m.user_id" class="mono sender">uid {{ m.user_id }}</span>
                  <span v-if="m.canonical_name && m.canonical_name !== m.sender_name" class="canonical">（{{ m.canonical_name }}）</span>
                  <span class="mono msg-id">#{{ m.id }}</span>
                  <span class="msg-time">{{ formatTime(m.created_at) }}</span>
                  <button class="msg-delete" title="删除此条" @click="onDelete(m)"><UiIcon name="Trash2" :size="13" /></button>
                </div>
                <div class="msg-body">{{ m.content }}</div>
              </div>
              <div class="load-more">
                <UiButton v-if="hasMore" :loading="loadingMore" icon="ChevronUp" @click="loadMore">加载更早</UiButton>
                <span v-else class="muted">已到最早</span>
              </div>
            </div>
          </div>
        </template>
      </div>
    </div>
  </div>
</template>

<script setup lang="ts">
import { ref } from 'vue'
import UiPageHeader from '../components/ui/UiPageHeader.vue'
import UiButton from '../components/ui/UiButton.vue'
import UiTag from '../components/ui/UiTag.vue'
import UiIcon from '../components/ui/UiIcon.vue'
import UiLoading from '../components/ui/UiLoading.vue'
import UiEmpty from '../components/ui/UiEmpty.vue'
import { listConversations, fetchMessages, deleteMessage } from '../api/conversations'
import { toast } from '../toast'

const PAGE_SIZE = 50
const conversations = ref<any[]>([]); const listing = ref(false); const listError = ref<string | null>(null)
const selectedKey = ref(''); const keyword = ref(''); const messages = ref<any[]>([])
const loadingMessages = ref(false); const loadingMore = ref(false); const loadError = ref<string | null>(null); const hasMore = ref(false)

function typeLabel(type: string): string { return { group: '群聊', private: '私聊', archive: '归档' }[type] || type }
function typeVariant(type: string): string { return { group: 'info', private: 'success', archive: 'warn' }[type] || 'info' }
function roleVariant(role: string): string { return { user: 'info', assistant: 'success', system: 'warn', tool: 'warn' }[role] || 'info' }
function displayGroupId(conv: any): string { if (conv.type === 'private') return conv.group_id.slice('private:'.length); if (conv.type === 'archive') return conv.group_id.slice('archive:'.length); return conv.group_id }
function formatTime(iso: string): string { if (!iso) return ''; const d = new Date(iso); if (Number.isNaN(d.getTime())) return iso; const pad = (n: number) => String(n).padStart(2, '0'); return `${d.getFullYear()}-${pad(d.getMonth() + 1)}-${pad(d.getDate())} ${pad(d.getHours())}:${pad(d.getMinutes())}` }

async function loadConversations() { listing.value = true; listError.value = null; try { const data = await listConversations(); conversations.value = data.conversations || [] } catch (e: unknown) { listError.value = (e as Error).message } finally { listing.value = false } }
async function selectConversation(groupKey: string) { if (groupKey === selectedKey.value) return; selectedKey.value = groupKey; keyword.value = ''; await reload() }
async function reload() { if (!selectedKey.value) return; loadingMessages.value = true; loadError.value = null; messages.value = []; hasMore.value = false; try { const data = await fetchMessages(selectedKey.value, { keyword: keyword.value || undefined, limit: PAGE_SIZE }); messages.value = data.messages || []; hasMore.value = !!data.has_more } catch (e: unknown) { loadError.value = (e as Error).message } finally { loadingMessages.value = false } }
async function loadMore() { if (!messages.value.length) return; loadingMore.value = true; try { const data = await fetchMessages(selectedKey.value, { beforeId: messages.value[messages.value.length - 1].id, keyword: keyword.value || undefined, limit: PAGE_SIZE }); messages.value.push(...(data.messages || [])); hasMore.value = !!data.has_more } catch (e: unknown) { toast((e as Error).message, 'error') } finally { loadingMore.value = false } }
function clearKeyword() { keyword.value = ''; reload() }
async function onDelete(m: any) { if (!confirm(`删除消息 #${m.id}？`)) return; try { await deleteMessage(selectedKey.value, m.id); messages.value = messages.value.filter(x => x.id !== m.id); toast('已删除') } catch (e: unknown) { toast((e as Error).message, 'error') } }
loadConversations()
</script>

<style scoped>
.conv-view { display: flex; flex-direction: column; flex: 1; min-height: 0; overflow: hidden; }
.error { color: var(--qq-danger); }
.muted { color: var(--qq-text-muted); font-size: var(--qq-text-sm); }
.mono { font-family: var(--qq-font-mono); }

.split { display: flex; gap: var(--qq-gap-md); flex: 1; min-height: 0; }

.list-panel { width: 260px; flex-shrink: 0; background: var(--qq-surface); border-radius: var(--qq-radius-card); box-shadow: var(--qq-shadow-card); display: flex; flex-direction: column; overflow: hidden; }
.list-scroll { overflow-y: auto; flex: 1; }

.list-item { display: block; width: 100%; text-align: left; padding: var(--qq-gap-sm) var(--qq-gap-md); border: none; border-radius: 0; background: transparent; cursor: pointer; font-family: var(--qq-font-base); transition: background var(--qq-transition-fast); }
.list-item:hover { background: var(--qq-surface-hover); }
.list-item.active { background: var(--qq-primary-soft); border-left: 3px solid var(--qq-primary); }
.list-item-head { display: flex; align-items: center; gap: var(--qq-gap-xs); margin-bottom: 2px; }
.list-item-id { color: var(--qq-text); font-size: var(--qq-text-sm); }
.list-item-meta { font-size: var(--qq-text-xs); color: var(--qq-text-muted); display: flex; gap: 4px; }

.main-col { display: flex; flex-direction: column; flex: 1; min-width: 0; min-height: 0; gap: var(--qq-gap-sm); }
.hint-panel { flex: 1; display: flex; align-items: center; justify-content: center; background: var(--qq-surface); border-radius: var(--qq-radius-card); box-shadow: var(--qq-shadow-card); }

.filter-bar { display: flex; align-items: center; gap: var(--qq-gap-sm); padding: var(--qq-gap-sm) var(--qq-gap-md); background: var(--qq-surface); border-radius: var(--qq-radius-card); box-shadow: var(--qq-shadow-card); flex-wrap: wrap; }
.selected-id { font-size: var(--qq-text-sm); color: var(--qq-text-muted); white-space: nowrap; }
.filter-input { flex: 1; min-width: 180px; }

.messages-panel { flex: 1; min-height: 0; background: var(--qq-surface); border-radius: var(--qq-radius-card); box-shadow: var(--qq-shadow-card); overflow: hidden; display: flex; flex-direction: column; }
.messages-scroll { overflow-y: auto; flex: 1; padding: var(--qq-gap-sm); display: flex; flex-direction: column; gap: 6px; }

.msg { padding: 10px 12px; border-radius: var(--qq-radius-sm); background: var(--qq-surface-strong); border-left: 3px solid var(--qq-border); }
.msg--user { border-left-color: var(--qq-primary); }
.msg--assistant { border-left-color: var(--qq-success); }
.msg--system, .msg--tool { border-left-color: var(--qq-warn); }
.msg-head { display: flex; align-items: center; gap: var(--qq-gap-xs); font-size: var(--qq-text-xs); margin-bottom: 4px; flex-wrap: wrap; }
.sender { font-weight: 500; color: var(--qq-text); }
.canonical { color: var(--qq-text-muted); }
.msg-id { color: var(--qq-text-muted); }
.msg-time { color: var(--qq-text-muted); margin-left: auto; }
.msg-delete { background: transparent; border: none; color: var(--qq-text-muted); cursor: pointer; padding: 2px 4px; border-radius: var(--qq-radius-sm); transition: all var(--qq-transition-fast); }
.msg-delete:hover { color: var(--qq-danger); background: var(--qq-danger-soft); }
.msg-body { font-size: var(--qq-text-sm); color: var(--qq-text); line-height: 1.6; white-space: pre-wrap; word-break: break-word; }
.load-more { display: flex; justify-content: center; padding: var(--qq-gap-sm); }

@media (max-width: 900px) { .split { flex-direction: column; } .list-panel { width: 100%; max-height: 200px; } }
</style>
