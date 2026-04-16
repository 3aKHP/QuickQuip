<template>
  <LoginView
    v-if="authReady && !authenticated"
    :submitting="authBusy"
    :error="authError"
    @submit="handleLogin"
  />
  <div v-else-if="authReady" class="layout">
    <nav>
      <span class="brand">QuickQuip</span>
      <button :class="{ active: view === 'stats' }" @click="view = 'stats'">统计</button>
      <button :class="{ active: view === 'rules' }" @click="view = 'rules'">规则</button>
      <button :class="{ active: view === 'groups' }" @click="view = 'groups'">群组</button>
      <button :class="{ active: view === 'memory' }" @click="view = 'memory'">记忆</button>
      <button :class="{ active: view === 'summary' }" @click="view = 'summary'">总结</button>
      <button :class="{ active: view === 'config' }" @click="view = 'config'">配置</button>
      <span class="nav-spacer"></span>
      <button class="small" :disabled="authBusy" @click="handleLogout">退出</button>
    </nav>
    <main>
      <StatsView v-if="view === 'stats'" />
      <RulesView v-else-if="view === 'rules'" />
      <GroupsView v-else-if="view === 'groups'" />
      <MemoryView v-else-if="view === 'memory'" />
      <SummaryView v-else-if="view === 'summary'" />
      <ConfigView v-else-if="view === 'config'" />
    </main>
    <transition name="toast">
      <div v-if="toastMsg" class="toast" :class="toastType">{{ toastMsg }}</div>
    </transition>
  </div>
  <div v-else class="auth-shell">
    <section class="card login-card">
      <h2>正在检查登录状态</h2>
      <p class="muted login-copy">稍等，正在确认当前浏览器会话是否仍然有效。</p>
    </section>
  </div>
</template>

<script>
import StatsView from './views/StatsView.vue'
import RulesView from './views/RulesView.vue'
import GroupsView from './views/GroupsView.vue'
import MemoryView from './views/MemoryView.vue'
import SummaryView from './views/SummaryView.vue'
import ConfigView from './views/ConfigView.vue'
import LoginView from './views/LoginView.vue'
import { toastMsg, toastType } from './toast.js'
import { getAuthState, login, logout, setUnauthorizedHandler } from './api.js'

export default {
  components: { StatsView, RulesView, GroupsView, MemoryView, SummaryView, ConfigView, LoginView },
  data: () => ({
    view: 'stats',
    authReady: false,
    authenticated: false,
    authBusy: false,
    authError: '',
    toastMsg,
    toastType,
  }),
  created() {
    setUnauthorizedHandler(() => {
      this.authenticated = false
      this.authReady = true
      this.authBusy = false
      this.authError = '登录状态已失效，请重新登录。'
    })
    this.initializeAuth()
  },
  beforeUnmount() {
    // L9: 清理全局 handler，避免 HMR 场景下旧组件的闭包继续触发
    setUnauthorizedHandler(null)
  },
  methods: {
    async initializeAuth() {
      this.authReady = false
      this.authError = ''
      try {
        await getAuthState()
        this.authenticated = true
      } catch (error) {
        if (error.status !== 401) {
          this.authError = error.data?.detail || error.message || '鉴权检查失败'
        }
        this.authenticated = false
      } finally {
        this.authReady = true
      }
    },
    async handleLogin(password) {
      this.authBusy = true
      this.authError = ''
      try {
        await login(password)
        this.authenticated = true
        toastMsg.value = null
      } catch (error) {
        this.authenticated = false
        this.authError = error.status === 401
          ? '口令错误，请重试。'
          : (error.data?.detail || error.message || '登录失败')
      } finally {
        this.authBusy = false
      }
    },
    async handleLogout() {
      this.authBusy = true
      this.authError = ''
      try {
        await logout()
      } catch (error) {
        this.authError = error.data?.detail || error.message || '退出失败'
      } finally {
        this.authenticated = false
        this.authBusy = false
      }
    },
  },
}
</script>

<style>
*, *::before, *::after { box-sizing: border-box; margin: 0; padding: 0; }

body {
  font-family: system-ui, sans-serif;
  font-size: 14px;
  background: #0d1117;
  color: #c9d1d9;
  min-height: 100vh;
}

.layout { display: flex; flex-direction: column; min-height: 100vh; }

