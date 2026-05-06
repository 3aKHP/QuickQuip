<template>
  <div>
    <UiPageHeader title="功能群组管理" />
    <p v-if="error" class="error">{{ error }}</p>
    <UiLoading v-else-if="!loaded" />
    <div v-else class="groups-layout">
      <UiCard padding="md" shadow="sm">
        <h3 class="card-title"><UiIcon name="FileText" :size="18" /> 每日总结</h3>
        <ul class="glist">
          <li v-for="gid in groups.summary" :key="gid"><span class="gid">{{ gid }}</span><UiButton size="sm" variant="danger" icon="X" @click="removeGroup('summary', gid)">移除</UiButton></li>
          <li v-if="!groups.summary.length" class="empty-li"><UiEmpty icon="BookOpen" title="无" description="暂无开启每日总结的群组" /></li>
        </ul>
        <div class="add-row"><select v-model="newSummaryId"><option value="">— 从已知群选择 —</option><option v-for="gid in availableGroups('summary')" :key="gid" :value="gid">{{ gid }}</option></select><input v-model="newSummaryIdManual" placeholder="或手动输入群号" @keyup.enter="addGroup('summary')" /><UiButton icon="Plus" @click="addGroup('summary')">添加</UiButton></div>
      </UiCard>
      <UiCard padding="md" shadow="sm">
        <h3 class="card-title"><UiIcon name="Newspaper" :size="18" /> 每日简报</h3>
        <ul class="glist">
          <li v-for="gid in groups.briefing" :key="gid"><span class="gid">{{ gid }}</span><UiButton size="sm" variant="danger" icon="X" @click="removeGroup('briefing', gid)">移除</UiButton></li>
          <li v-if="!groups.briefing.length" class="empty-li"><UiEmpty icon="BookOpen" title="无" description="暂无开启每日简报的群组" /></li>
        </ul>
        <div class="add-row"><select v-model="newBriefingId"><option value="">— 从已知群选择 —</option><option v-for="gid in availableGroups('briefing')" :key="gid" :value="gid">{{ gid }}</option></select><input v-model="newBriefingIdManual" placeholder="或手动输入群号" @keyup.enter="addGroup('briefing')" /><UiButton icon="Plus" @click="addGroup('briefing')">添加</UiButton></div>
      </UiCard>
    </div>
  </div>
</template>

<script setup lang="ts">
import { onMounted, ref } from 'vue'
import UiPageHeader from '../components/ui/UiPageHeader.vue'; import UiCard from '../components/ui/UiCard.vue'
import UiButton from '../components/ui/UiButton.vue'; import UiIcon from '../components/ui/UiIcon.vue'
import UiLoading from '../components/ui/UiLoading.vue'; import UiEmpty from '../components/ui/UiEmpty.vue'
import { fetchGroups, fetchKnownGroups, updateGroup } from '../api/groups'; import { toast } from '../toast'

const loaded = ref(false); const error = ref<string | null>(null); const groups = ref<{ summary: string[]; briefing: string[] }>({ summary: [], briefing: [] }); const knownGroups = ref<string[]>([])
const newSummaryId = ref(''); const newSummaryIdManual = ref(''); const newBriefingId = ref(''); const newBriefingIdManual = ref('')

onMounted(async () => { try { const [g, k] = await Promise.all([fetchGroups(), fetchKnownGroups()]); groups.value = g; knownGroups.value = k.groups || []; loaded.value = true } catch (e: unknown) { error.value = (e as Error).message } })
function availableGroups(type: 'summary' | 'briefing'): string[] { return knownGroups.value.filter(g => !groups.value[type].includes(g)) }
async function addGroup(type: 'summary' | 'briefing') { const v = (type === 'summary' ? (newSummaryId.value || newSummaryIdManual.value) : (newBriefingId.value || newBriefingIdManual.value)).trim(); if (!v || !/^\d+$/.test(v)) { toast('群号必须为纯数字', 'error'); return }; try { await updateGroup(type, v, true); if (!groups.value[type].includes(v)) groups.value[type].push(v); if (type === 'summary') { newSummaryId.value = ''; newSummaryIdManual.value = '' } else { newBriefingId.value = ''; newBriefingIdManual.value = '' }; toast(`群 ${v} 已添加`) } catch (e: unknown) { toast(`操作失败：${(e as Error).message}`, 'error') } }
async function removeGroup(type: 'summary' | 'briefing', gid: string) { try { await updateGroup(type, gid, false); groups.value[type] = groups.value[type].filter(g => g !== gid); toast(`群 ${gid} 已移除`) } catch (e: unknown) { toast(`操作失败：${(e as Error).message}`, 'error') } }
</script>

<style scoped>
.error { color: var(--qq-danger); }
.groups-layout { display: grid; grid-template-columns: 1fr 1fr; gap: var(--qq-gap-lg); }
@media (max-width: 767px) { .groups-layout { grid-template-columns: 1fr; } }
.card-title { display: flex; align-items: center; gap: var(--qq-gap-xs); margin-bottom: var(--qq-gap-md); font-size: var(--qq-text-base); color: var(--qq-text); }
.glist { list-style: none; margin-bottom: var(--qq-gap-sm); }
.glist li { display: flex; align-items: center; justify-content: space-between; padding: var(--qq-gap-sm) 0; border-bottom: 1px solid var(--qq-border); font-size: var(--qq-text-sm); }
.glist li:last-child { border-bottom: none; }
.glist li.empty-li { padding: 0; border: none; }
.gid { font-family: var(--qq-font-mono); color: var(--qq-text); }
.add-row { display: flex; gap: var(--qq-gap-sm); margin-top: var(--qq-gap-sm); flex-wrap: wrap; }
.add-row select, .add-row input { flex: 1; min-width: 120px; }
</style>
