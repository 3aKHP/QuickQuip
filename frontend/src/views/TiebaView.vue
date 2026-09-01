<template>
  <div class="tieba-view">
    <UiPageHeader title="贴吧帖子池" subtitle="只读视图，依赖 tieba 爬虫后台同步的数据">
      <template #actions>
        <UiButton icon="RefreshCw" :loading="loading" @click="loadAll">刷新</UiButton>
        <UiButton icon="Download" :loading="syncing" @click="startSync(null)">立即同步全部</UiButton>
        <UiButton icon="Radar" :disabled="!selectedForum" :loading="peeking" @click="peekSelected">现爬一条</UiButton>
      </template>
    </UiPageHeader>

    <div v-if="syncLog.length" class="sync-log-wrap">
      <div class="sync-log-head">
        <span>同步日志{{ syncing ? '（进行中…）' : '（已完成）' }}</span>
        <button class="sync-log-close" @click="clearLog"><UiIcon name="X" :size="14" /></button>
      </div>
      <pre ref="logEl" class="sync-log">{{ syncLog.join('\n') }}</pre>
    </div>

    <p v-if="loadError" class="error">{{ loadError }}</p>

    <div class="split">
      <UiCard padding="none" shadow="sm" class="forum-card">
        <UiLoading v-if="loading && !forums.length" />
        <UiEmpty v-else-if="!forums.length" icon="BookOpen" title="尚无任何贴吧缓存" />
        <ul v-else class="forum-list">
          <li v-for="f in forums" :key="f.forum_keyword" class="forum-item qq-selectable" :class="{ active: f.forum_keyword === selectedForum }" @click="selectForum(f.forum_keyword)">
            <div class="forum-head">
              <span class="forum-name">{{ f.forum_keyword }}吧</span>
              <UiTag size="sm" :variant="syncVariant(f)">{{ syncLabel(f) }}</UiTag>
              <button class="forum-sync-btn" :disabled="syncing" @click.stop="startSync(f.forum_keyword)" title="立即同步此吧">
                <UiIcon name="Download" :size="12" />
              </button>
            </div>
            <div class="forum-meta">
              <span>{{ f.count }} 条</span>
              <span v-if="f.last_sync_completed_at"> · {{ formatTime(f.last_sync_completed_at) }}</span>
            </div>
            <div v-if="f.last_error" class="forum-error" :title="f.last_error">{{ f.last_error }}</div>
          </li>
        </ul>
      </UiCard>

      <div class="main-col">
        <UiCard v-if="!selectedForum" padding="lg" shadow="sm" class="hint-card">
          <UiEmpty icon="BookOpen" title="从左侧选择一个贴吧查看帖子" />
        </UiCard>

        <template v-else>
          <UiCard padding="md" shadow="sm" class="filter-card">
            <div class="filter-row">
              <span class="selected-forum">{{ selectedForum }}吧 · {{ total }} 条</span>
              <input v-model="keyword" placeholder="标题/正文/作者关键词" @keyup.enter="reload" />
              <UiButton icon="Search" :loading="loadingThreads" @click="reload">查询</UiButton>
              <UiButton v-if="keyword" variant="ghost" icon="X" @click="clearKeyword">清空</UiButton>
            </div>
          </UiCard>

          <UiCard padding="none" shadow="sm" class="threads-card">
            <UiLoading v-if="loadingThreads && !threads.length" />
            <UiEmpty v-else-if="!threads.length" icon="BookOpen" title="没有匹配的帖子" />
            <div v-else class="threads">
              <div v-for="t in threads" :key="t.tid" class="thread" :class="{ selected: t.tid === detail?.tid }" @click="openDetail(t.tid)">
                <div class="thread-row">
                  <img v-if="t.cover_image_url" :src="tiebaImgProxyUrl(t.cover_image_url)" class="thread-cover" loading="lazy" />
                  <div class="thread-body">
                    <div class="thread-title">
                      <span class="title-text">{{ t.title }}</span>
                      <UiTag v-if="t.was_sent" size="sm" variant="success">已发送过</UiTag>
                      <UiTag v-if="t.is_deleted" size="sm" variant="danger">已删除</UiTag>
                      <UiTag v-if="t.image_count" size="sm">{{ t.image_count }} 图</UiTag>
                    </div>
                    <div class="thread-meta">
                      <span class="mono">#{{ t.tid }}</span>
                      <span v-if="t.author_name">· {{ t.author_name }}</span>
                      <span>· {{ formatTime(t.last_seen_at) }}</span>
                    </div>
                    <div v-if="t.preview" class="thread-preview">{{ t.preview }}</div>
                  </div>
                </div>
              </div>
              <div class="load-more-wrap">
                <UiButton v-if="hasMore" :loading="loadingMore" icon="ChevronDown" @click="loadMore">加载更多</UiButton>
                <span v-else-if="threads.length" class="muted">已到末尾</span>
              </div>
            </div>
          </UiCard>
        </template>
      </div>
    </div>

    <ThreadDetailDialog v-if="detail" :detail="detail" @close="detail = null" />
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
import ThreadDetailDialog from '../components/tieba/ThreadDetailDialog.vue'
import { listTiebaForums, fetchTiebaThreads, fetchTiebaThread, tiebaImgProxyUrl, peekTiebaThread } from '../api/tieba'
import type { TiebaForumInfo, TiebaThread, TiebaThreadRow } from '../api/tieba'
import { useTiebaSync } from '../composables/useTiebaSync'
import { toast } from '../toast'

