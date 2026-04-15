<template>
  <div>
    <div class="view-header">
      <h2>消息统计</h2>
      <div class="header-actions">
        <span v-if="updatedAt" class="muted">更新于 {{ updatedAt }}</span>
        <button @click="load" :disabled="loading">{{ loading ? '刷新中…' : '刷新' }}</button>
      </div>
    </div>
    <p v-if="error" class="error">{{ error }}</p>
    <p v-else-if="loading && !data">加载中…</p>
    <div v-else-if="data">
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
  data: () => ({ data: null, error: null, loading: false, updatedAt: null }),
  async mounted() { await this.load() },
  methods: {
    async load() {
      this.loading = true
      this.error = null
      try {
        this.data = await apiFetch('/api/stats')
        this.updatedAt = new Date().toLocaleTimeString('zh-CN')
      } catch (e) {
        this.error = e.message
      } finally {
        this.loading = false
      }
    },
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

<style scoped>
.view-header { display: flex; align-items: center; justify-content: space-between; margin-bottom: 16px; }
.view-header h2 { margin-bottom: 0; }
.header-actions { display: flex; align-items: center; gap: 12px; }
</style>