nav {
  background: #161b22;
  border-bottom: 1px solid #30363d;
  padding: 0 16px;
  display: flex;
  align-items: center;
  gap: 4px;
  height: 44px;
}
.brand { font-weight: 600; margin-right: 12px; color: #58a6ff; }
.nav-spacer { flex: 1; }
nav button {
  background: none;
  border: none;
  color: #8b949e;
  padding: 6px 12px;
  border-radius: 4px;
  cursor: pointer;
  font-size: 14px;
}
nav button:hover { color: #c9d1d9; background: #21262d; }
nav button.active { color: #c9d1d9; background: #21262d; }

main { padding: 24px; flex: 1; }

.auth-shell {
  min-height: 100vh;
  display: grid;
  place-items: center;
  padding: 24px;
}

.login-card {
  width: min(100%, 420px);
  margin: 0;
}

.login-copy {
  margin-bottom: 16px;
  line-height: 1.5;
}

.login-form {
  display: flex;
  gap: 10px;
  margin-bottom: 12px;
}

.login-form input {
  flex: 1;
  background: #0d1117;
  border: 1px solid #30363d;
  border-radius: 4px;
  color: #c9d1d9;
  padding: 8px 10px;
  font-size: 14px;
}

.card {
  background: #161b22;
  border: 1px solid #30363d;
  border-radius: 6px;
  padding: 16px;
  margin-bottom: 12px;
}

h2 { font-size: 18px; margin-bottom: 16px; color: #e6edf3; }
h3 { font-size: 15px; margin-bottom: 10px; color: #e6edf3; }

.error { color: #f85149; }
.muted { color: #8b949e; font-size: 13px; }

details summary { cursor: pointer; color: #8b949e; font-size: 13px; margin-top: 8px; }
details ol { margin: 6px 0 0 20px; font-size: 13px; color: #8b949e; }

.toolbar {
  display: flex;
  align-items: center;
  gap: 12px;
  margin-bottom: 16px;
  flex-wrap: wrap;
}
.toolbar label { display: flex; align-items: center; gap: 6px; color: #8b949e; }
.toolbar select, .toolbar input {
  background: #0d1117;
  border: 1px solid #30363d;
  border-radius: 4px;
  color: #c9d1d9;
  padding: 4px 8px;
  font-size: 14px;
}

button {
  background: #21262d;
  border: 1px solid #30363d;
  border-radius: 4px;
  color: #c9d1d9;
  padding: 5px 12px;
  cursor: pointer;
  font-size: 13px;
}
button:hover { background: #30363d; }
button:disabled { opacity: 0.5; cursor: default; }

.btn-on  { background: #1f6feb33; border-color: #1f6feb; color: #58a6ff; }
.btn-off { background: #f8514933; border-color: #f85149; color: #f85149; }
.btn-on:hover  { background: #1f6feb55; }
.btn-off:hover { background: #f8514955; }
.small { padding: 2px 8px; font-size: 12px; }

.rule-grid { display: flex; flex-direction: column; gap: 4px; }
.rule-row {
  display: flex;
  align-items: center;
  justify-content: space-between;
  padding: 6px 10px;
  background: #0d1117;
  border: 1px solid #21262d;
  border-radius: 4px;
}
.rule-name { font-size: 13px; font-family: monospace; color: #c9d1d9; }

/* Toggle switch */
.toggle-wrap { display: flex; align-items: center; gap: 8px; }
.toggle {
  position: relative;
  width: 36px;
  height: 20px;
  flex-shrink: 0;
}
.toggle input { opacity: 0; width: 0; height: 0; }
.toggle-slider {
  position: absolute;
  inset: 0;
  background: #30363d;
  border-radius: 20px;
  cursor: pointer;
  transition: background 0.2s;
}
.toggle-slider::before {
  content: '';
  position: absolute;
  width: 14px;
  height: 14px;
  left: 3px;
  top: 3px;
  background: #8b949e;
  border-radius: 50%;
  transition: transform 0.2s, background 0.2s;
}
.toggle input:checked + .toggle-slider { background: #1f6feb44; }
.toggle input:checked + .toggle-slider::before { transform: translateX(16px); background: #58a6ff; }

.groups-layout { display: grid; grid-template-columns: 1fr 1fr; gap: 16px; }
@media (max-width: 600px) { .groups-layout { grid-template-columns: 1fr; } }

.groups-layout section {
  background: #161b22;
  border: 1px solid #30363d;
  border-radius: 6px;
  padding: 16px;
}
.groups-layout ul { list-style: none; margin-bottom: 12px; }
.groups-layout li {
  display: flex;
  align-items: center;
  justify-content: space-between;
  padding: 4px 0;
  border-bottom: 1px solid #21262d;
  font-size: 13px;
}
.groups-layout li:last-child { border-bottom: none; }
.add-row { display: flex; gap: 8px; margin-top: 8px; }
.add-row input, .add-row select {
  flex: 1;
  background: #0d1117;
  border: 1px solid #30363d;
  border-radius: 4px;
  color: #c9d1d9;
  padding: 4px 8px;
  font-size: 13px;
}

/* Toast */
.toast {
  position: fixed;
  bottom: 24px;
  left: 50%;
  transform: translateX(-50%);
  background: #21262d;
  border: 1px solid #30363d;
  border-radius: 6px;
  padding: 8px 20px;
  font-size: 13px;
  color: #c9d1d9;
  z-index: 9999;
  pointer-events: none;
  white-space: nowrap;
}
.toast.error { border-color: #f85149; color: #f85149; }
.toast.info  { border-color: #58a6ff; color: #58a6ff; }
.toast-enter-active, .toast-leave-active { transition: opacity 0.2s, transform 0.2s; }
.toast-enter-from, .toast-leave-to { opacity: 0; transform: translateX(-50%) translateY(8px); }
</style>
