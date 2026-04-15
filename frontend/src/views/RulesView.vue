<template>
  <div>
    <h2>规则开关</h2>
    <p v-if="error" class="error">{{ error }}</p>
    <p v-else-if="!loaded">加载中…</p>
    <div v-else>
      <!-- Group selector -->
      <div class="toolbar">
        <label>群组：
          <select v-model="selectedGroup">
            <option value="">— 选择群组 —</option>
            <option v-for="gid in allGroups" :key="gid" :value="gid">{{ gid }}</option>
          </select>
        </label>
        <label>新群组 ID：
          <input v-model="newGroupId" placeholder="输入群号" @keyup.enter="addGroup" />
        </label>
        <button @click="addGroup">添加</button>
      </div>

      <div v-if="selectedGroup" class="rule-grid">
        <div v-for="rule in allRules" :key="rule" class="rule-row">
          <span class="rule-name">{{ rule }}</span>
          <button
            :class="isEnabled(rule) ? 'btn-on' : 'btn-off'"
            @click="toggle(rule)"
          >{{ isEnabled(rule) ? 'ON' : 'OFF' }}</button>
        </div>
      </div>
      <p v-else class="muted">请先选择或添加一个群组</p>
    </div>
  </div>
</template>

<script>
import { apiFetch } from '../api.js'
export default {
  data: () => ({
    loaded: false,
    error: null,
    disabled: {},   // { group_id: [rule, ...] }
    allRules: [],
    selectedGroup: '',
    newGroupId: '',
  }),
  computed: {
    allGroups() {
      return Object.keys(this.disabled)
    },
  },
  async mounted() {
    try {
      const d = await apiFetch('/api/rules')
      this.disabled = d.disabled
      this.allRules = d.all_rules
      this.loaded = true
    } catch (e) {
      this.error = e.message
    }
  },
  methods: {
    isEnabled(rule) {
      return !(this.disabled[this.selectedGroup] || []).includes(rule)
    },
    async toggle(rule) {
      const nowEnabled = this.isEnabled(rule)
      try {
        await apiFetch(`/api/rules/${this.selectedGroup}/${rule}`, {
          method: 'POST',
          body: JSON.stringify({ enabled: !nowEnabled }),
        })
        // update local state
        if (!this.disabled[this.selectedGroup]) {
          this.disabled[this.selectedGroup] = []
        }
        if (nowEnabled) {
          this.disabled[this.selectedGroup].push(rule)
        } else {
          this.disabled[this.selectedGroup] = this.disabled[this.selectedGroup].filter(r => r !== rule)
        }
      } catch (e) {
        alert(`操作失败：${e.message}`)
      }
    },
    addGroup() {
      const gid = this.newGroupId.trim()
      if (!gid || !/^\d+$/.test(gid)) return alert('群号必须为纯数字')
      if (!this.disabled[gid]) this.disabled[gid] = []
      this.selectedGroup = gid
      this.newGroupId = ''
    },
  },
}
</script>