const PAGE_SIZE = 30

const forums = ref<TiebaForumInfo[]>([])
const loading = ref(false)
const loadError = ref<string | null>(null)

const peeking = ref(false)

const selectedForum = ref('')
const keyword = ref('')
const threads = ref<TiebaThreadRow[]>([])
const total = ref(0)
const hasMore = ref(false)
const loadingThreads = ref(false)
const loadingMore = ref(false)

const detail = ref<TiebaThread | null>(null)

const STATUS_MAP: Record<string, string> = { ok: '正常', running: '同步中', error: '错误', idle: '未同步' }
const VARIANT_MAP: Record<string, string> = { ok: 'success', running: 'info', error: 'danger', idle: 'info' }

function syncLabel(f: TiebaForumInfo): string {
  if (f.login_required) return '需登录'
  return STATUS_MAP[f.last_sync_status] || f.last_sync_status
}

function syncVariant(f: TiebaForumInfo): string {
  if (f.login_required) return 'warn'
  return VARIANT_MAP[f.last_sync_status] || 'info'
}

function formatTime(ts: number): string {
  if (!ts) return ''
  const d = new Date(ts * 1000)
  if (Number.isNaN(d.getTime())) return ''
  const pad = (n: number) => String(n).padStart(2, '0')
  return `${d.getFullYear()}-${pad(d.getMonth() + 1)}-${pad(d.getDate())} ${pad(d.getHours())}:${pad(d.getMinutes())}`
}

async function loadAll() {
  loading.value = true
  loadError.value = null
  try {
    const data = await listTiebaForums()
    forums.value = data.forums || []
    if (selectedForum.value) await reload()
  } catch (e: unknown) {
    loadError.value = (e as Error).message
  } finally {
    loading.value = false
  }
}

const { syncing, syncLog, logEl, startSync, clearLog } = useTiebaSync(loadAll)

async function selectForum(forum: string) {
  if (forum === selectedForum.value) return
  selectedForum.value = forum
  keyword.value = ''
  await reload()
}

async function reload() {
  if (!selectedForum.value) return
  loadingThreads.value = true
  threads.value = []
  total.value = 0
  hasMore.value = false
  try {
    const data = await fetchTiebaThreads(selectedForum.value, {
      keyword: keyword.value || undefined,
      limit: PAGE_SIZE,
      offset: 0,
    })
    threads.value = data.threads || []
    total.value = data.total || 0
    hasMore.value = !!data.has_more
  } catch (e: unknown) {
    toast((e as Error).message, 'error')
  } finally {
    loadingThreads.value = false
  }
}

