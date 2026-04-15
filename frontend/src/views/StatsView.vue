<template>
  <div>
    <h2>消息统计</h2>
    <p v-if="error" class="error">{{ error }}</p>
    <p v-else-if="!data">加载中…</p>
    <div v-else>
      <div v-for="(gs, gid) in data" :key="gid" class="card">
        <h3>群 {{ gid }}</h3>
        <p>消息总数：{{ gs.total_messages }}</p>
        <details v-if="topUsers(gs).length">
          <summary>活跃用户 Top {{ topUsers(gs).length }}</summary>
          <ol>
            <li v-for="[uid, cnt] in topUsers(gs)" :key="uid">
              {{ gs.user_names?.[uid] || uid }} — {{ cnt }} 条
            </li>
          </ol>
        </details>
        <details v-if="topRules(gs).length">
          <summary>规则触发 Top {{ topRules(gs).length }}</summary>
          <ol>
            <li v-for="[rule, cnt] in topRules(gs)" :key="rule">
              {{ rule }} — {{ cnt }} 次
            </li>
          </ol>
        </details>
      </div>
      <p v-if="!Object.keys(data).length" class="muted">暂无数据</p>
    </div>
  </div>
</template>

<script>
import { apiFetch } from '../api.js'
export default {
  data: () => ({ data: null, error: null }),
  async mounted() {
    try {
      this.data = await apiFetch('/api/stats')
    } catch (e) {
      this.error = e.message
    }
  },
  methods: {
    topUsers(gs) {
      return Object.entries(gs.user_messages || {})
        .sort((a, b) => b[1] - a[1]).slice(0, 15)
    },
    topRules(gs) {
      return Object.entries(gs.rule_triggers || {})
        .sort((a, b) => b[1] - a[1]).slice(0, 10)
    },
  },
}
</script>
