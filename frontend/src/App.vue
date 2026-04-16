<template>
  <LoginView
    v-if="authReady && !authenticated"
    :submitting="authBusy"
    :error="authError"
    @submit="handleLogin"
  />
  <div v-else-if="authReady" class="layout">
    <AppNav
      :items="NAV_ITEMS"
      :active-key="view"
      :logout-disabled="authBusy"
      @update:active-key="view = $event"
      @logout="handleLogout"
    />
    <main>
      <Transition name="fade" mode="out-in">
        <component :is="activeComponent" :key="view" />
      </Transition>
    </main>
    <Transition name="toast">
      <div v-if="toastMsg" class="toast" :class="toastType">
        <UiIcon :name="toastType === 'error' ? 'CircleX' : 'Info'" :size="16" />
        <span>{{ toastMsg }}</span>
      </div>
    </Transition>
  </div>
  <div v-else class="auth-shell">
    <UiCard padding="lg" shadow="md" class="login-card">
      <h2>正在检查登录状态</h2>
      <p class="muted">稍等，正在确认当前浏览器会话是否仍然有效。</p>
    </UiCard>
  </div>
</template>

<script>
import LoginView from './views/LoginView.vue'
import AppNav from './components/layout/AppNav.vue'
import UiCard from './components/ui/UiCard.vue'
import UiIcon from './components/ui/UiIcon.vue'
import { toastMsg, toastType } from './toast.js'
import { getAuthState, login, logout } from './api/auth.js'
import { setUnauthorizedHandler } from './api/index.js'
import { NAV_ITEMS } from './config/nav.js'

export default {
  components: {
    LoginView,
    AppNav, UiCard, UiIcon,
  },
  data: () => ({
    view: 'stats',
    authReady: false,
    authenticated: false,
    authBusy: false,
    authError: '',
    toastMsg,
    toastType,
    NAV_ITEMS,
  }),
  computed: {
    activeComponent() {
      const item = NAV_ITEMS.find(i => i.key === this.view)
      return item ? item.component : null
    },
  },
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
.layout {
  display: flex;
  flex-direction: column;
  min-height: 100vh;
}

main {
  padding: var(--qq-gap-lg);
  flex: 1;
}

main > .fade-enter-active,
main > .fade-leave-active {
  transition: opacity var(--qq-transition-base), transform var(--qq-transition-base);
}

main > .fade-enter-from,
main > .fade-leave-to {
  opacity: 0;
  transform: translateY(4px);
}

.auth-shell {
  min-height: 100vh;
  display: grid;
  place-items: center;
  padding: var(--qq-gap-lg);
}

.login-card {
  width: min(100%, 420px);
}

.login-card h2 {
  font-size: 18px;
  margin-bottom: var(--qq-gap-sm);
  color: var(--qq-text);
}

.muted {
  color: var(--qq-text-muted);
  font-size: 13px;
  line-height: 1.6;
}

.error {
  color: var(--qq-danger);
}

/* Toast */
.toast {
  position: fixed;
  bottom: var(--qq-gap-lg);
  left: 50%;
  transform: translateX(-50%);
  display: inline-flex;
  align-items: center;
  gap: var(--qq-gap-sm);
  background: var(--qq-surface-elevated);
  border: 1px solid var(--qq-border-strong);
  border-radius: var(--qq-radius-md);
  padding: 10px 18px;
  font-size: 13px;
  color: var(--qq-text);
  z-index: 9999;
  pointer-events: none;
  white-space: nowrap;
  box-shadow: var(--qq-shadow-md);
}

.toast.error {
  border-color: rgba(248, 81, 73, 0.45);
  color: var(--qq-danger);
}

.toast.info {
  border-color: rgba(88, 166, 255, 0.45);
  color: var(--qq-accent);
}

/* Legacy helpers kept for backward compat during migration */
h2 { font-size: 18px; margin-bottom: var(--qq-gap-md); color: var(--qq-text); }
h3 { font-size: 15px; margin-bottom: var(--qq-gap-sm); color: var(--qq-text); }

.toolbar {
  display: flex;
  align-items: center;
  gap: var(--qq-gap-md);
  margin-bottom: var(--qq-gap-md);
  flex-wrap: wrap;
}

.toolbar label {
  display: flex;
  align-items: center;
  gap: var(--qq-gap-xs);
  color: var(--qq-text-muted);
  font-size: 13px;
}

.toolbar select,
.toolbar input {
  background: var(--qq-surface-strong);
  border: 1px solid var(--qq-border);
  border-radius: var(--qq-radius-sm);
  color: var(--qq-text);
  padding: 5px 10px;
  font-size: 14px;
  outline: none;
}

.toolbar select:focus,
.toolbar input:focus {
  border-color: var(--qq-accent);
  box-shadow: 0 0 0 3px var(--qq-accent-soft);
}

.add-row {
  display: flex;
  gap: var(--qq-gap-sm);
  margin-top: var(--qq-gap-sm);
  flex-wrap: wrap;
}

.add-row input,
.add-row select {
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

.add-row input:focus,
.add-row select:focus {
  border-color: var(--qq-accent);
  box-shadow: 0 0 0 3px var(--qq-accent-soft);
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

.groups-layout section {
  background: var(--qq-surface);
  border: 1px solid var(--qq-border);
  border-radius: var(--qq-radius-md);
  padding: var(--qq-gap-md);
  box-shadow: var(--qq-shadow-sm);
}

.groups-layout ul {
  list-style: none;
  margin-bottom: var(--qq-gap-sm);
}

.groups-layout li {
  display: flex;
  align-items: center;
  justify-content: space-between;
  padding: 6px 0;
  border-bottom: 1px solid var(--qq-border);
  font-size: 13px;
}

.groups-layout li:last-child {
  border-bottom: none;
}
</style>