async function loadMore() {
  if (!hasMore.value) return
  loadingMore.value = true
  try {
    const data = await fetchTiebaThreads(selectedForum.value, {
      keyword: keyword.value || undefined,
      limit: PAGE_SIZE,
      offset: threads.value.length,
    })
    threads.value.push(...(data.threads || []))
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

async function openDetail(tid: string) {
  try {
    detail.value = await fetchTiebaThread(selectedForum.value, tid)
  } catch (e: unknown) {
    toast((e as Error).message, 'error')
  }
}

async function peekSelected() {
  if (!selectedForum.value) return
  peeking.value = true
  try {
    detail.value = await peekTiebaThread(selectedForum.value)
    toast('现爬完成')
  } catch (e: unknown) {
    toast((e as Error).message, 'error', 4000)
  } finally {
    peeking.value = false
  }
}

loadAll()
</script>

<style scoped>
.tieba-view {
  display: flex;
  flex-direction: column;
  flex: 1;
  min-height: 0;
}

.error { color: var(--qq-danger); }
.muted { color: var(--qq-text-muted); font-size: var(--qq-text-sm); }
.mono { font-family: var(--qq-font-mono); }

.split {
  display: flex;
  gap: var(--qq-gap-md);
  flex: 1;
  min-height: 0;
}

.forum-card {
  width: 260px;
  flex-shrink: 0;
  overflow-y: auto;
  max-height: calc(100vh - 180px);
}

.forum-list { list-style: none; margin: 0; padding: 0; }

.forum-item {
  padding: var(--qq-gap-sm) var(--qq-gap-md);
  border-bottom: 1px solid var(--qq-border);
  cursor: pointer;
  transition: background var(--qq-transition-fast);
}

.forum-item:last-child { border-bottom: none; }

.forum-head {
  display: flex;
  align-items: center;
  gap: var(--qq-gap-xs);
  margin-bottom: 3px;
}

.forum-name {
  font-weight: 500;
  color: var(--qq-text);
  font-size: var(--qq-text-base);
}

.forum-meta {
  font-size: var(--qq-text-xs);
  color: var(--qq-text-muted);
  display: flex;
  gap: 4px;
}

.forum-sync-btn {
  background: none;
  border: none;
  cursor: pointer;
  color: var(--qq-text-muted);
  padding: 2px;
  display: flex;
  border-radius: var(--qq-radius-sm);
  margin-left: auto;
}

.forum-sync-btn:hover { color: var(--qq-primary); }
.forum-sync-btn:disabled { opacity: 0.4; cursor: not-allowed; }

.forum-error {
  margin-top: 4px;
  font-size: var(--qq-text-xs);
  color: var(--qq-danger);
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.main-col {
  display: flex;
  flex-direction: column;
  flex: 1;
  min-width: 0;
  gap: var(--qq-gap-sm);
}

.sync-log-wrap {
  border: 1px solid var(--qq-border);
  border-radius: var(--qq-radius-sm);
  margin-bottom: var(--qq-gap-sm);
  overflow: hidden;
}

.sync-log-head {
  display: flex;
  align-items: center;
  justify-content: space-between;
  padding: 4px 10px;
  background: var(--qq-surface-strong);
  font-size: var(--qq-text-xs);
  color: var(--qq-text-muted);
}

.sync-log-close {
  background: none;
  border: none;
  cursor: pointer;
  color: var(--qq-text-muted);
  padding: 0;
  display: flex;
}

.sync-log {
  margin: 0;
  padding: var(--qq-gap-sm) 10px;
  font-size: var(--qq-text-xs);
  font-family: var(--qq-font-mono);
  line-height: 1.6;
  max-height: 220px;
  overflow-y: auto;
  background: var(--qq-surface);
  white-space: pre-wrap;
  word-break: break-all;
}

.hint-card {
  flex: 1;
  display: flex;
  align-items: center;
  justify-content: center;
}

.filter-card { flex-shrink: 0; }

.filter-row {
  display: flex;
  align-items: center;
  gap: var(--qq-gap-sm);
  flex-wrap: wrap;
}

.selected-forum { font-size: var(--qq-text-sm); color: var(--qq-text-muted); }

.filter-row input {
  background: var(--qq-surface-strong);
  border: 1px solid var(--qq-border);
  border-radius: var(--qq-radius-sm);
  color: var(--qq-text);
  padding: 5px 10px;
  font-size: var(--qq-text-base);
  font-family: var(--qq-font-base);
  outline: none;
  flex: 1;
  min-width: 200px;
}

.filter-row input:focus {
  border-color: var(--qq-primary);
  box-shadow: 0 0 0 3px var(--qq-primary-soft);
}

.threads-card {
  flex: 1;
  overflow: hidden;
  display: flex;
  flex-direction: column;
  min-height: 300px;
}

.threads {
  overflow-y: auto;
  padding: var(--qq-gap-sm);
  display: flex;
  flex-direction: column;
  gap: 4px;
}

.thread {
  padding: 8px 10px;
  border-radius: var(--qq-radius-sm);
  cursor: pointer;
  transition: background var(--qq-transition-fast);
  border: 1px solid transparent;
}

.thread:hover { background: var(--qq-surface-elevated); }
.thread.selected {
  background: var(--qq-surface-elevated);
  border-color: var(--qq-primary);
}

.thread-row { display: flex; gap: var(--qq-gap-sm); }

.thread-cover {
  width: 72px;
  height: 72px;
  object-fit: cover;
  border-radius: var(--qq-radius-sm);
  flex-shrink: 0;
  background: var(--qq-surface-strong);
}

.thread-body { flex: 1; min-width: 0; }

.thread-title {
  display: flex;
  align-items: center;
  gap: var(--qq-gap-xs);
  flex-wrap: wrap;
  margin-bottom: 3px;
}

.title-text {
  font-size: var(--qq-text-base);
  color: var(--qq-text);
  font-weight: 500;
}

.thread-meta {
  font-size: var(--qq-text-xs);
  color: var(--qq-text-muted);
  display: flex;
  gap: 4px;
  margin-bottom: 4px;
}

.thread-preview {
  font-size: var(--qq-text-xs);
  color: var(--qq-text-muted);
  line-height: 1.5;
  overflow: hidden;
  display: -webkit-box;
  -webkit-line-clamp: 2;
  -webkit-box-orient: vertical;
}

.load-more-wrap {
  display: flex;
  justify-content: center;
  padding: var(--qq-gap-sm);
}

@media (max-width: 900px) {
  .split { flex-direction: column; }
  .forum-card { width: 100%; max-height: 200px; }
}
</style>
