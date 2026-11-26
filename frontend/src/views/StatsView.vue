<template>
  <div class="stats-view">
    <UiPageHeader title="消息统计">
      <template #actions>
        <span v-if="updatedAt" class="muted">更新于 {{ updatedAt }}</span>
        <UiButton :loading="loading" icon="RefreshCw" @click="load">刷新</UiButton>
      </template>
    </UiPageHeader>

    <div v-if="error" class="soft-note soft-note--danger stats-error" role="alert">{{ error }}</div>
    <UiLoading v-if="loading && !data" />

    <template v-if="data">
      <UiStatStrip v-if="totalGroupCount > 0" :items="stripItems" />

      <div v-if="totalGroupCount > 0" class="stats-toolbar">
        <div class="stats-filter">
          <UiIcon name="Search" :size="14" class="stats-filter__icon" />
          <input v-model="groupFilter" type="search" placeholder="筛选群号..." />
        </div>
        <UiButton size="sm" icon="ArrowDown" @click="toggleSort">
          {{ sortBy === 'messages' ? '按消息量降序' : '按群号升序' }}
        </UiButton>
        <span v-if="groupFilter.trim()" class="muted">
          匹配 {{ filteredGroups.length }} / {{ totalGroupCount }} 个群
        </span>
      </div>

      <div class="stats-list">
        <div v-for="item in filteredGroups" :key="item.gid" class="stats-group">
          <UiCard padding="md" shadow="sm">
            <div class="group-head">
              <h3>群 {{ item.gid }}</h3>
              <span class="group-head__stat">
                <UiTag>总消息 {{ formatNum(item.totalMessages) }}</UiTag>
                <UiInfoTip text="该群成员发言总数，机器人自身发言不计；自统计开始累计、跨重启保留，无时间窗口。" />
              </span>
            </div>
            <div v-if="computedStats[item.gid]?.users?.length" class="group-section">
              <h4 class="section-label">
                <UiIcon name="Users" :size="14" />
                <span>活跃用户 Top {{ computedStats[item.gid].users.length }}</span>
                <UiInfoTip :text="`按发言条数排序的群成员前 ${USER_TOP_N} 名；名称取该成员最近一次的群名片。`" />
              </h4>
              <div class="bar-list">
                <div v-for="[uid, cnt] in computedStats[item.gid].users" :key="uid" class="bar-row">
                  <span class="bar-label" :title="item.gs.user_names?.[uid] || uid">{{ item.gs.user_names?.[uid] || uid }}</span>
                  <div class="bar-track"><div class="bar-fill" :style="{ width: pct(cnt, computedStats[item.gid].maxUser) + '%' }" /></div>
                  <span class="bar-value">{{ formatNum(cnt) }}</span>
                </div>
              </div>
            </div>
            <div v-if="computedStats[item.gid]?.rules?.length" class="group-section">
              <h4 class="section-label">
                <UiIcon name="Zap" :size="14" />
                <span>规则触发 Top {{ computedStats[item.gid].rules.length }}</span>
                <UiInfoTip text="该群内机器人回复规则的触发次数：chat_rules.toml 规则、LLM 对话（llm_chat）、唤醒与无聊搭话均计入。" />
              </h4>
              <div class="bar-list">
                <div v-for="[rule, cnt] in computedStats[item.gid].rules" :key="rule" class="bar-row">
                  <span class="bar-label mono" :title="rule">{{ rule }}</span>
                  <div class="bar-track"><div class="bar-fill alt" :style="{ width: pct(cnt, computedStats[item.gid].maxRule) + '%' }" /></div>
                  <span class="bar-value">{{ formatNum(cnt) }}</span>
                </div>
              </div>
            </div>
          </UiCard>
        </div>

        <UiEmpty
          v-if="!totalGroupCount"
          icon="BarChart3"
          title="暂无统计数据"
          description="统计来自 Bot 在线期间接收的群消息；让 Bot 在群内运行并积累发言后，这里会出现各群的消息总量、活跃用户榜与规则触发榜。"
        />
        <UiEmpty
          v-else-if="!filteredGroups.length"
          icon="Search"
          title="没有匹配的群组"
          description="尝试清空筛选关键字以查看全部群组统计。"
        />
      </div>
    </template>
  </div>
</template>

<script setup lang="ts">
import { computed, onMounted, ref } from 'vue'
import UiPageHeader from '../components/ui/UiPageHeader.vue'
import UiButton from '../components/ui/UiButton.vue'
import UiCard from '../components/ui/UiCard.vue'
import UiTag from '../components/ui/UiTag.vue'
import UiIcon from '../components/ui/UiIcon.vue'
import UiLoading from '../components/ui/UiLoading.vue'
import UiEmpty from '../components/ui/UiEmpty.vue'
import UiInfoTip from '../components/ui/UiInfoTip.vue'
import UiStatStrip from '../components/ui/UiStatStrip.vue'
import { fetchStats } from '../api/stats'

const data = ref<Record<string, any> | null>(null)
const error = ref<string | null>(null)
const loading = ref(false)
const updatedAt = ref<string | null>(null)
const computedStats = ref<Record<string, any>>({})
const groupFilter = ref('')
const sortBy = ref<'messages' | 'gid'>('messages')

