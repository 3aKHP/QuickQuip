<template>
  <div class="audit-view">
    <UiPageHeader title="审计日志" subtitle="Web 管理后台所有变更操作的审计记录" />
    <UiStatStrip v-if="!loading" :items="stripItems" />
    <div class="fbar">
      <div class="f"><label>操作类型</label><select v-model="filters.action"><option value="">全部</option><option value="create">create</option><option value="update">update</option><option value="delete">delete</option><option value="toggle">toggle</option></select></div>
      <div class="f"><label>目标类型</label><select v-model="filters.target_type"><option value="">全部</option><option value="rule">rule</option><option value="group">group</option><option value="memory">memory</option><option value="persona">persona</option><option value="config">config</option><option value="llm_about">llm_about</option><option value="group_setting">group_setting</option></select></div>
      <div class="f"><label>起始</label><input v-model="filters.since" type="date" /></div>
      <div class="f"><label>结束</label><input v-model="filters.until" type="date" /></div>
      <div class="f f-act"><UiButton icon="Search" @click="search">查询</UiButton><UiButton variant="ghost" size="sm" icon="RefreshCw" @click="reset">重置</UiButton></div>
    </div>
    <UiCard padding="md" shadow="sm">
      <UiSkeleton v-if="loading" variant="table" :rows="8" />
      <div v-else-if="error" class="err">{{ error }}</div>
      <template v-else-if="items.length > 0">
        <div class="table-scroll"><table class="audit-table"><thead><tr><th>时间</th><th>操作者</th><th>操作</th><th>目标类型</th><th>目标 ID</th></tr></thead><tbody><template v-for="entry in items" :key="entry.id"><tr class="ar" @click="tg(entry.id)"><td class="col-t">{{ entry.timestamp }}</td><td class="mono">{{ entry.operator }}</td><td><UiTag size="sm" :variant="av(entry.action)">{{ entry.action }}</UiTag></td><td><UiTag size="sm" :variant="tv(entry.target_type)">{{ entry.target_type }}</UiTag></td><td class="mono col-tid">{{ entry.target_id }}</td></tr><tr v-if="exp.has(entry.id)"><td colspan="5"><div class="sum-panels"><div v-if="entry.summary_before" class="sp sp-before"><span class="sl">变更前</span><pre class="json">{{ pj(entry.summary_before) }}</pre></div><div v-if="entry.summary_after" class="sp sp-after"><span class="sl">变更后</span><pre class="json">{{ pj(entry.summary_after) }}</pre></div><div v-if="!entry.summary_before && !entry.summary_after" class="no-sum">无摘要</div></div></td></tr></template></tbody></table></div>
        <div class="pager"><UiButton size="sm" variant="ghost" icon="ChevronLeft" :disabled="page <= 1" @click="go(page - 1)" /><span class="mono page-info">{{ page }} / {{ totalPages }} ({{ total }} 条)</span><UiButton size="sm" variant="ghost" icon="ChevronRight" :disabled="page >= totalPages" @click="go(page + 1)" /></div>
      </template>
      <UiEmpty v-else icon="ShieldCheck" title="暂无审计记录" />
    </UiCard>
  </div>
</template>

<script setup lang="ts">
import { onMounted, ref, reactive, computed } from 'vue'
import UiPageHeader from '../components/ui/UiPageHeader.vue'; import UiButton from '../components/ui/UiButton.vue'; import UiCard from '../components/ui/UiCard.vue'; import UiTag from '../components/ui/UiTag.vue'; import UiLoading from '../components/ui/UiLoading.vue'; import UiEmpty from '../components/ui/UiEmpty.vue'; import UiSkeleton from '../components/ui/UiSkeleton.vue'; import UiStatStrip from '../components/ui/UiStatStrip.vue'
import { fetchAuditEntries, type AuditEntry, type AuditQueryParams } from '../api/audit'

const loading = ref(true); const error = ref<string | null>(null); const items = ref<AuditEntry[]>([]); const total = ref(0); const page = ref(1); const limit = 50; const exp = ref(new Set<number>())

