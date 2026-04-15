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
          <input v-model="newSummaryId" placeholder="群号" @keyup.enter="addGroup('summary')" />
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
          <input v-model="newBriefingId" placeholder="群号" @keyup.enter="addGroup('briefing')" />
          <button @click="addGroup('briefing')">添加</button>
        </div>
      </section>
    </div>
  </div>
</template>

<script>
import { apiFetch } from '../api.js'
export default {
  data: () => ({
    loaded: false,
    error: null,
    groups: { summary: [], briefing: [] },
    newSummaryId: '',
    newBriefingId: '',
  }),
  async mounted() {
    try {
      this.groups = await apiFetch('/api/groups')
      this.loaded = true
    } catch (e) {
      this.error = e.message
    }
  },
  methods: {
    async addGroup(type) {
      const raw = type === 'summary' ? this.newSummaryId : this.newBriefingId
      const gid = raw.trim()
      if (!gid || !/^\d+$/.test(gid)) return alert('群号必须为纯数字')
      try {
        await apiFetch(`/api/groups/${type}/${gid}`, {
          method: 'POST',
          body: JSON.stringify({ enabled: true }),
        })
        if (!this.groups[type].includes(gid)) this.groups[type].push(gid)
        if (type === 'summary') this.newSummaryId = ''
        else this.newBriefingId = ''
      } catch (e) {
        alert(`操作失败：${e.message}`)
      }
    },
    async removeGroup(type, gid) {
      try {
        await apiFetch(`/api/groups/${type}/${gid}`, {
          method: 'POST',
          body: JSON.stringify({ enabled: false }),
        })
        this.groups[type] = this.groups[type].filter(g => g !== gid)
      } catch (e) {
        alert(`操作失败：${e.message}`)
      }
    },
  },
}
</script>
