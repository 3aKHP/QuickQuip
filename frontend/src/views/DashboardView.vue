<template>
  <div class="dash-view">
    <header class="dash-hero">
      <img class="dash-hero__logo" src="/brand.svg" alt="" width="48" height="48" aria-hidden="true">
      <div class="dash-hero__info">
        <h1 class="dash-hero__title">QuickQuip 管理台</h1>
        <p class="dash-hero__subtitle">当前运行状态一览</p>
      </div>
      <UiTag variant="info">v{{ quickQuipVersion }}</UiTag>
    </header>

    <p v-if="error" class="error">{{ error }}</p>
    <div v-if="loading" class="dash-cards">
      <UiCard v-for="i in 4" :key="i" padding="md" shadow="sm"><UiSkeleton :rows="2" /></UiCard>
    </div>

    <template v-else-if="data">
      <div class="domain-grid">
        <router-link
          v-for="section in NAV_SECTIONS.filter(s => s.key !== 'overview')"
          :key="section.key"
          class="domain-card"
          :to="firstPath(section.key)"
        >
          <span class="domain-card__icon">
            <UiIcon :name="section.icon" :size="22" />
          </span>
          <span class="domain-card__body">
            <span class="domain-card__title">{{ section.label }}</span>
            <span class="domain-card__desc">{{ section.description }}</span>
          </span>
          <UiIcon name="ArrowRight" :size="16" />
        </router-link>
      </div>

      <!-- Top stat cards -->
      <div class="dash-cards">
        <UiStatCard label="活跃群组" variant="primary" icon="Users" :count-to="data.totalGroups" :count-format="fmt" />
        <UiStatCard label="累计消息" icon="MessageCircle" :count-to="data.totalMessages" :count-format="fmt" />
        <UiStatCard label="活跃用户" icon="Radar" :count-to="data.totalUsers" :count-format="fmt" />
        <UiStatCard label="金币用户" icon="Coins" :count-to="data.goldUserCount" :count-format="fmt" :sub="`总金币 ${fmt(data.totalGold)}`" />
      </div>

      <!-- Row 2: rankings -->
      <div class="dash-row">
        <UiCard padding="md" shadow="sm" class="dash-half">
          <h3 class="dash-card-title section-title">群消息排行 Top 5</h3>
          <div v-if="data.groupMessages.length" class="mini-bar-list">
            <div v-for="(g, i) in data.groupMessages" :key="g.gid" class="mini-bar-row">
              <span class="mini-bar-rank">{{ i + 1 }}</span>
              <span class="mono mini-bar-key">{{ g.gid }}</span>
              <div class="mini-bar-track">
                <div class="mini-bar-fill" :style="{ width: pct(g.count, data.groupMessages[0].count) + '%' }" />
              </div>
              <span class="mini-bar-val">{{ fmt(g.count) }}</span>
            </div>
          </div>
          <UiEmpty v-else compact icon="BarChart3" title="暂无群消息数据" />
        </UiCard>

        <UiCard padding="md" shadow="sm" class="dash-half">
          <h3 class="dash-card-title section-title">规则触发 Top 5</h3>
          <div v-if="data.ruleTriggers.length" class="mini-bar-list">
            <div v-for="(r, i) in data.ruleTriggers" :key="r.rule" class="mini-bar-row">
              <span class="mini-bar-rank">{{ i + 1 }}</span>
              <span class="mono mini-bar-key">{{ r.rule }}</span>
              <span class="mini-bar-val">{{ r.count }}</span>
            </div>
          </div>
          <UiEmpty v-else compact icon="Zap" title="暂无规则触发数据" />
        </UiCard>
      </div>

      <!-- Row 3: cron + LLM -->
      <div class="dash-row">
        <UiCard padding="md" shadow="sm" class="dash-half">
          <h3 class="dash-card-title section-title">定时任务</h3>
          <div class="cron-summary">
            <div class="cron-item">
              <UiTag :variant="data.cronJobs.total > 0 ? 'success' : 'info'" size="sm">{{ data.cronJobs.total }} 个任务</UiTag>
            </div>
            <div class="cron-item">
              <span class="cron-dot cron-dot--ok" />
              <span>{{ data.cronJobs.ok }} 正常</span>
            </div>
            <div v-if="data.cronJobs.error" class="cron-item">
              <span class="cron-dot cron-dot--err" />
              <span>{{ data.cronJobs.error }} 异常</span>
            </div>
          </div>
        </UiCard>

        <UiCard padding="md" shadow="sm" class="dash-half">
          <h3 class="dash-card-title section-title">LLM 对话</h3>
          <div class="cron-summary">
            <span class="llm-count">{{ fmt(data.llmConversations.count) }}</span>
            <span class="muted">条消息</span>
            <span v-if="data.llmConversations.latest" class="muted" style="margin-left:auto">最近 {{ fmtTime(data.llmConversations.latest) }}</span>
          </div>
        </UiCard>
      </div>
    </template>
  </div>
