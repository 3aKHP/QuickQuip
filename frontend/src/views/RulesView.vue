<template>
  <div>
    <h2>规则开关</h2>
    <p v-if="error" class="error">{{ error }}</p>
    <p v-else-if="!loaded">加载中…</p>
    <div v-else>
      <div class="toolbar">
        <label>群组：
          <select v-model="selectedGroup">
            <option value="">— 选择群组 —</option>
            <option v-for="gid in allGroups" :key="gid" :value="gid">{{ gid }}</option>
          </select>
        </label>
        <label>手动添加：
          <input v-model="newGroupId" placeholder="输入群号" @keyup.enter="addGroup" />
        </label>
        <button @click="addGroup">添加</button>
      </div>

      <div v-if="selectedGroup" class="rule-grid">
        <div v-for="rule in allRules" :key="rule" class="rule-row">
          <span class="rule-name">{{ rule }}</span>
          <label class="toggle">
            <input type="checkbox" :checked="isEnabled(rule)" @click.prevent="toggle(rule)" />
            <span class="toggle-slider"></span>
          </label>
        </div>
      </div>
      <p v-else class="muted">请先选择或添加一个群组</p>
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
    disabled: {},
    allRules: [],
    allGroups: [],
    selectedGroup: '',
    newGroupId: '',
  }),
  async mounted() {
    try {
      const [rulesData, knownData] = await Promise.all([
        apiFetch('/api/rules'),
        apiFetch('/api/groups/known').catch(() => ({ groups: [] })),
      ])
      this.disabled = rulesData.disabled
      this.allRules = rulesData.all_rules
      const fromRules = Object.keys(rulesData.disabled)
      const fromKnown = knownData.groups || []
      this.allGroups = [...new Set([...fromKnown, ...fromRules])].sort()
      this.loaded = true
    } catch (e) {
      this.error = e.message
    }
  },
  methods: {
    isEnabled(rule) {
      return !(this.disabled[this.selectedGroup] || []).includes(rule)
    },
    addGroup() {
      const gid = this.newGroupId.trim()
      if (!gid || !/^\d+$/.test(gid)) return
      if (!this.allGroups.includes(gid)) this.allGroups.push(gid)
      if (!this.disabled[gid]) this.disabled[gid] = []
      this.selectedGroup = gid
      this.newGroupId = ''
    },
    async toggle(rule) {
      const nowEnabled = this.isEnabled(rule)
      try {
        await apiFetch(`/api/rules/${this.selectedGroup}/${rule}`, {
          method: 'POST',
          body: JSON.stringify({ enabled: !nowEnabled }),
        })
        if (!this.disabled[this.selectedGroup]) this.disabled[this.selectedGroup] = []
        if (nowEnabled) {
          this.disabled[this.selectedGroup].push(rule)
        } else {
          this.disabled[this.selectedGroup] = this.disabled[this.selectedGroup].filter(r => r !== rule)
        }
        toast(`${rule} 已${!nowEnabled ? '启用' : '禁用'}`)
      } catch (e) {
        toast(`操作失败：${e.message}`, 'error')
      }
    },
  },
}
</script>
