<template>
  <div>
    <UiPageHeader title="消息统计">
      <template #actions>
        <span v-if="updatedAt" class="muted">更新于 {{ updatedAt }}</span>
        <UiButton :loading="loading" icon="RefreshCw" @click="load">
          刷新
        </UiButton>
      </template>
    </UiPageHeader>

    <p v-if="error" class="error">{{ error }}</p>
    <UiLoading v-else-if="loading && !data" />
    <div v-else-if="data">
      <div v-for="(gs, gid) in data" :key="gid" class="stat-card">
        <UiCard padding="md" shadow="sm">
          <div class="stat-header">
            <h3>群 {{ gid }}</h3>
            <UiTag>总消息 {{ gs.total_messages || 0 }}</UiTag>
          </div>

          <div v-if="computedStats[gid]?.users?.length" class="stat-section">
            <div class="section-title">
              <UiIcon name="Users" :size="14" />
              <span>活跃用户 Top {{ computedStats[gid].users.length }}</span>
            </div>
            <div class="bar-list">
              <div v-for="[uid, cnt] in computedStats[gid].users" :key="uid" class="bar-row">
                <span class="bar-label">{{ gs.user_names?.[uid] || uid }}</span>
                <div class="bar-track">
                  <div class="bar-fill" :style="{ width: pct(cnt, computedStats[gid].maxUser) + '%' }" />
                </div>
                <span class="bar-value">{{ cnt }}</span>
              </div>
            </div>
          </div>

          <div v-if="computedStats[gid]?.rules?.length" class="stat-section">
            <div class="section-title">
              <UiIcon name="Zap" :size="14" />
              <span>规则触发 Top {{ computedStats[gid].rules.length }}</span>
            </div>
            <div class="bar-list">
              <div v-for="[rule, cnt] in computedStats[gid].rules" :key="rule" class="bar-row">
                <span class="bar-label mono">{{ rule }}</span>
                <div class="bar-track">
                  <div class="bar-fill alt" :style="{ width: pct(cnt, computedStats[gid].maxRule) + '%' }" />
                </div>
                <span class="bar-value">{{ cnt }}</span>
              </div>
            </div>
          </div>
        </UiCard>
      </div>

      <UiEmpty v-if="!Object.keys(data).length" icon="BarChart2" title="暂无数据" />
    </div>
  </div>
</template>

<script setup lang="ts">
import { onMounted, ref } from 'vue'
import UiCard from '../components/ui/UiCard.vue'
import UiButton from '../components/ui/UiButton.vue'
import UiPageHeader from '../components/ui/UiPageHeader.vue'
import UiTag from '../components/ui/UiTag.vue'
import UiIcon from '../components/ui/UiIcon.vue'
import UiLoading from '../components/ui/UiLoading.vue'
import UiEmpty from '../components/ui/UiEmpty.vue'
import { fetchStats } from '../api/stats'

const data = ref<any>(null)
const error = ref<string | null>(null)
const loading = ref(false)
const updatedAt = ref<string | null>(null)
const computedStats = ref<Record<string, any>>({})

onMounted(() => load())

async function load() {
  loading.value = true
  error.value = null
  try {
    data.value = await fetchStats()
    updatedAt.value = new Date().toLocaleTimeString('zh-CN')
    precomputeStats()
  } catch (e: unknown) {
    error.value = (e as Error).message
  } finally {
    loading.value = false
  }
}

function precomputeStats() {
  const out: Record<string, any> = {}
  for (const [gid, gs] of Object.entries(data.value || {}) as [string, any][]) {
    const users = (Object.entries(gs.user_messages || {}) as [string, number][])
      .sort((a, b) => b[1] - a[1]).slice(0, 15)
    const rules = (Object.entries(gs.rule_triggers || {}) as [string, number][])
      .sort((a, b) => b[1] - a[1]).slice(0, 10)
    const userValues = users.map(([, v]) => v as number)
    const ruleValues = rules.map(([, v]) => v as number)
    out[gid] = {
      users,
      rules,
      maxUser: userValues.length ? Math.max(...userValues) : 1,
      maxRule: ruleValues.length ? Math.max(...ruleValues) : 1,
    }
  }
  computedStats.value = out
}

function pct(value: number, max: number): number {
  if (!max) return 0
  return Math.max(4, Math.round((value / max) * 100))
}
</script>

<style scoped>
.muted {
  color: var(--qq-text-muted);
  font-size: 13px;
}

.error {
  color: var(--qq-danger);
}

.stat-card {
  margin-bottom: var(--qq-gap-md);
}

.stat-header {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: var(--qq-gap-sm);
  margin-bottom: var(--qq-gap-sm);
}

.stat-header h3 {
  margin: 0;
  font-size: 16px;
  color: var(--qq-text);
}

.stat-section {
  margin-top: var(--qq-gap-md);
  padding-top: var(--qq-gap-md);
  border-top: 1px solid var(--qq-border);
}

.section-title {
  display: inline-flex;
  align-items: center;
  gap: 6px;
  font-size: 13px;
  font-weight: 500;
  color: var(--qq-text-muted);
  margin-bottom: var(--qq-gap-sm);
}

.bar-list {
  display: flex;
  flex-direction: column;
  gap: 8px;
}

.bar-row {
  display: grid;
  grid-template-columns: 140px 1fr 48px;
  align-items: center;
  gap: var(--qq-gap-sm);
  font-size: 13px;
}

.bar-label {
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
  color: var(--qq-text);
}

.bar-label.mono {
  font-family: var(--qq-font-mono);
}

.bar-track {
  height: 6px;
  background: var(--qq-surface-strong);
  border-radius: var(--qq-radius-pill);
  overflow: hidden;
}

.bar-fill {
  height: 100%;
  background: linear-gradient(90deg, var(--qq-accent), rgba(88, 166, 255, 0.6));
  border-radius: var(--qq-radius-pill);
  transition: width 0.4s ease;
}

.bar-fill.alt {
  background: linear-gradient(90deg, var(--qq-warn), rgba(210, 153, 34, 0.6));
}

.bar-value {
  text-align: right;
  color: var(--qq-text-muted);
  font-variant-numeric: tabular-nums;
}

@media (max-width: 640px) {
  .bar-row {
    grid-template-columns: 100px 1fr 40px;
  }
}
</style>