</template>

<script setup lang="ts">
import { onMounted, ref } from 'vue'
import UiCard from '../components/ui/UiCard.vue'
import UiTag from '../components/ui/UiTag.vue'
import UiIcon from '../components/ui/UiIcon.vue'
import UiLoading from '../components/ui/UiLoading.vue'
import UiEmpty from '../components/ui/UiEmpty.vue'
import UiStatCard from '../components/ui/UiStatCard.vue'
import UiSkeleton from '../components/ui/UiSkeleton.vue'
import { fetchDashboardData, type DashboardData } from '../api/dashboard'
import { NAV_ITEMS, NAV_SECTIONS } from '../config/nav'

const data = ref<DashboardData | null>(null)
const loading = ref(true)
const error = ref<string | null>(null)
const quickQuipVersion = __QUICKQUIP_VERSION__

function fmt(n: number): string {
  if (n >= 10000) return (n / 10000).toFixed(1) + '万'
  return n.toLocaleString('zh-CN')
}

function fmtTime(iso: string): string {
  if (!iso) return ''
  const d = new Date(iso)
  if (Number.isNaN(d.getTime())) return ''
  const pad = (n: number) => String(n).padStart(2, '0')
  return `${d.getFullYear()}-${pad(d.getMonth() + 1)}-${pad(d.getDate())} ${pad(d.getHours())}:${pad(d.getMinutes())}`
}

function pct(value: number, max: number): number {
  if (!max) return 0
  return Math.max(4, Math.round((value / max) * 100))
}

function firstPath(sectionKey: string): string {
  return NAV_ITEMS.find(item => item.section === sectionKey)?.path || '/'
}

onMounted(async () => {
  try {
    data.value = await fetchDashboardData()
  } catch (e: unknown) {
    error.value = (e as Error).message
  } finally {
    loading.value = false
  }
})
</script>

<style scoped>
.dash-view {
  display: flex;
  flex-direction: column;
  flex: 1;
  min-height: 0;
}

.error { color: var(--qq-danger); }

/* Hero 位：总览域唯一使用品牌渐变晕染的大面积区块 */
.dash-hero {
  position: relative;
  display: flex;
  align-items: center;
  gap: var(--qq-gap-md);
  padding: var(--qq-gap-lg);
  margin-bottom: var(--qq-gap-lg);
  border: 1px solid var(--qq-border);
  border-radius: var(--qq-radius-card);
  background:
    radial-gradient(ellipse at 88% -30%, var(--qq-cyan-soft), transparent 55%),
    linear-gradient(120deg, var(--qq-primary-soft), transparent 62%),
    var(--qq-surface);
  box-shadow: var(--qq-shadow-card);
  overflow: hidden;
}

.dash-hero__logo {
  width: 48px;
  height: 48px;
  display: block;
  border-radius: var(--qq-radius-xl);
  box-shadow: 0 4px 14px var(--qq-primary-shadow);
  flex-shrink: 0;
}

.dash-hero__info {
  flex: 1;
  min-width: 0;
}

.dash-hero__title {
  font-family: var(--qq-font-display);
  font-size: var(--qq-text-xl);
  font-weight: 600;
  color: var(--qq-text);
  line-height: 1.3;
}

.dash-hero__subtitle {
  font-size: var(--qq-text-sm);
  color: var(--qq-text-muted);
  margin-top: var(--qq-gap-xs);
}

.domain-grid {
  display: grid;
  grid-template-columns: repeat(auto-fit, minmax(210px, 1fr));
  gap: var(--qq-gap-sm);
  margin-bottom: var(--qq-gap-lg);
}

