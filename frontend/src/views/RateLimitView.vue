<template>
  <div class="rl-view">
    <UiPageHeader title="限流实时状态" subtitle="各规则在当前滑动窗口内的命中情况（内存状态，仅反映当前进程）">
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
          <span class="rule-window">窗口 {{ r.window_seconds }}s</span>
        </div>

        <div class="rule-stat">
          <div class="stat-label">
            <span>全局已用</span>
            <span class="stat-num">
              <span :class="{ saturated: r.global_used >= r.global_limit }">{{ r.global_used }}</span>
              / {{ r.global_limit }}
            </span>
          </div>
          <div class="bar">
            <div
              class="bar-fill"
              :class="{ saturated: r.global_used >= r.global_limit }"
              :style="{ width: progressPercent(r.global_used, r.global_limit) + '%' }"
            />
          </div>
        </div>

        <div class="rule-meta">
          <span>单用户上限 {{ r.user_limit }}</span>
          <span>·</span>
          <span>活跃用户 {{ r.active_users }}</span>
        </div>

        <div v-if="r.top_users.length" class="top-users">
          <div class="top-title">当前窗口消耗排行</div>
          <div v-for="u in r.top_users" :key="u.user_id" class="top-row">
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
      </UiCard>
    </div>
  </div>
</template>

<script setup>
import { onBeforeUnmount, ref, watch } from 'vue'
import UiPageHeader from '../components/ui/UiPageHeader.vue'
import UiButton from '../components/ui/UiButton.vue'
import UiCard from '../components/ui/UiCard.vue'
import UiLoading from '../components/ui/UiLoading.vue'
import UiEmpty from '../components/ui/UiEmpty.vue'
import { fetchRateLimit } from '../api/rateLimit.js'

const rules = ref([])
const loading = ref(false)
const loadError = ref(null)
const autoRefresh = ref(false)
let timer = null

function progressPercent(used, limit) {
  if (!limit) return 0
  return Math.min(100, Math.round((used / limit) * 100))
}

async function load() {
  loading.value = true
  loadError.value = null
  try {
    const data = await fetchRateLimit()
    rules.value = data.rules || []
  } catch (e) {
    loadError.value = e.message
    if (e._isUnauthorized) stopTimer()
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

.error {
  color: var(--qq-danger);
}

.mono {
  font-family: var(--qq-font-mono);
}

.auto-toggle {
  display: inline-flex;
  align-items: center;
  gap: 6px;
  color: var(--qq-text-muted);
  font-size: 13px;
  cursor: pointer;
}

.auto-toggle input {
  cursor: pointer;
}

.rule-grid {
  display: grid;
  grid-template-columns: repeat(auto-fill, minmax(320px, 1fr));
  gap: var(--qq-gap-md);
}

.rule-head {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: var(--qq-gap-sm);
  margin-bottom: var(--qq-gap-sm);
}

.rule-name {
  font-weight: 500;
  color: var(--qq-text);
  font-size: 14px;
  font-family: var(--qq-font-mono);
}

.rule-window {
  font-size: 12px;
  color: var(--qq-text-muted);
}

.rule-stat {
  margin-bottom: var(--qq-gap-xs);
}

.stat-label {
  display: flex;
  justify-content: space-between;
  font-size: 12px;
  color: var(--qq-text-muted);
  margin-bottom: 4px;
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
  background: var(--qq-surface-strong);
  border-radius: 3px;
  overflow: hidden;
}

.bar-fill {
  height: 100%;
  background: var(--qq-accent);
  transition: width 0.3s ease;
}

.bar-fill.saturated {
  background: var(--qq-danger);
}

.rule-meta {
  font-size: 12px;
  color: var(--qq-text-muted);
  display: flex;
  gap: 6px;
  margin: var(--qq-gap-xs) 0;
}

.top-users {
  margin-top: var(--qq-gap-sm);
  padding-top: var(--qq-gap-sm);
  border-top: 1px solid var(--qq-border);
}

.top-title {
  font-size: 11px;
  color: var(--qq-text-muted);
  margin-bottom: 4px;
}

.top-row {
  display: grid;
  grid-template-columns: minmax(100px, auto) 1fr auto;
  align-items: center;
  gap: var(--qq-gap-sm);
  font-size: 12px;
  color: var(--qq-text-muted);
  margin-bottom: 3px;
}

.mini-bar {
  height: 4px;
  background: var(--qq-surface-strong);
  border-radius: 2px;
  overflow: hidden;
}

.mini-fill {
  height: 100%;
  background: var(--qq-accent);
  transition: width 0.3s ease;
}

.mini-fill.saturated {
  background: var(--qq-danger);
}

.used {
  font-size: 11px;
}
</style>