/** 活跃用户榜上限：slice 与说明文案共用同一取值 */
const USER_TOP_N = 15

const totalGroupCount = computed(() => Object.keys(data.value || {}).length)

const stripItems = computed(() => {
  const raw = data.value || {}
  let totalMessages = 0
  let totalTriggers = 0
  const userSet = new Set<string>()
  for (const gs of Object.values(raw)) {
    totalMessages += gs.total_messages || 0
    for (const uid of Object.keys(gs.user_messages || {})) userSet.add(uid)
    for (const cnt of Object.values(gs.rule_triggers || {})) totalTriggers += Number(cnt) || 0
  }
  return [
    { label: '活跃群组', value: totalGroupCount.value, icon: 'Users', format: formatNum },
    { label: '累计消息', value: totalMessages, icon: 'MessageCircle', format: formatNum },
    { label: '活跃用户', value: userSet.size, icon: 'Radar', format: formatNum },
    { label: '规则触发', value: totalTriggers, icon: 'Zap', format: formatNum },
  ]
})

const filteredGroups = computed(() => {
  const raw = data.value || {}
  const q = groupFilter.value.trim().toLowerCase()
  const entries = Object.entries(raw)
    .filter(([gid]) => !q || gid.toLowerCase().includes(q))
    .map(([gid, gs]) => ({
      gid,
      gs,
      totalMessages: Number(gs?.total_messages) || 0,
    }))
  entries.sort((a, b) => {
    if (sortBy.value === 'messages') {
      return (b.totalMessages - a.totalMessages) || a.gid.localeCompare(b.gid)
    }
    return a.gid.localeCompare(b.gid)
  })
  return entries
})

function toggleSort() {
  sortBy.value = sortBy.value === 'messages' ? 'gid' : 'messages'
}

onMounted(() => { load() })

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
      .sort((a, b) => b[1] - a[1])
      .slice(0, USER_TOP_N)
    const rules = (Object.entries(gs.rule_triggers || {}) as [string, number][])
      .sort((a, b) => b[1] - a[1])
      .slice(0, 10)
    out[gid] = {
      users,
      rules,
      maxUser: Math.max(...users.map(([, v]) => v as number), 1),
      maxRule: Math.max(...rules.map(([, v]) => v as number), 1),
    }
  }
  computedStats.value = out
}

function pct(v: number, max: number): number {
  return max ? Math.max(4, Math.round((v / max) * 100)) : 0
}

function formatNum(n: number): string {
  return n >= 10000 ? (n / 10000).toFixed(1) + '万' : n.toLocaleString('zh-CN')
}
</script>

<style scoped>
.stats-view { display: flex; flex-direction: column; flex: 1; min-height: 0; }
.stats-error { margin-bottom: var(--qq-gap-md); }
.muted { color: var(--qq-text-muted); font-size: var(--qq-text-sm); }

.stats-toolbar {
  display: flex;
  align-items: center;
  gap: var(--qq-gap-sm);
  flex-wrap: wrap;
  margin-bottom: var(--qq-gap-md);
}

.stats-filter {
  position: relative;
  display: inline-flex;
  align-items: center;
}

.stats-filter__icon {
  position: absolute;
  left: 10px;
  color: var(--qq-text-muted);
  pointer-events: none;
}

.stats-filter input {
  width: 220px;
  padding-left: 30px;
}

.stats-list { display: flex; flex-direction: column; gap: var(--qq-gap-lg); }
.group-head { display: flex; align-items: center; justify-content: space-between; gap: var(--qq-gap-sm); margin-bottom: var(--qq-gap-md); }
.group-head h3 { margin: 0; font-size: var(--qq-text-md); font-weight: 600; color: var(--qq-text); }
.group-head__stat { display: inline-flex; align-items: center; }

.group-section { margin-top: var(--qq-gap-md); padding-top: var(--qq-gap-md); border-top: 1px solid var(--qq-border); }
.section-label { display: inline-flex; align-items: center; gap: 6px; font-size: var(--qq-text-sm); font-weight: 500; color: var(--qq-text-muted); margin-bottom: var(--qq-gap-sm); }

.bar-list { display: flex; flex-direction: column; gap: var(--qq-gap-sm); }
.bar-row { display: grid; grid-template-columns: 140px 1fr minmax(48px, auto); align-items: center; gap: var(--qq-gap-sm); font-size: var(--qq-text-sm); }
.bar-label { overflow: hidden; text-overflow: ellipsis; white-space: nowrap; color: var(--qq-text); }
.bar-label.mono { font-family: var(--qq-font-mono); }
.bar-track { height: 6px; background: var(--qq-surface-strong); border-radius: var(--qq-radius-full); overflow: hidden; }
.bar-fill { height: 100%; background: var(--qq-primary); border-radius: var(--qq-radius-full); transition: width 0.4s var(--qq-ease-out); }
.bar-fill.alt { background: var(--qq-warn); }
.bar-value { text-align: right; color: var(--qq-text-muted); font-variant-numeric: tabular-nums; white-space: nowrap; }

@media (max-width: 640px) { .bar-row { grid-template-columns: 100px 1fr minmax(44px, auto); } }
@media (max-width: 400px) { .bar-row { grid-template-columns: 70px 1fr minmax(40px, auto); } }
</style>