.domain-card {
  min-height: 76px;
  display: grid;
  grid-template-columns: 42px minmax(0, 1fr) 18px;
  align-items: center;
  gap: var(--qq-gap-sm);
  padding: var(--qq-gap-md);
  background: var(--qq-surface);
  border: 1px solid var(--qq-border);
  border-radius: var(--qq-radius-card);
  color: var(--qq-text);
  text-decoration: none;
  box-shadow: var(--qq-shadow-card);
  transition: border-color var(--qq-transition-fast), transform var(--qq-transition-fast);
}

.domain-card:hover {
  border-color: var(--qq-primary);
  transform: translateY(-1px);
}

.domain-card__icon {
  width: 42px;
  height: 42px;
  display: grid;
  place-items: center;
  border-radius: var(--qq-radius-sm);
  background: var(--qq-primary-soft);
  color: var(--qq-primary);
}

.domain-card__body {
  display: flex;
  min-width: 0;
  flex-direction: column;
  gap: 2px;
}

.domain-card__title {
  font-size: var(--qq-text-base);
  font-weight: 700;
}

.domain-card__desc {
  color: var(--qq-text-muted);
  font-size: var(--qq-text-xs);
  line-height: 1.5;
}

/* Stat cards row */
.dash-cards {
  display: grid;
  grid-template-columns: repeat(auto-fit, minmax(180px, 1fr));
  gap: var(--qq-gap-md);
  margin-bottom: var(--qq-gap-lg);
}

.llm-count {
  font-size: var(--qq-text-2xl);
  font-weight: 700;
  color: var(--qq-text);
  line-height: 1;
  font-variant-numeric: tabular-nums;
}

/* Card rows */
.dash-row {
  display: grid;
  grid-template-columns: 1fr 1fr;
  gap: var(--qq-gap-md);
  margin-bottom: var(--qq-gap-md);
}

@media (max-width: 767px) {
  .dash-row { grid-template-columns: 1fr; }
}

@media (max-width: 640px) {
  .dash-cards {
    grid-template-columns: repeat(2, 1fr);
  }

  .mini-bar-row {
    grid-template-columns: 18px 1fr auto;
  }

  .mini-bar-track {
    display: none;
  }

  .mini-bar-val {
    text-align: right;
  }
}

.dash-card-title {
  margin-bottom: var(--qq-gap-md);
}

/* Mini bar chart */
.mini-bar-list {
  display: flex;
  flex-direction: column;
  gap: var(--qq-gap-sm);
}

.mini-bar-row {
  display: grid;
  grid-template-columns: 18px 1fr 120px 56px;
  align-items: center;
  gap: var(--qq-gap-sm);
  font-size: var(--qq-text-sm);
}

.mini-bar-rank {
  color: var(--qq-text-muted);
  font-weight: 600;
  font-size: var(--qq-text-xs);
  text-align: right;
}

.mini-bar-key {
  font-size: var(--qq-text-xs);
  color: var(--qq-text);
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.mini-bar-track {
  height: 4px;
  background: var(--qq-surface-strong);
  border-radius: var(--qq-radius-full);
  overflow: hidden;
}

.mini-bar-fill {
  height: 100%;
  border-radius: var(--qq-radius-full);
  background: var(--qq-primary);
  transition: width 0.5s var(--qq-ease-out);
}

.mini-bar-val {
  text-align: right;
  color: var(--qq-text-muted);
  font-variant-numeric: tabular-nums;
}

/* Cron summary */
.cron-summary {
  display: flex;
  align-items: center;
  gap: var(--qq-gap-md);
  flex-wrap: wrap;
}

.cron-item {
  display: flex;
  align-items: center;
  gap: var(--qq-gap-xs);
  font-size: var(--qq-text-sm);
  color: var(--qq-text);
}

.cron-dot {
  width: 8px;
  height: 8px;
  border-radius: 50%;
}

.cron-dot--ok { background: var(--qq-success); }
.cron-dot--err { background: var(--qq-danger); }

.muted { color: var(--qq-text-muted); font-size: var(--qq-text-sm); }
.mono { font-family: var(--qq-font-mono); }
</style>
