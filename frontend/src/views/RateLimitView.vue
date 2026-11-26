<template>
  <div>
    <UiPageHeader title="限流实时状态" subtitle="内存状态，重启归零。scope=全局 的规则保护外部 API/共享资源；scope=按群 的规则每个群独立分桶">
      <template #subtitle>
        <UiInfoTip text="桶名可在 chat_rules.toml 的 [rate_limit_rules] 覆写或新增；「上限 A/B」表示滑动窗口内整桶最多 A 次、单用户最多 B 次；「全局桶」由全局规则共用，「私聊/无群上下文」为按群规则兜底桶；数字与进度条变红表示已触顶。" />
      </template>
      <template #actions>
        <span v-if="updatedAt" class="updated-at">更新于 {{ updatedAt }}</span>
        <label class="auto"><input v-model="autoRefresh" type="checkbox" /><span>5s 刷新</span></label>
        <UiButton icon="RefreshCw" :loading="loading" @click="load">刷新</UiButton>
      </template>
    </UiPageHeader>

    <div v-if="loadError" class="soft-note soft-note--danger rl-banner" role="alert">{{ loadError }}</div>

    <UiStatStrip v-if="rules.length" :items="stripItems" />

    <div v-if="rules.length" class="rl-toolbar">
      <input v-model="searchQuery" type="search" placeholder="筛选桶名或群号..." class="rl-search" />
      <label class="auto">
        <input v-model="onlyActive" type="checkbox" />
        <span>仅看活跃</span>
      </label>
      <span v-if="searchQuery.trim() || onlyActive" class="muted">
        显示 {{ filteredRules.length }} / {{ rules.length }} 条规则
      </span>
    </div>

    <UiLoading v-if="loading && !rules.length" />
    <UiEmpty v-else-if="!rules.length" icon="Zap" title="无限流规则" />
    <UiEmpty v-else-if="!filteredRules.length" icon="Search" title="没有符合条件的限流规则" />
    <div v-else class="rule-grid">
      <UiCard v-for="r in filteredRules" :key="r.name" padding="md" shadow="sm" class="rule-card">
        <div class="rule-head">
          <span class="rule-name" :title="r.name">{{ r.name }}</span>
          <div class="rule-tags">
            <UiTag size="sm" :variant="r.scope === 'global' ? 'warn' : 'info'">{{ r.scope === 'global' ? '全局' : '按群' }}</UiTag>
            <span class="window">窗口 {{ r.window_seconds }}s · 上限 {{ r.global_limit }}/{{ r.user_limit }}</span>
          </div>
        </div>
        <div v-if="!r.buckets.length" class="empty"><span class="muted">当前窗口无命中</span></div>
        <div v-else class="buckets">
          <div v-for="b in r.buckets" :key="b.group_id || '__global__'" class="bucket">
            <div class="bucket-head">
              <span class="bucket-label">{{ bucketLabel(r, b) }}</span>
              <span class="mono stat"><span :class="{ sat: b.global_used >= r.global_limit }">{{ b.global_used }}</span> / {{ r.global_limit }}</span>
            </div>
            <div class="bar"><div class="bar-fill" :class="{ sat: b.global_used >= r.global_limit }" :style="{ width: pct(b.global_used, r.global_limit) + '%' }" /></div>
            <div v-if="b.top_users.length" class="top">
              <div class="top-head">活跃 {{ b.active_users }} 人</div>
              <div v-for="u in b.top_users" :key="u.user_id" class="top-row">
                <span class="mono">uid {{ u.user_id }}</span>
                <div class="mini-bar"><div class="mini-fill" :class="{ sat: u.used >= r.user_limit }" :style="{ width: pct(u.used, r.user_limit) + '%' }" /></div>
                <span class="mono used">{{ u.used }}/{{ r.user_limit }}</span>
              </div>
            </div>
          </div>
        </div>
      </UiCard>
    </div>
  </div>
</template>

<script setup lang="ts">
import { computed, onBeforeUnmount, onMounted, ref, watch } from 'vue'
import UiPageHeader from '../components/ui/UiPageHeader.vue'
import UiButton from '../components/ui/UiButton.vue'
import UiCard from '../components/ui/UiCard.vue'
import UiTag from '../components/ui/UiTag.vue'
import UiLoading from '../components/ui/UiLoading.vue'
import UiEmpty from '../components/ui/UiEmpty.vue'
import UiInfoTip from '../components/ui/UiInfoTip.vue'
import UiStatStrip from '../components/ui/UiStatStrip.vue'
import { fetchRateLimit } from '../api/rateLimit'

const rules = ref<any[]>([])
const loading = ref(false)
const loadError = ref<string | null>(null)
const autoRefresh = ref(false)
const updatedAt = ref<string | null>(null)
const searchQuery = ref('')
const onlyActive = ref(false)

let timer: ReturnType<typeof setTimeout> | null = null
let unmounted = false

const stripItems = computed(() => {
  let activeBuckets = 0
  let saturatedBuckets = 0
  for (const r of rules.value) {
    const buckets = r.buckets || []
    activeBuckets += buckets.length
    for (const b of buckets) {
      const globalSat = b.global_used >= r.global_limit
      const userSat = (b.top_users || []).some((u: any) => u.used >= r.user_limit)
      if (globalSat || userSat) saturatedBuckets++
    }
  }
  return [
    { label: '规则总数', value: rules.value.length, icon: 'Gauge' },
    { label: '活跃桶', value: activeBuckets, icon: 'Activity' },
    { label: '已触顶', value: saturatedBuckets, icon: 'AlertTriangle' },
  ]
})

