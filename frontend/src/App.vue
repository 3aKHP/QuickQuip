<template>
  <div class="app-root">
    <!-- Ambient light field -->
    <LightField :mode="authenticated ? 'ambient' : 'showcase'" />

    <!-- Unauthenticated -->
    <LoginView
      v-if="authReady && !authenticated"
      :submitting="authBusy"
      :error="authError"
      @submit="handleLogin"
    />

    <!-- Main layout -->
    <div v-else-if="authReady" class="layout">
      <StatusBar />
      <div class="layout__body">
        <AppNav
          :items="NAV_ITEMS"
          :sections="NAV_SECTIONS"
          :logout-disabled="authBusy"
          :theme-icon="theme === 'dark' ? 'Sun' : 'Moon'"
          :theme-label="theme === 'dark' ? '亮色' : '暗色'"
          @logout="handleLogout"
          @toggle-theme="toggleTheme"
        />
        <main ref="contentEl" class="content" :class="routeMotionClass">
          <div class="page-stage">
            <router-view v-slot="{ Component, route: viewRoute }">
              <Transition name="page-shell">
                <component :is="Component" :key="viewRoute.fullPath" class="page-view" />
              </Transition>
            </router-view>
          </div>
        </main>
      </div>

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
import { nextTick, onMounted, onBeforeUnmount, ref, watch } from 'vue'
import { useRoute } from 'vue-router'
import LoginView from './views/LoginView.vue'
import AppNav from './components/layout/AppNav.vue'
import StatusBar from './components/layout/StatusBar.vue'
import LightField from './components/background/LightField.vue'
import UiCard from './components/ui/UiCard.vue'
import UiIcon from './components/ui/UiIcon.vue'
import { toastMsg, toastType } from './toast'
import { NAV_ITEMS, NAV_SECTIONS } from './config/nav'
import { useAuth } from './composables/useAuth'
import { useTheme } from './composables/useTheme'

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

const { theme, loadTheme, toggleTheme } = useTheme()
const route = useRoute()
const contentEl = ref<HTMLElement | null>(null)
const routeMotionClass = ref('route-motion-forward')

function routeDepth(path: string): number {
  if (path === '/') return 0
  return path.split('/').filter(Boolean).length
}

watch(
  () => route.fullPath,
  (nextPath, prevPath) => {
    const nextDepth = routeDepth(nextPath)
    const prevDepth = prevPath ? routeDepth(prevPath) : nextDepth

    if (nextDepth > prevDepth) {
      routeMotionClass.value = 'route-motion-forward'
    } else if (nextDepth < prevDepth) {
      routeMotionClass.value = 'route-motion-back'
    } else {
      routeMotionClass.value = 'route-motion-switch'
    }

    void nextTick(() => {
      contentEl.value?.scrollTo({ top: 0 })
    })
  },
  { immediate: true },
)

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
  position: relative;
}

.layout {
  display: flex;
  flex-direction: column;
  flex: 1;
  min-height: 0;
  position: relative;
  z-index: 1;
}

.layout__body {
  display: flex;
  flex-direction: row;
  flex: 1;
  min-height: 0;
}

.content {
  position: relative;
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

/* Route trace sweep — 换页时顶部一道蓝青光带横扫 */
.content::before {
  content: "";
  position: absolute;
  top: var(--qq-gap-md);
  left: var(--qq-gap-lg);
  right: var(--qq-gap-lg);
  z-index: 6;
  height: 1px;
  pointer-events: none;
  opacity: 0;
  background:
    linear-gradient(90deg, transparent, var(--qq-route-trace-color), transparent 42%),
    linear-gradient(90deg, transparent 56%, var(--qq-route-trace-secondary), transparent);
  transform: translateX(-42%);
}

.content.route-motion-forward::before,
.content.route-motion-back::before,
.content.route-motion-switch::before {
  animation: route-trace-sweep 360ms linear 1;
}

.page-stage {
  position: relative;
  width: 100%;
}

.auth-shell {
  position: relative;
  z-index: 1;
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
  background:
    linear-gradient(180deg, var(--qq-shell-glass-highlight), transparent 58%),
    var(--qq-shell-drawer-bg);
  border: 1px solid var(--qq-shell-glass-border);
  border-radius: var(--qq-radius-card);
  padding: 10px 18px;
  font-size: var(--qq-text-sm);
  color: var(--qq-text);
  z-index: 9999;
  pointer-events: none;
  white-space: nowrap;
  backdrop-filter: blur(16px) saturate(1.2);
  -webkit-backdrop-filter: blur(16px) saturate(1.2);
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
  .layout__body {
    flex-direction: column;
  }

  .content {
    padding: var(--qq-gap-md);
    padding-bottom: calc(var(--qq-gap-lg) + env(safe-area-inset-bottom, 0px));
  }

  .content::before {
    left: var(--qq-gap-md);
    right: var(--qq-gap-md);
  }

  .toast {
    bottom: auto;
    top: calc(var(--qq-status-bar-height) + 56px + env(safe-area-inset-top, 0px));
    transform: translateX(-50%);
  }
}
</style>
