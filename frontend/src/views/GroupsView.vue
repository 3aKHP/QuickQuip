<template>
  <div>
    <UiPageHeader title="功能群组管理" />
    <p v-if="error" class="error">{{ error }}</p>
    <UiLoading v-else-if="!loaded" />
    <UiCard v-else padding="md" shadow="sm" accent="primary">
      <UiTabs v-model="activeTab" :tabs="typeTabs" class="groups-tabs" />
      <Transition name="tab-pane" mode="out-in">
        <div :key="activeTab" class="tab-body">
          <ul class="glist">
            <li v-for="gid in groups[activeTab]" :key="gid">
              <span class="gid">{{ gid }}</span>
              <span class="row-actions">
                <select v-if="activeTab === 'briefing'" v-model="briefingPeriods[gid]" class="period-select">
                  <option value="">当前时段</option>
                  <option value="morning">早报</option>
                  <option value="noon">午报</option>
                  <option value="evening">晚报</option>
                </select><UiInfoTip text="不指定时段时按当前时刻自动选择：0–11 点为早报、11–18 点为午报、18–24 点为晚报（北京时间）。" />
                <UiButton size="sm" icon="Send" :loading="runningNow === `${activeTab}:${gid}`" @click="runNow(gid)">立即生成</UiButton><UiInfoTip text="点击后任务入队由机器人异步执行，生成完成直接发到群里：每日总结覆盖昨天 06:00 至当前时刻，周/月报生成上一个完整周期，简报按上方所选时段取数（早报回顾昨天全天，午/晚报回顾当天截至当前）；触发有冷却限制，消息不足时跳过。" />
                <UiButton size="sm" variant="danger" icon="X" @click="removeGroup(activeTab, gid)">移除</UiButton>
              </span>
            </li>
            <li v-if="!groups[activeTab].length" class="empty-li">
              <UiEmpty compact icon="BookOpen" :title="`暂无开启${typeLabels[activeTab]}的群组`" />
            </li>
          </ul>
          <div class="add-row">
            <select v-model="newIds[activeTab]"><option value="">— 从已知群选择 —</option><option v-for="gid in availableGroups(activeTab)" :key="gid" :value="gid">{{ gid }}</option></select><UiInfoTip text="可选项来自消息统计：机器人历史上收到过消息的群才会出现；没出现的新群可在右侧手动输入群号。" />
            <input v-model="newManuals[activeTab]" placeholder="或手动输入群号" @keyup.enter="addGroup(activeTab)" />
            <UiButton icon="Plus" @click="addGroup(activeTab)">添加</UiButton>
          </div>
        </div>
      </Transition>
    </UiCard>
  </div>
</template>

<script setup lang="ts">
import { onMounted, ref } from 'vue'
import UiPageHeader from '../components/ui/UiPageHeader.vue'
import UiCard from '../components/ui/UiCard.vue'
import UiButton from '../components/ui/UiButton.vue'
import UiLoading from '../components/ui/UiLoading.vue'
import UiEmpty from '../components/ui/UiEmpty.vue'
import UiTabs from '../components/ui/UiTabs.vue'
import UiInfoTip from '../components/ui/UiInfoTip.vue'
import { fetchGroups, fetchKnownGroups, runBriefingNow, runPeriodReportNow, runSummaryNow, updateGroup } from '../api/groups'
import { toast } from '../toast'

type GroupType = 'summary' | 'briefing' | 'weekly' | 'monthly'

const loaded = ref(false)
const error = ref<string | null>(null)
const groups = ref<Record<GroupType, string[]>>({ summary: [], briefing: [], weekly: [], monthly: [] })
const knownGroups = ref<string[]>([])
const newIds = ref<Record<GroupType, string>>({ summary: '', briefing: '', weekly: '', monthly: '' })
const newManuals = ref<Record<GroupType, string>>({ summary: '', briefing: '', weekly: '', monthly: '' })
const runningNow = ref('')
const briefingPeriods = ref<Record<string, string>>({})

