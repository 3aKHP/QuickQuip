<template>
  <div>
    <UiPageHeader title="调度器监控" subtitle="Bot 进程 Cron 任务的调度状态与最近执行结果（只读）；群聊定时消息在「定时消息」页管理"><template #actions><UiButton icon="RefreshCw" :disabled="loading" @click="loadJobs">刷新</UiButton></template></UiPageHeader>
    <p v-if="loadError" class="error">{{ loadError }}</p>
    <UiSkeleton v-if="loading && !jobs.length" variant="table" :rows="6" />
    <UiCard v-if="!loading && jobs.length" padding="none" shadow="sm">
      <div class="table-scroll"><table class="job-table"><thead><tr><th>任务名称</th><th>触发器<UiInfoTip text="三种触发方式：cron = 周期表达式；interval = 固定间隔秒数；date = 一次性定点时刻。" /></th><th>下次执行</th><th>上次执行</th><th>状态<UiInfoTip text="上次执行结果，由 bot 进程在每次任务跑完后记录：正常 / 失败（悬停标签可看见报错）/ 未执行（job 自登记以来还没触发过）。" /></th></tr></thead><tbody><tr v-for="job in jobs" :key="job.id"><td class="name-cell">{{ job.name }}</td><td class="mono">{{ formatTrigger(job.trigger) }}</td><td class="mono">{{ formatTime(job.next_run) }}</td><td class="mono">{{ formatTime(job.last_run) }}</td><td><UiTag v-if="job.last_status === 'ok'" size="sm" variant="success">正常</UiTag><UiTag v-else-if="job.last_status === 'error'" size="sm" variant="danger" :title="job.last_error || ''">失败</UiTag><span v-else-if="!job.last_status && !job.last_run" class="no-data">未执行</span><span v-else class="no-data">&mdash;</span></td></tr></tbody></table></div>
    </UiCard>
    <UiEmpty v-else-if="!loading" icon="Clock" :title="emptyTitle" :description="emptyDescription" />
    <div v-if="jobs.length || snapshotAt" class="refresh"><UiIcon name="RefreshCw" :size="12" /><span>每 30 秒自动刷新，快照时间 {{ snapshotText }}</span><UiInfoTip text="数据来自 bot 进程定期写入的状态文件：生产部署下 Web 与 bot 是两个进程，只能读文件。" /><span v-if="snapshotStale" class="stale">快照超过 5 分钟未更新，bot 进程可能未运行</span></div>
  </div>
</template>

<script setup lang="ts">
import { computed, onMounted, onUnmounted, ref } from 'vue'
import UiPageHeader from '../components/ui/UiPageHeader.vue'; import UiButton from '../components/ui/UiButton.vue'; import UiCard from '../components/ui/UiCard.vue'; import UiTag from '../components/ui/UiTag.vue'; import UiIcon from '../components/ui/UiIcon.vue'; import UiEmpty from '../components/ui/UiEmpty.vue'; import UiSkeleton from '../components/ui/UiSkeleton.vue'; import UiInfoTip from '../components/ui/UiInfoTip.vue'
import { fetchCronDashboard, type CronJob } from '../api/cronDashboard'

const jobs = ref<CronJob[]>([]); const loading = ref(false); const loadError = ref<string | null>(null); const snapshotAt = ref<string | null>(null)
const POLL_INTERVAL = 30_000; const POLL_BACKOFF_CAP = 120_000
let _timer: ReturnType<typeof setTimeout> | null = null; let _failures = 0; let _stopped = false

function formatTime(iso: string | null): string { if (!iso) return '—'; try { const d = new Date(iso); const pad = (n: number) => String(n).padStart(2, '0'); return `${d.getFullYear()}-${pad(d.getMonth() + 1)}-${pad(d.getDate())} ${pad(d.getHours())}:${pad(d.getMinutes())}:${pad(d.getSeconds())}` } catch { return iso } }
function formatTrigger(raw: string): string { const m = raw.match(/^cron\[(.*)\]$/); return m ? m[1] : raw }

const snapshotText = computed(() => snapshotAt.value ? formatTime(snapshotAt.value) : '—')
// nowTick 随每轮 loadJobs 推进，让 snapshotStale 在页面存活期间也能随时间翻转
const nowTick = ref(Date.now())
const snapshotStale = computed(() => { if (!snapshotAt.value) return false; const t = new Date(snapshotAt.value).getTime(); return Number.isFinite(t) && nowTick.value - t > 5 * 60_000 })

// 空态区分「真无任务」与「取不到数」：快照缺失/过期都指向 bot 进程侧问题，而非任务清单为空
const emptyTitle = computed(() => !snapshotAt.value ? 'Bot 尚未上报调度快照' : snapshotStale.value ? '调度快照已过期' : '暂无调度任务')
const emptyDescription = computed(() => {
  if (!snapshotAt.value) return '数据来自 Bot 进程定期写入的状态文件；Bot 未运行或从未产生快照时这里为空，启动 Bot 后任务清单会自动出现。'
  if (snapshotStale.value) return '快照超过 5 分钟未更新，Bot 进程可能未运行；此处展示的是最后一次快照的内容（无任务记录）。'
  return 'Bot 调度器快照正常：当前没有登记的 Cron 任务。'
})

async function loadJobs() { loading.value = true; loadError.value = null; try { const d = await fetchCronDashboard(); jobs.value = d.jobs || []; snapshotAt.value = d.updated_at ?? null; _failures = 0 } catch (e: unknown) { loadError.value = (e as Error).message; _failures += 1 } finally { nowTick.value = Date.now(); loading.value = false } }
function scheduleNext() { if (!_stopped) _timer = setTimeout(tick, Math.min(POLL_INTERVAL * 2 ** _failures, POLL_BACKOFF_CAP)) }
async function tick() { if (!document.hidden) await loadJobs(); scheduleNext() } // 隐藏标签页跳过本轮，节拍本身保持
onMounted(() => { _stopped = false; void loadJobs().then(scheduleNext) })
onUnmounted(() => { _stopped = true; if (_timer) { clearTimeout(_timer); _timer = null } })
</script>

<style scoped>
.error { color: var(--qq-danger); }
.job-table { background: var(--qq-surface); }
.name-cell { font-weight: 500; }
.mono { font-family: var(--qq-font-mono); font-size: 12px; color: var(--qq-text-muted); }
.no-data { color: var(--qq-text-muted); }
.refresh { display: flex; align-items: center; gap: 6px; font-size: 11px; color: var(--qq-text-muted); margin-top: var(--qq-gap-md); }
.stale { color: var(--qq-danger); }
</style>
