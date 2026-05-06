<template>
  <div class="app-root">
    <!-- Unauthenticated -->
    <LoginView
      v-if="authReady && !authenticated"
      :submitting="authBusy"
      :error="authError"
      @submit="handleLogin"
    />

    <!-- Main layout -->
    <div v-else-if="authReady" class="layout">
      <AppNav
        :items="NAV_ITEMS"
        :sections="NAV_SECTIONS"
        :logout-disabled="authBusy"
        :theme-icon="theme === 'dark' ? 'Sun' : 'Moon'"
        :theme-label="theme === 'dark' ? '亮色' : '暗色'"
        @logout="handleLogout"
        @toggle-theme="toggleTheme"
      />
      <main class="content">
        <router-view v-slot="{ Component }">
          <Transition name="fade" mode="out-in">
            <component :is="Component" />
          </Transition>
        </router-view>
      </main>

      <!-- Toast -->
      <Transition name="toast">
        <div v-if="toastMsg" class="toast" :class="toastType">
          <UiIcon :name="toastType === 'error' ? 'CircleX' : 'Info'" :size="16" />
          <span>{{ toastMsg }}</span>
        </div>
      </Transition>
    </div>

    <!-- Checking auth -->
    <div v-else class="auth-shell">
      <UiCard padding="lg" shadow="md" class="login-card">
        <h2>正在检查登录状态</h2>
        <p class="muted">稍等，正在确认当前浏览器会话是否仍然有效。</p>
      </UiCard>
    </div>
  </div>
</template>

<script setup lang="ts">
import { onMounted, onBeforeUnmount, ref, watch } from 'vue'
import LoginView from './views/LoginView.vue'
import AppNav from './components/layout/AppNav.vue'
import UiCard from './components/ui/UiCard.vue'
import UiIcon from './components/ui/UiIcon.vue'
import { toastMsg, toastType } from './toast'
import { NAV_ITEMS, NAV_SECTIONS } from './config/nav'
import { useAuth } from './composables/useAuth'

const {
  authReady,
  authenticated,
  authBusy,
  authError,
  initializeAuth,
  handleLogin,
  handleLogout,
  attachUnauthorizedHandler,
  detachUnauthorizedHandler,
} = useAuth()

const theme = ref<'light' | 'dark'>('light')

function applyTheme(t: 'light' | 'dark') {
  document.documentElement.setAttribute('data-theme', t)
}

function loadTheme() {
  try {
    const stored = localStorage.getItem('qq-admin-theme')
    if (stored === 'light' || stored === 'dark') {
      theme.value = stored
    }
  } catch { /* ignore */ }
  applyTheme(theme.value)
}

function toggleTheme() {
  theme.value = theme.value === 'light' ? 'dark' : 'light'
  try { localStorage.setItem('qq-admin-theme', theme.value) } catch { /* ignore */ }
  applyTheme(theme.value)
}

watch(theme, applyTheme)

;(window as any).__qqToggleTheme = toggleTheme

onMounted(() => {
  loadTheme()
  attachUnauthorizedHandler()
  initializeAuth()
})

onBeforeUnmount(() => {
  detachUnauthorizedHandler()
})
</script>

<style>
.app-root {
  display: flex;
  flex-direction: column;
  height: 100vh;
  overflow: hidden;
}

.layout {
  display: flex;
  flex-direction: row;
  flex: 1;
  min-height: 0;
}

.content {
  padding: var(--qq-gap-lg);
  flex: 1;
  display: flex;
  flex-direction: column;
  min-height: 0;
  overflow-y: auto;
  max-width: var(--qq-content-max-width);
  margin: 0 auto;
  width: 100%;
}

.auth-shell {
  height: 100vh;
  display: grid;
  place-items: center;
  padding: var(--qq-gap-lg);
}

.login-card {
  width: min(100%, 420px);
}

.login-card h2 {
  font-size: var(--qq-text-md);
  margin-bottom: var(--qq-gap-sm);
  color: var(--qq-text);
}

.muted {
  color: var(--qq-text-muted);
  font-size: var(--qq-text-sm);
  line-height: 1.6;
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
  border-radius: var(--qq-radius-card);
  padding: 10px 18px;
  font-size: var(--qq-text-sm);
  color: var(--qq-text);
  z-index: 9999;
  pointer-events: none;
  white-space: nowrap;
  box-shadow: var(--qq-shadow-md);
}

.toast.error {
  border-color: var(--qq-toast-border-error);
  color: var(--qq-danger);
}

.toast.info {
  border-color: var(--qq-toast-border-info);
  color: var(--qq-primary);
}

/* Responsive */
@media (max-width: 767px) {
  .layout {
    flex-direction: column;
  }

  .content {
    padding: var(--qq-gap-md);
  }
}
</style>
