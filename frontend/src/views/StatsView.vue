<template>
  <div class="stats-view">
    <UiPageHeader title="消息统计"><template #actions><span v-if="updatedAt" class="muted">更新于 {{ updatedAt }}</span><UiButton :loading="loading" icon="RefreshCw" @click="load">刷新</UiButton></template></UiPageHeader>

    <p v-if="error" class="error">{{ error }}</p>
    <UiLoading v-else-if="loading && !data" />

    <div v-else-if="data" class="stats-list">
      <div v-for="(gs, gid) in data" :key="gid" class="stats-group">
        <UiCard padding="md" shadow="sm">
          <div class="group-head">
            <h3>群 {{ gid }}</h3>
            <UiTag>总消息 {{ formatNum(gs.total_messages || 0) }}</UiTag>
          </div>
          <div v-if="computedStats[gid]?.users?.length" class="group-section">
            <h4 class="section-label"><UiIcon name="Users" :size="14" /><span>活跃用户 Top {{ computedStats[gid].users.length }}</span></h4>
            <div class="bar-list">
              <div v-for="[uid, cnt] in computedStats[gid].users" :key="uid" class="bar-row">
                <span class="bar-label">{{ gs.user_names?.[uid] || uid }}</span>
                <div class="bar-track"><div class="bar-fill" :style="{ width: pct(cnt, computedStats[gid].maxUser) + '%' }" /></div>
                <span class="bar-value">{{ cnt }}</span>
              </div>
            </div>
          </div>
          <div v-if="computedStats[gid]?.rules?.length" class="group-section">
            <h4 class="section-label"><UiIcon name="Zap" :size="14" /><span>规则触发 Top {{ computedStats[gid].rules.length }}</span></h4>
            <div class="bar-list">
              <div v-for="[rule, cnt] in computedStats[gid].rules" :key="rule" class="bar-row">
                <span class="bar-label mono">{{ rule }}</span>
                <div class="bar-track"><div class="bar-fill alt" :style="{ width: pct(cnt, computedStats[gid].maxRule) + '%' }" /></div>
                <span class="bar-value">{{ cnt }}</span>
              </div>
            </div>
          </div>
        </UiCard>
      </div>
      <UiEmpty v-if="!Object.keys(data).length" icon="BarChart3" title="暂无数据" />
    </div>
  </div>
</template>

<script setup lang="ts">
import { onMounted, ref } from 'vue'
import UiPageHeader from '../components/ui/UiPageHeader.vue'
import UiButton from '../components/ui/UiButton.vue'
import UiCard from '../components/ui/UiCard.vue'
import UiTag from '../components/ui/UiTag.vue'
import UiIcon from '../components/ui/UiIcon.vue'
import UiLoading from '../components/ui/UiLoading.vue'
import UiEmpty from '../components/ui/UiEmpty.vue'
import { fetchStats } from '../api/stats'

const data = ref<any>(null); const error = ref<string | null>(null); const loading = ref(false); const updatedAt = ref<string | null>(null); const computedStats = ref<Record<string, any>>({})

onMounted(() => load())

async function load() { loading.value = true; error.value = null; try { data.value = await fetchStats(); updatedAt.value = new Date().toLocaleTimeString('zh-CN'); precomputeStats() } catch (e: unknown) { error.value = (e as Error).message } finally { loading.value = false } }
function precomputeStats() { const out: Record<string, any> = {}; for (const [gid, gs] of Object.entries(data.value || {}) as [string, any][]) { const users = (Object.entries(gs.user_messages || {}) as [string, number][]).sort((a, b) => b[1] - a[1]).slice(0, 15); const rules = (Object.entries(gs.rule_triggers || {}) as [string, number][]).sort((a, b) => b[1] - a[1]).slice(0, 10); out[gid] = { users, rules, maxUser: Math.max(...users.map(([, v]) => v as number), 1), maxRule: Math.max(...rules.map(([, v]) => v as number), 1) } }; computedStats.value = out }
function pct(v: number, max: number): number { return max ? Math.max(4, Math.round((v / max) * 100)) : 0 }
function formatNum(n: number): string { return n >= 10000 ? (n / 10000).toFixed(1) + '万' : n.toLocaleString('zh-CN') }
</script>

<style scoped>
.stats-view { display: flex; flex-direction: column; flex: 1; min-height: 0; }
.error { color: var(--qq-danger); }
.muted { color: var(--qq-text-muted); font-size: var(--qq-text-sm); }

.stats-list { display: flex; flex-direction: column; gap: var(--qq-gap-lg); }
.group-head { display: flex; align-items: center; justify-content: space-between; gap: var(--qq-gap-sm); margin-bottom: var(--qq-gap-md); }
.group-head h3 { margin: 0; font-size: var(--qq-text-md); font-weight: 600; color: var(--qq-text); }

.group-section { margin-top: var(--qq-gap-md); padding-top: var(--qq-gap-md); border-top: 1px solid var(--qq-border); }
.section-label { display: inline-flex; align-items: center; gap: 6px; font-size: var(--qq-text-sm); font-weight: 500; color: var(--qq-text-muted); margin-bottom: var(--qq-gap-sm); }

.bar-list { display: flex; flex-direction: column; gap: var(--qq-gap-sm); }
.bar-row { display: grid; grid-template-columns: 140px 1fr 48px; align-items: center; gap: var(--qq-gap-sm); font-size: var(--qq-text-sm); }
.bar-label { overflow: hidden; text-overflow: ellipsis; white-space: nowrap; color: var(--qq-text); }
.bar-label.mono { font-family: var(--qq-font-mono); }
.bar-track { height: 6px; background: var(--qq-surface-strong); border-radius: var(--qq-radius-full); overflow: hidden; }
.bar-fill { height: 100%; background: var(--qq-primary); border-radius: var(--qq-radius-full); transition: width 0.4s var(--qq-ease-out); }
.bar-fill.alt { background: var(--qq-warn); }
.bar-value { text-align: right; color: var(--qq-text-muted); font-variant-numeric: tabular-nums; }

@media (max-width: 640px) { .bar-row { grid-template-columns: 100px 1fr 40px; } }
@media (max-width: 400px) { .bar-row { grid-template-columns: 70px 1fr 36px; } }
</style>