const activeTab = ref<GroupType>('summary')
const typeTabs: { key: GroupType; label: string; tip: string }[] = [
  { key: 'summary', label: '每日总结', tip: '开启后每天定时把前一个 06:00–06:00 窗口的群聊消息交给 LLM 生成长文总结并发布到群；生成/发布时间、最少消息数在 llm.toml 的 [daily_summary]。' },
  { key: 'briefing', label: '每日简报', tip: '每天早/午/晚三个时段定时播报到群：早报回顾昨天，午报、晚报回顾当天截至当前，含消息数、活跃用户、热词等；时段 cron 在 llm.toml 的 [daily_briefing]。' },
  { key: 'weekly', label: '群周报', tip: '每周一生成上一个完整 ISO 周（上周）的群聊回顾，数据来自聊天归档，不足 min_messages 条则跳过；配置在 llm.toml 的 [weekly_report]。' },
  { key: 'monthly', label: '群月报', tip: '每月 1 日生成上一个自然月（上月）的群聊回顾，数据来自聊天归档，不足 min_messages 条则跳过；配置在 llm.toml 的 [monthly_report]。' },
]
const typeLabels: Record<GroupType, string> = {
  summary: '每日总结', briefing: '每日简报', weekly: '群周报', monthly: '群月报',
}

onMounted(async () => {
  try {
    const [g, k] = await Promise.all([fetchGroups(), fetchKnownGroups()])
    groups.value = { summary: [], briefing: [], weekly: [], monthly: [], ...g }
    knownGroups.value = k.groups || []
    loaded.value = true
  } catch (e: unknown) {
    error.value = (e as Error).message
  }
})

function availableGroups(type: GroupType): string[] {
  return knownGroups.value.filter(g => !groups.value[type].includes(g))
}

async function addGroup(type: GroupType) {
  const v = (newIds.value[type] || newManuals.value[type]).trim()
  if (!v || !/^\d+$/.test(v)) { toast('群号必须为纯数字', 'error'); return }
  try {
    await updateGroup(type, v, true)
    if (!groups.value[type].includes(v)) groups.value[type].push(v)
    newIds.value[type] = ''
    newManuals.value[type] = ''
    toast(`群 ${v} 已添加`)
  } catch (e: unknown) {
    toast(`操作失败：${(e as Error).message}`, 'error')
  }
}

async function removeGroup(type: GroupType, gid: string) {
  try {
    await updateGroup(type, gid, false)
    groups.value[type] = groups.value[type].filter(g => g !== gid)
    toast(`群 ${gid} 已移除`)
  } catch (e: unknown) {
    toast(`操作失败：${(e as Error).message}`, 'error')
  }
}

function runNow(gid: string) {
  const type = activeTab.value
  if (type === 'summary') return summaryNow(gid)
  if (type === 'briefing') return briefingNow(gid)
  return periodNow(type, gid)
}

async function summaryNow(gid: string) {
  runningNow.value = `summary:${gid}`
  try {
    const r = await runSummaryNow(gid)
    toast(`总结任务已入队：${r.action?.id || ''}`)
  } catch (e: unknown) {
    toast(`入队失败：${(e as Error).message}`, 'error', 4000)
  } finally {
    runningNow.value = ''
  }
}

async function briefingNow(gid: string) {
  runningNow.value = `briefing:${gid}`
  try {
    const r = await runBriefingNow(gid, briefingPeriods.value[gid] || undefined)
    toast(`播报任务已入队：${r.action?.id || ''}`)
  } catch (e: unknown) {
    toast(`入队失败：${(e as Error).message}`, 'error', 4000)
  } finally {
    runningNow.value = ''
  }
}

async function periodNow(type: 'weekly' | 'monthly', gid: string) {
  runningNow.value = `${type}:${gid}`
  try {
    const r = await runPeriodReportNow(type, gid)
    toast(`${type === 'weekly' ? '周报' : '月报'}任务已入队：${r.action?.id || ''}`)
  } catch (e: unknown) {
    toast(`入队失败：${(e as Error).message}`, 'error', 4000)
  } finally {
    runningNow.value = ''
  }
}
</script>

<style scoped>
.error { color: var(--qq-danger); }
.groups-tabs { margin-bottom: var(--qq-gap-md); }
.tab-body { min-height: 120px; }
.glist { list-style: none; margin-bottom: var(--qq-gap-sm); }
.glist li { display: flex; align-items: center; justify-content: space-between; padding: var(--qq-gap-sm) 0; border-bottom: 1px solid var(--qq-border); font-size: var(--qq-text-sm); }
.glist li:last-child { border-bottom: none; }
.glist li.empty-li { padding: 0; border: none; }
.gid { font-family: var(--qq-font-mono); color: var(--qq-text); }
.row-actions { display: inline-flex; align-items: center; justify-content: flex-end; gap: var(--qq-gap-xs); flex-wrap: wrap; }
.period-select { width: 92px; padding: 4px 6px; font-size: var(--qq-text-xs); }
.add-row { display: flex; gap: var(--qq-gap-sm); margin-top: var(--qq-gap-sm); flex-wrap: wrap; }
.add-row select, .add-row input { flex: 1; min-width: 120px; }
</style>
