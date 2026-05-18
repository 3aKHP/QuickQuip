<template>
  <div>
    <UiPageHeader title="定时任务" subtitle="所有 Cron 定时任务的调度状态和最近执行结果"><template #actions><UiButton icon="RefreshCw" :disabled="loading" @click="loadJobs">刷新</UiButton></template></UiPageHeader>
    <p v-if="loadError" class="error">{{ loadError }}</p>
    <UiLoading v-if="loading && !jobs.length" />
    <div v-if="!loading && jobs.length" class="table-scroll"><table class="job-table"><thead><tr><th>任务名称</th><th>触发器</th><th>下次执行</th><th>上次执行</th><th>状态</th></tr></thead><tbody><tr v-for="job in jobs" :key="job.id"><td class="name-cell">{{ job.name }}</td><td class="mono">{{ formatTrigger(job.trigger) }}</td><td class="mono">{{ formatTime(job.next_run) }}</td><td class="mono">{{ formatTime(job.last_run) }}</td><td><UiTag v-if="job.last_status === 'ok'" size="sm" variant="success">正常</UiTag><UiTag v-else-if="job.last_status === 'error'" size="sm" variant="danger" :title="job.last_error || ''">失败</UiTag><span v-else class="no-data">&mdash;</span></td></tr></tbody></table></div>
    <UiEmpty v-else-if="!loading" icon="Clock" title="暂无定时任务" />
    <div v-if="jobs.length" class="refresh"><UiIcon name="RefreshCw" :size="12" /><span>每 30 秒自动刷新，上次更新 {{ lastRefresh }}</span></div>
  </div>
</template>

<script setup lang="ts">
import { onMounted, onUnmounted, ref } from 'vue'
import UiPageHeader from '../components/ui/UiPageHeader.vue'; import UiButton from '../components/ui/UiButton.vue'; import UiTag from '../components/ui/UiTag.vue'; import UiIcon from '../components/ui/UiIcon.vue'; import UiLoading from '../components/ui/UiLoading.vue'; import UiEmpty from '../components/ui/UiEmpty.vue'
import { fetchCronDashboard, type CronJob } from '../api/cronDashboard'

const jobs = ref<CronJob[]>([]); const loading = ref(false); const loadError = ref<string | null>(null); const lastRefresh = ref(''); let _timer: ReturnType<typeof setInterval> | null = null

function formatTime(iso: string | null): string { if (!iso) return '—'; try { const d = new Date(iso); const pad = (n: number) => String(n).padStart(2, '0'); return `${d.getFullYear()}-${pad(d.getMonth() + 1)}-${pad(d.getDate())} ${pad(d.getHours())}:${pad(d.getMinutes())}:${pad(d.getSeconds())}` } catch { return iso } }
function formatTrigger(raw: string): string { const m = raw.match(/^cron\[(.*)\]$/); return m ? m[1] : raw }

async function loadJobs() { loading.value = true; loadError.value = null; try { const d = await fetchCronDashboard(); jobs.value = d.jobs || []; lastRefresh.value = formatTime(new Date().toISOString()) } catch (e: unknown) { loadError.value = (e as Error).message } finally { loading.value = false } }
onMounted(() => { loadJobs(); _timer = setInterval(loadJobs, 30_000) })
onUnmounted(() => { if (_timer) { clearInterval(_timer); _timer = null } })
</script>

<style scoped>
.error { color: var(--qq-danger); }
.table-wrap { border-radius: var(--qq-radius-card); overflow: hidden; box-shadow: var(--qq-shadow-card); }
.job-table { background: var(--qq-surface); }
.name-cell { font-weight: 500; }
.mono { font-family: var(--qq-font-mono); font-size: 12px; color: var(--qq-text-muted); }
.no-data { color: var(--qq-text-muted); }
.refresh { display: flex; align-items: center; gap: 6px; font-size: 11px; color: var(--qq-text-muted); margin-top: var(--qq-gap-md); }
</style>
