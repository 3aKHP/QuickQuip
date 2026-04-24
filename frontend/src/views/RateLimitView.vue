<template>
  <div class="rl-view">
    <UiPageHeader title="限流实时状态" subtitle="内存状态，重启归零。scope=全局 的规则保护外部 API/共享资源；scope=按群 的规则每个群独立分桶">
      <template #actions>
        <label class="auto-toggle">
          <input type="checkbox" v-model="autoRefresh" />
          <span>5s 自动刷新</span>
        </label>
        <UiButton icon="RefreshCw" :loading="loading" @click="load">刷新</UiButton>
      </template>
    </UiPageHeader>

    <p v-if="loadError" class="error">{{ loadError }}</p>
    <UiLoading v-if="loading && !rules.length" />
    <UiEmpty v-else-if="!rules.length" icon="Zap" title="无限流规则" />

    <div v-else class="rule-grid">
      <UiCard
        v-for="r in rules"
        :key="r.name"
        padding="md"
        shadow="sm"
        class="rule-card"
      >
        <div class="rule-head">
          <span class="rule-name">{{ r.name }}</span>
          <div class="rule-tags">
            <UiTag size="sm" :variant="r.scope === 'global' ? 'warn' : 'info'">
              {{ r.scope === 'global' ? '全局' : '按群' }}
            </UiTag>
            <span class="rule-window">窗口 {{ r.window_seconds }}s · 上限 {{ r.global_limit }}/{{ r.user_limit }}</span>
          </div>
        </div>

        <div v-if="!r.buckets.length" class="empty-bucket">
          <span class="muted">当前窗口无命中</span>
        </div>

        <div v-else class="buckets">
          <div
            v-for="b in r.buckets"
            :key="b.group_id || '__global__'"
            class="bucket"
          >
            <div class="bucket-head">
              <span class="bucket-label">{{ bucketLabel(r, b) }}</span>
              <span class="stat-num">
                <span :class="{ saturated: b.global_used >= r.global_limit }">{{ b.global_used }}</span>
                / {{ r.global_limit }}
              </span>
            </div>
            <div class="bar">
              <div
                class="bar-fill"
                :class="{ saturated: b.global_used >= r.global_limit }"
                :style="{ width: progressPercent(b.global_used, r.global_limit) + '%' }"
              />
            </div>

            <div v-if="b.top_users.length" class="top-users">
              <div class="top-row-header">
                <span>活跃 {{ b.active_users }} 人</span>
              </div>
              <div v-for="u in b.top_users" :key="u.user_id" class="top-row">
                <span class="mono">uid {{ u.user_id }}</span>
                <div class="mini-bar">
                  <div
                    class="mini-fill"
                    :class="{ saturated: u.used >= r.user_limit }"
                    :style="{ width: progressPercent(u.used, r.user_limit) + '%' }"
                  />
                </div>
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
import { onBeforeUnmount, ref, watch } from 'vue'
import UiPageHeader from '../components/ui/UiPageHeader.vue'
import UiButton from '../components/ui/UiButton.vue'
import UiCard from '../components/ui/UiCard.vue'
import UiTag from '../components/ui/UiTag.vue'
import UiLoading from '../components/ui/UiLoading.vue'
import UiEmpty from '../components/ui/UiEmpty.vue'
import { fetchRateLimit } from '../api/rateLimit'

const rules = ref<any[]>([])
const loading = ref(false)
const loadError = ref<string | null>(null)
const autoRefresh = ref(false)
let timer: ReturnType<typeof setInterval> | null = null

function progressPercent(used: number, limit: number): number {
  if (!limit) return 0
  return Math.min(100, Math.round((used / limit) * 100))
}

function bucketLabel(rule: any, bucket: any): string {
  if (rule.scope === 'global') return '全局桶'
  if (!bucket.group_id) return '私聊/无群上下文'
  return `群 ${bucket.group_id}`
}

async function load() {
  loading.value = true
  loadError.value = null
  try {
    const data = await fetchRateLimit()
    rules.value = data.rules || []
  } catch (e: unknown) {
    loadError.value = (e as Error).message
    if ((e as any)._isUnauthorized) stopTimer()
  } finally {
    loading.value = false
  }
}

function startTimer() {
  stopTimer()
  timer = setInterval(load, 5000)
}

function stopTimer() {
  if (timer) {
    clearInterval(timer)
    timer = null
  }
}

watch(autoRefresh, (on) => {
  if (on) startTimer()
  else stopTimer()
})

onBeforeUnmount(stopTimer)

load()
</script>

<style scoped>
.rl-view {
  display: flex;
  flex-direction: column;
  flex: 1;
  min-height: 0;
}

.error { color: var(--qq-danger); }
.muted { color: var(--qq-text-muted); font-size: 12px; }
.mono { font-family: var(--qq-font-mono); }

.auto-toggle {
  display: inline-flex;
  align-items: center;
  gap: 6px;
  color: var(--qq-text-muted);
  font-size: 13px;
  cursor: pointer;
}

.auto-toggle input { cursor: pointer; }

.rule-grid {
  display: grid;
  grid-template-columns: repeat(auto-fill, minmax(340px, 1fr));
  gap: var(--qq-gap-md);
}

.rule-head {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: var(--qq-gap-sm);
  margin-bottom: var(--qq-gap-sm);
  flex-wrap: wrap;
}

.rule-name {
  font-weight: 500;
  color: var(--qq-text);
  font-size: 14px;
  font-family: var(--qq-font-mono);
}

.rule-tags {
  display: flex;
  align-items: center;
  gap: var(--qq-gap-xs);
}

.rule-window {
  font-size: 11px;
  color: var(--qq-text-muted);
}

.empty-bucket {
  padding: var(--qq-gap-sm) 0;
}

.buckets {
  display: flex;
  flex-direction: column;
  gap: var(--qq-gap-sm);
}

.bucket {
  padding: var(--qq-gap-sm);
  border-radius: var(--qq-radius-sm);
  background: var(--qq-surface-strong);
}

.bucket-head {
  display: flex;
  justify-content: space-between;
  align-items: center;
  font-size: 12px;
  color: var(--qq-text-muted);
  margin-bottom: 4px;
}

.bucket-label {
  color: var(--qq-text);
  font-weight: 500;
}

.stat-num {
  font-family: var(--qq-font-mono);
  color: var(--qq-text);
}

.stat-num .saturated {
  color: var(--qq-danger);
  font-weight: 600;
}

.bar {
  height: 6px;
  background: var(--qq-surface);
  border-radius: 3px;
  overflow: hidden;
}

.bar-fill {
  height: 100%;
  background: var(--qq-accent);
  transition: width 0.3s ease;
}

.bar-fill.saturated { background: var(--qq-danger); }

.top-users {
  margin-top: var(--qq-gap-xs);
  padding-top: var(--qq-gap-xs);
  border-top: 1px solid var(--qq-border);
}

.top-row-header {
  font-size: 11px;
  color: var(--qq-text-muted);
  margin-bottom: 3px;
}

.top-row {
  display: grid;
  grid-template-columns: minmax(100px, auto) 1fr auto;
  align-items: center;
  gap: var(--qq-gap-sm);
  font-size: 12px;
  color: var(--qq-text-muted);
  margin-bottom: 2px;
}

.mini-bar {
  height: 4px;
  background: var(--qq-surface);
  border-radius: 2px;
  overflow: hidden;
}

.mini-fill {
  height: 100%;
  background: var(--qq-accent);
  transition: width 0.3s ease;
}

.mini-fill.saturated { background: var(--qq-danger); }

.used { font-size: 11px; }
</style>