const filteredRules = computed(() => {
  const q = searchQuery.value.trim().toLowerCase()
  return rules.value.filter((r) => {
    if (onlyActive.value && !(r.buckets && r.buckets.length)) return false
    if (!q) return true
    if (String(r.name || '').toLowerCase().includes(q)) return true
    return (r.buckets || []).some((b: any) => String(b.group_id || '').toLowerCase().includes(q))
  })
})

function pct(u: number, l: number): number {
  if (!l) return 0
  return Math.min(100, Math.round((u / l) * 100))
}

function bucketLabel(r: any, b: any): string {
  if (r.scope === 'global') return '全局桶'
  if (!b.group_id) return '私聊/无群上下文'
  return `群 ${b.group_id}`
}

function fmtTime(d: Date): string {
  const pad = (n: number) => String(n).padStart(2, '0')
  return `${pad(d.getHours())}:${pad(d.getMinutes())}:${pad(d.getSeconds())}`
}

function stopTimer() {
  if (timer) {
    clearTimeout(timer)
    timer = null
  }
}

function scheduleNext() {
  stopTimer()
  if (!autoRefresh.value || unmounted) return
  timer = setTimeout(() => {
    timer = null
    if (unmounted || !autoRefresh.value) return
    if (typeof document !== 'undefined' && document.hidden) {
      scheduleNext()
      return
    }
    load()
  }, 5000)
}

async function load() {
  stopTimer()
  loading.value = true
  loadError.value = null
  try {
    const res = await fetchRateLimit()
    if (unmounted) return
    rules.value = res.rules || []
    updatedAt.value = fmtTime(new Date())
  } catch (e: unknown) {
    if (unmounted) return
    loadError.value = (e as Error).message
    if ((e as any)?._isUnauthorized) {
      autoRefresh.value = false
    }
  } finally {
    loading.value = false
    if (autoRefresh.value && !unmounted) {
      scheduleNext()
    }
  }
}

function handleVisibilityChange() {
  if (!document.hidden && autoRefresh.value && !loading.value && !unmounted) {
    load()
  }
}

watch(autoRefresh, (on) => {
  if (on) scheduleNext()
  else stopTimer()
})

onMounted(() => {
  document.addEventListener('visibilitychange', handleVisibilityChange)
})

onBeforeUnmount(() => {
  unmounted = true
  stopTimer()
  document.removeEventListener('visibilitychange', handleVisibilityChange)
})

load()
</script>

<style scoped>
.rl-banner { margin-bottom: var(--qq-gap-md); }
.updated-at { color: var(--qq-text-muted); font-size: var(--qq-text-xs); font-variant-numeric: tabular-nums; white-space: nowrap; }
.auto { display: inline-flex; align-items: center; gap: 6px; color: var(--qq-text-muted); font-size: var(--qq-text-sm); cursor: pointer; }
.rl-toolbar { display: flex; align-items: center; gap: var(--qq-gap-md); flex-wrap: wrap; margin-bottom: var(--qq-gap-md); }
.rl-search { width: 240px; }

.rule-grid { display: grid; grid-template-columns: repeat(auto-fill, minmax(min(320px, 100%), 1fr)); gap: var(--qq-gap-md); }
.rule-card { display: flex; flex-direction: column; }
.rule-head { display: flex; align-items: flex-start; justify-content: space-between; gap: var(--qq-gap-sm); min-height: 28px; margin-bottom: var(--qq-gap-sm); flex-wrap: wrap; }
.rule-name { font-weight: 600; color: var(--qq-text); font-family: var(--qq-font-mono); overflow-wrap: anywhere; }
.rule-tags { display: flex; align-items: center; gap: var(--qq-gap-xs); flex-wrap: wrap; }
.window { font-size: var(--qq-text-xs); color: var(--qq-text-muted); white-space: nowrap; }
.empty { padding: var(--qq-gap-sm) 0; }
.muted { color: var(--qq-text-muted); font-size: var(--qq-text-xs); }
.mono { font-family: var(--qq-font-mono); }
.buckets { display: flex; flex-direction: column; gap: var(--qq-gap-sm); }
.bucket { padding: var(--qq-gap-sm); border-radius: var(--qq-radius-sm); background: var(--qq-surface-strong); }
.bucket-head { display: flex; justify-content: space-between; align-items: center; font-size: var(--qq-text-xs); margin-bottom: 4px; }
.bucket-label { color: var(--qq-text); font-weight: 500; }
.stat { color: var(--qq-text); font-size: var(--qq-text-xs); }
.stat .sat { color: var(--qq-danger); font-weight: 600; }
.bar { height: 6px; background: var(--qq-surface); border-radius: var(--qq-radius-full); overflow: hidden; }
.bar-fill { height: 100%; background: var(--qq-primary); transition: width 0.3s var(--qq-ease-out); }
.bar-fill.sat { background: var(--qq-danger); }
.top { margin-top: var(--qq-gap-xs); padding-top: var(--qq-gap-xs); border-top: 1px solid var(--qq-border); }
.top-head { font-size: var(--qq-text-xs); color: var(--qq-text-muted); margin-bottom: 3px; }
.top-row { display: grid; grid-template-columns: minmax(100px, auto) 1fr auto; align-items: center; gap: var(--qq-gap-sm); font-size: var(--qq-text-xs); color: var(--qq-text-muted); }
.mini-bar { height: 4px; background: var(--qq-surface); border-radius: var(--qq-radius-full); overflow: hidden; }
.mini-fill { height: 100%; background: var(--qq-primary); transition: width 0.3s var(--qq-ease-out); }
.mini-fill.sat { background: var(--qq-danger); }
</style>
