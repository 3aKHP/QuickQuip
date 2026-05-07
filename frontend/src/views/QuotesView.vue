<template>
  <div>
    <UiPageHeader title="语录管理" subtitle="按群组浏览、搜索、管理名言语录" />

    <p v-if="loadError" class="error">{{ loadError }}</p>

    <!-- Group selector -->
    <UiCard padding="md" shadow="sm" class="section">
      <h3 class="st">群组</h3>
      <div class="lookup">
        <select v-model="selectedGroup" @change="loadQuotes" class="group-select">
          <option value="">请选择群组</option>
          <option v-for="g in groups" :key="g.group_id" :value="g.group_id">
            {{ g.group_id }}（{{ g.count }} 条）
          </option>
        </select>
        <UiButton icon="RefreshCw" :loading="groupLoading" @click="loadGroups" />
      </div>
    </UiCard>

    <template v-if="selectedGroup">
      <!-- Search -->
      <UiCard padding="md" shadow="sm" class="section">
        <div class="toolbar">
          <h3 class="st">语录（共 {{ total }} 条）</h3>
          <div class="search-row">
            <input v-model="keyword" placeholder="搜索关键词…" class="search-input" @keyup.enter="search" />
            <UiButton icon="Search" :loading="loading" @click="search">搜索</UiButton>
            <UiButton v-if="keyword" size="sm" @click="clearSearch">清除</UiButton>
          </div>
        </div>

        <UiLoading v-if="loading && !entries.length" />
        <UiEmpty v-else-if="!entries.length" icon="FileText" :title="keyword ? '无匹配语录' : '暂无语录'" />

        <table v-else class="data-table">
          <thead>
            <tr>
              <th class="num">#</th>
              <th>内容</th>
              <th>发言人</th>
              <th>时间</th>
              <th class="act">操作</th>
            </tr>
          </thead>
          <tbody>
            <tr v-for="q in entries" :key="q.id">
              <td class="num">{{ q.group_seq }}</td>
              <td class="content-cell">
                <span class="quote-text">{{ q.content }}</span>
              </td>
              <td class="sender">{{ q.quoted_sender_name }}</td>
              <td class="time">{{ formatTime(q.saved_at) }}</td>
              <td class="act">
                <UiButton size="sm" variant="danger" icon="Trash2" @click="doDelete(q)">删除</UiButton>
              </td>
            </tr>
          </tbody>
        </table>

        <div v-if="hasMore && entries.length" class="load-more">
          <UiButton :loading="loading" @click="loadMore">加载更多</UiButton>
        </div>
      </UiCard>
    </template>
  </div>
</template>

<script setup lang="ts">
import { onMounted, ref } from 'vue'
import UiPageHeader from '../components/ui/UiPageHeader.vue'
import UiCard from '../components/ui/UiCard.vue'
import UiButton from '../components/ui/UiButton.vue'
import UiLoading from '../components/ui/UiLoading.vue'
import UiEmpty from '../components/ui/UiEmpty.vue'
import { listGroups, listQuotes, deleteQuote } from '../api/quotes'
import { toast } from '../toast'

const loadError = ref<string | null>(null)
const groupLoading = ref(false)
const groups = ref<any[]>([])
const selectedGroup = ref('')
const loading = ref(false)
const entries = ref<any[]>([])
const total = ref(0)
const hasMore = ref(false)
const keyword = ref('')
const offset = ref(0)
const pageSize = 50

onMounted(() => loadGroups())

async function loadGroups() {
  groupLoading.value = true
  try {
    const data = await listGroups()
    groups.value = data.groups || []
  } catch (e: any) { loadError.value = e.message || String(e) }
  finally { groupLoading.value = false }
}

async function loadQuotes(reset: boolean = true) {
  if (!selectedGroup.value) return
  if (reset) { offset.value = 0; entries.value = [] }
  loading.value = true
  try {
    const data = await listQuotes(selectedGroup.value, offset.value, pageSize, keyword.value)
    if (reset) {
      entries.value = data.entries || []
    } else {
      entries.value = [...entries.value, ...(data.entries || [])]
    }
    total.value = data.total || 0
    hasMore.value = data.has_more || false
  } catch (e: any) { loadError.value = e.message || String(e) }
  finally { loading.value = false }
}

function search() {
  offset.value = 0
  entries.value = []
  loadQuotes(true)
}

function clearSearch() {
  keyword.value = ''
  search()
}

function loadMore() {
  offset.value += pageSize
  loadQuotes(false)
}

async function doDelete(q: any) {
  if (!confirm(`确定删除 #${q.group_seq}「${q.content.slice(0, 20)}…」？`)) return
  try {
    await deleteQuote(q.id)
    entries.value = entries.value.filter(e => e.id !== q.id)
    total.value = Math.max(0, total.value - 1)
    toast('已删除')
  } catch (e: any) { toast(e.message || '删除失败', 'error') }
}

function formatTime(ts: number): string {
  const d = new Date(ts * 1000)
  return d.toLocaleDateString('zh-CN', { month: '2-digit', day: '2-digit' })
}
</script>

<style scoped>
.error { color: var(--qq-danger); }
.section { margin-bottom: var(--qq-gap-md); }
.st { margin: 0; font-size: var(--qq-text-base); color: var(--qq-text); }
.lookup { display: flex; align-items: center; gap: var(--qq-gap-md); margin-top: var(--qq-gap-sm); }
.group-select {
  flex: 1; max-width: 320px;
  background: var(--qq-surface-strong);
  border: 1px solid var(--qq-border);
  border-radius: var(--qq-radius-sm);
  color: var(--qq-text);
  padding: 6px 10px;
  font-size: var(--qq-text-sm);
  outline: none;
}
.toolbar { display: flex; align-items: center; gap: var(--qq-gap-md); flex-wrap: wrap; }
.search-row { display: flex; align-items: center; gap: var(--qq-gap-sm); margin-left: auto; }
.search-input {
  width: 180px;
  background: var(--qq-surface-strong);
  border: 1px solid var(--qq-border);
  border-radius: var(--qq-radius-sm);
  color: var(--qq-text);
  padding: 5px 10px;
  font-size: var(--qq-text-sm);
  outline: none;
}
.search-input:focus { border-color: var(--qq-accent); box-shadow: 0 0 0 3px var(--qq-accent-soft); }
.data-table { width: 100%; border-collapse: collapse; font-size: var(--qq-text-sm); margin-top: var(--qq-gap-sm); }
.data-table th { text-align: left; padding: 6px 10px; border-bottom: 2px solid var(--qq-border); color: var(--qq-text-muted); font-weight: 600; }
.data-table td { padding: 6px 10px; border-bottom: 1px solid var(--qq-border); }
.num { text-align: right; width: 40px; font-variant-numeric: tabular-nums; }
.act { width: 60px; text-align: center; }
.content-cell { max-width: 320px; }
.quote-text { display: block; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
.sender { white-space: nowrap; color: var(--qq-text-muted); font-size: var(--qq-text-xs); }
.time { white-space: nowrap; font-size: var(--qq-text-xs); color: var(--qq-text-muted); }
.load-more { margin-top: var(--qq-gap-sm); text-align: center; }
</style>
