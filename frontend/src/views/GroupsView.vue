<template>
  <div>
<h2>功能群组管理</h2>
    <p v-if="error" class="error">{{ error }}</p>
    <p v-else-if="!loaded">加载中…</p>
    <div v-else class="groups-layout">
      <section>
        <h3>每日总结</h3>
        <ul>
          <li v-for="gid in groups.summary" :key="gid">
            {{ gid }}
            <button class="btn-off small" @click="removeGroup('summary', gid)">移除</button>
          </li>
          <li v-if="!groups.summary.length" class="muted">无</li>
        </ul>
        <div class="add-row">
          <select v-model="newSummaryId">
            <option value="">— 从已知群选择 —</option>
            <option v-for="gid in availableGroups('summary')" :key="gid" :value="gid">{{ gid }}</option>
          </select>
          <input v-model="newSummaryIdManual" placeholder="或手动输入群号" @keyup.enter="addGroup('summary')" />
          <button @click="addGroup('summary')">添加</button>
        </div>
      </section>

      <section>
        <h3>每日简报</h3>
        <ul>
          <li v-for="gid in groups.briefing" :key="gid">
            {{ gid }}
            <button class="btn-off small" @click="removeGroup('briefing', gid)">移除</button>
          </li>
          <li v-if="!groups.briefing.length" class="muted">无</li>
        </ul>
        <div class="add-row">
          <select v-model="newBriefingId">
            <option value="">— 从已知群选择 —</option>
            <option v-for="gid in availableGroups('briefing')" :key="gid" :value="gid">{{ gid }}</option>
          </select>
          <input v-model="newBriefingIdManual" placeholder="或手动输入群号" @keyup.enter="addGroup('briefing')" />
          <button @click="addGroup('briefing')">添加</button>
        </div>
      </section>
    </div>
  </div>
</template>

<script>
import { apiFetch } from '../api.js'
import { toast } from '../toast.js'
export default {
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
        apiFetch('/api/groups'),
        apiFetch('/api/groups/known').catch(() => ({ groups: [] })),
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
        await apiFetch(`/api/groups/${type}/${gid}`, {
          method: 'POST',
          body: JSON.stringify({ enabled: true }),
        })
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
        await apiFetch(`/api/groups/${type}/${gid}`, {
          method: 'POST',
          body: JSON.stringify({ enabled: false }),
        })
        this.groups[type] = this.groups[type].filter(g => g !== gid)
        toast(`群 ${gid} 已移除`)
      } catch (e) {
        toast(`操作失败：${e.message}`, 'error')
      }
    },
  },
}
</script>

