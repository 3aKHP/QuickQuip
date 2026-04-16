<template>
  <div>
    <UiPageHeader title="功能群组管理" />
    <p v-if="error" class="error">{{ error }}</p>
    <UiLoading v-else-if="!loaded" />
    <div v-else class="groups-layout">
      <UiCard padding="md" shadow="sm">
        <div class="section-header">
          <UiIcon name="CalendarCheck" :size="18" />
          <h3>每日总结</h3>
        </div>
        <ul class="group-list">
          <li v-for="gid in groups.summary" :key="gid">
            <span class="gid">{{ gid }}</span>
            <UiButton size="sm" variant="danger" icon="X" @click="removeGroup('summary', gid)">移除</UiButton>
          </li>
          <li v-if="!groups.summary.length" class="empty-item">
            <UiEmpty icon="Inbox" title="无" description="暂无开启每日总结的群组" />
          </li>
        </ul>
        <div class="add-row">
          <select v-model="newSummaryId">
            <option value="">— 从已知群选择 —</option>
            <option v-for="gid in availableGroups('summary')" :key="gid" :value="gid">{{ gid }}</option>
          </select>
          <input v-model="newSummaryIdManual" placeholder="或手动输入群号" @keyup.enter="addGroup('summary')" />
          <UiButton icon="Plus" @click="addGroup('summary')">添加</UiButton>
        </div>
      </UiCard>

      <UiCard padding="md" shadow="sm">
        <div class="section-header">
          <UiIcon name="Newspaper" :size="18" />
          <h3>每日简报</h3>
        </div>
        <ul class="group-list">
          <li v-for="gid in groups.briefing" :key="gid">
            <span class="gid">{{ gid }}</span>
            <UiButton size="sm" variant="danger" icon="X" @click="removeGroup('briefing', gid)">移除</UiButton>
          </li>
          <li v-if="!groups.briefing.length" class="empty-item">
            <UiEmpty icon="Inbox" title="无" description="暂无开启每日简报的群组" />
          </li>
        </ul>
        <div class="add-row">
          <select v-model="newBriefingId">
            <option value="">— 从已知群选择 —</option>
            <option v-for="gid in availableGroups('briefing')" :key="gid" :value="gid">{{ gid }}</option>
          </select>
          <input v-model="newBriefingIdManual" placeholder="或手动输入群号" @keyup.enter="addGroup('briefing')" />
          <UiButton icon="Plus" @click="addGroup('briefing')">添加</UiButton>
        </div>
      </UiCard>
    </div>
  </div>
</template>

<script>
import UiPageHeader from '../components/ui/UiPageHeader.vue'
import UiCard from '../components/ui/UiCard.vue'
import UiButton from '../components/ui/UiButton.vue'
import UiIcon from '../components/ui/UiIcon.vue'
import UiLoading from '../components/ui/UiLoading.vue'
import UiEmpty from '../components/ui/UiEmpty.vue'
import { fetchGroups, fetchKnownGroups, updateGroup } from '../api/groups.js'
import { toast } from '../toast.js'

export default {
  components: { UiPageHeader, UiCard, UiButton, UiIcon, UiLoading, UiEmpty },
  data: () => ({
    loaded: false,
    error: null,
    groups: { summary: [], briefing: [] },
    knownGroups: [],
    newSummaryId: '',
    newSummaryIdManual: '',
    newBriefingId: '',
    newBriefingIdManual: '',
  }),
  async mounted() {
    try {
      const [groupsData, knownData] = await Promise.all([
        fetchGroups(),
        fetchKnownGroups(),
      ])
      this.groups = groupsData
      this.knownGroups = knownData.groups || []
      this.loaded = true
    } catch (e) {
      this.error = e.message
    }
  },
  methods: {
    availableGroups(type) {
      return this.knownGroups.filter(g => !this.groups[type].includes(g))
    },
    async addGroup(type) {
      const fromSelect = type === 'summary' ? this.newSummaryId : this.newBriefingId
      const fromManual = type === 'summary' ? this.newSummaryIdManual : this.newBriefingIdManual
      const gid = (fromSelect || fromManual).trim()
      if (!gid || !/^\d+$/.test(gid)) { toast('群号必须为纯数字', 'error'); return }
      try {
        await updateGroup(type, gid, true)
        if (!this.groups[type].includes(gid)) this.groups[type].push(gid)
        if (type === 'summary') { this.newSummaryId = ''; this.newSummaryIdManual = '' }
        else { this.newBriefingId = ''; this.newBriefingIdManual = '' }
        toast(`群 ${gid} 已添加`)
      } catch (e) {
        toast(`操作失败：${e.message}`, 'error')
      }
    },
    async removeGroup(type, gid) {
      try {
        await updateGroup(type, gid, false)
        this.groups[type] = this.groups[type].filter(g => g !== gid)
        toast(`群 ${gid} 已移除`)
      } catch (e) {
        toast(`操作失败：${e.message}`, 'error')
      }
    },
  },
}
</script>

<style scoped>
.error {
  color: var(--qq-danger);
}

.groups-layout {
  display: grid;
  grid-template-columns: 1fr 1fr;
  gap: var(--qq-gap-md);
}

@media (max-width: 720px) {
  .groups-layout {
    grid-template-columns: 1fr;
  }
}

.section-header {
  display: flex;
  align-items: center;
  gap: var(--qq-gap-xs);
  margin-bottom: var(--qq-gap-sm);
}

.section-header h3 {
  margin: 0;
  font-size: 15px;
  color: var(--qq-text);
}

.group-list {
  list-style: none;
  margin-bottom: var(--qq-gap-sm);
}

.group-list li {
  display: flex;
  align-items: center;
  justify-content: space-between;
  padding: 8px 0;
  border-bottom: 1px solid var(--qq-border);
  font-size: 13px;
}

.group-list li:last-child {
  border-bottom: none;
}

.group-list li.empty-item {
  padding: 0;
}

.gid {
  font-family: var(--qq-font-mono);
  color: var(--qq-text);
}

.add-row {
  display: flex;
  gap: var(--qq-gap-sm);
  margin-top: var(--qq-gap-sm);
  flex-wrap: wrap;
}

.add-row select,
.add-row input {
  flex: 1;
  min-width: 120px;
  background: var(--qq-surface-strong);
  border: 1px solid var(--qq-border);
  border-radius: var(--qq-radius-sm);
  color: var(--qq-text);
  padding: 5px 10px;
  font-size: 13px;
  outline: none;
}

.add-row select:focus,
.add-row input:focus {
  border-color: var(--qq-accent);
  box-shadow: 0 0 0 3px var(--qq-accent-soft);
}
</style>