const stripItems = computed(() => [
  { label: '记录总数', value: total.value, icon: 'ShieldCheck' },
  { label: '当前页条数', value: items.value.length, icon: 'FileText' },
])
const filters = reactive<AuditQueryParams>({ action: '', target_type: '', since: '', until: '' })
const totalPages = computed(() => Math.max(1, Math.ceil(total.value / limit)))
function av(a: string) { return ({ create: 'success', update: 'info', delete: 'danger', toggle: 'warn' } as any)[a] || 'info' }
function tv(t: string) { return ({ rule: 'warn', group: 'info', memory: 'success', config: 'danger', llm_about: 'success', group_setting: 'warn' } as any)[t] || 'info' }
function pj(o: unknown) { try { return JSON.stringify(o, null, 2) } catch { return String(o) } }
function tg(id: number) { const n = new Set(exp.value); n.has(id) ? n.delete(id) : n.add(id); exp.value = n }
async function load() { loading.value = true; error.value = null; try { const p: AuditQueryParams = { page: page.value, limit }; if (filters.action) p.action = filters.action; if (filters.target_type) p.target_type = filters.target_type; if (filters.since) p.since = filters.since + 'T00:00:00'; if (filters.until) p.until = filters.until + 'T23:59:59'; const d = await fetchAuditEntries(p); items.value = d.items; total.value = d.total } catch (e: unknown) { error.value = (e as Error).message } finally { loading.value = false } }
function search() { page.value = 1; exp.value = new Set(); load() }
function reset() { filters.action = ''; filters.target_type = ''; filters.since = ''; filters.until = ''; page.value = 1; exp.value = new Set(); load() }
function go(p: number) { if (p < 1 || p > totalPages.value) return; page.value = p; exp.value = new Set(); load() }
onMounted(() => load())
</script>

<style scoped>
.audit-view { display: flex; flex-direction: column; flex: 1; min-height: 0; }
.fbar { display: flex; gap: var(--qq-gap-sm); flex-wrap: wrap; align-items: flex-end; margin-bottom: var(--qq-gap-lg); padding: var(--qq-gap-sm) var(--qq-gap-md); background: var(--qq-surface); border-radius: var(--qq-radius-card); box-shadow: var(--qq-shadow-card); }
.f { display: flex; flex-direction: column; gap: 4px; }
.f label { font-size: 11px; color: var(--qq-text-muted); font-weight: 500; }
.f-act { display: flex; flex-direction: row; gap: var(--qq-gap-xs); align-items: flex-end; }
.mono { font-family: var(--qq-font-mono); }
.col-t { white-space: nowrap; font-family: var(--qq-font-mono); font-size: var(--qq-text-xs); color: var(--qq-text-muted); }
.col-tid { font-family: var(--qq-font-mono); font-size: var(--qq-text-xs); max-width: 200px; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
.ar { cursor: pointer; }
.sum-panels { display: flex; gap: var(--qq-gap-sm); flex-wrap: wrap; padding: var(--qq-gap-sm) 0; animation: audit-expand 200ms var(--qq-ease-out); }
@keyframes audit-expand {
  from { opacity: 0; transform: translateY(-4px); }
  to { opacity: 1; transform: translateY(0); }
}
@media (prefers-reduced-motion: reduce) {
  .sum-panels { animation: none; }
}
.sp { flex: 1; min-width: 200px; }
.sl { font-size: var(--qq-text-xs); font-weight: 500; color: var(--qq-text-muted); }
.sp-before .sl { color: var(--qq-warn); }
.sp-after .sl { color: var(--qq-success); }
.json { padding: var(--qq-gap-sm); background: var(--qq-surface-strong); border-radius: var(--qq-radius-sm); font-size: 11px; font-family: var(--qq-font-mono); line-height: 1.4; overflow-x: auto; white-space: pre; color: var(--qq-text-muted); max-height: 200px; overflow-y: auto; }
.no-sum { font-size: var(--qq-text-xs); color: var(--qq-text-muted); }
.err { color: var(--qq-danger); font-size: var(--qq-text-sm); }
.pager { display: flex; align-items: center; justify-content: center; gap: var(--qq-gap-sm); padding-top: var(--qq-gap-sm); border-top: 1px solid var(--qq-border); margin-top: var(--qq-gap-sm); }
.page-info { font-size: var(--qq-text-xs); color: var(--qq-text-muted); }
</style>
