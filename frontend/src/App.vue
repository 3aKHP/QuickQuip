<template>
  <div ref="appRootRef" class="app-root">
    <!-- Ambient light field -->
    <LightField :mode="authenticated ? 'ambient' : 'showcase'" :domain="activeDomain" />

    <Transition name="auth-unlock" mode="out-in">
      <!-- Unauthenticated -->
      <LoginView
        v-if="authReady && !authenticated"
        key="login"
        :submitting="authBusy"
        :error="authError"
        @submit="handleLogin"
      />

      <!-- Main layout -->
      <div v-else-if="authReady" key="layout" class="layout" :class="{ 'layout--receded': paletteOpen }">
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
            <div :key="routeTraceKey" class="route-trace" aria-hidden="true" />
            <div class="page-stage">
              <router-view v-slot="{ Component, route: viewRoute }">
                <Transition name="page-shell">
                  <component :is="Component" :key="viewRoute.path" class="page-view" />
                </Transition>
              </router-view>
            </div>
          </main>
        </div>
      </div>

      <!-- Checking auth -->
      <div v-else key="checking" class="auth-shell">
        <UiCard padding="lg" shadow="md" class="login-card">
          <h2>正在检查登录状态</h2>
          <p class="muted">稍等，正在确认当前浏览器会话是否仍然有效。</p>
        </UiCard>
      </div>
    </Transition>

    <!-- Command Palette（全局 Cmd/Ctrl+K 快速跳转与操作） -->
    <CommandPalette
      v-if="authenticated"
      :theme="theme"
      :logout-disabled="authBusy"
      @toggle-theme="toggleTheme"
      @logout="handleLogout"
    />

    <!-- Toast（提升至 app-root 级，登录页同样可提示；悬停暂停、点击关闭） -->
    <Transition name="toast">
      <div
        v-if="toastMsg"
        class="toast"
        :class="toastType"
        :role="toastType === 'error' ? 'alert' : 'status'"
        :aria-live="toastType === 'error' ? 'assertive' : 'polite'"
        @click="dismissToast"
        @mouseenter="pauseToast"
        @mouseleave="resumeToast"
      >
        <UiIcon :name="toastType === 'error' ? 'CircleX' : 'Info'" :size="16" class="toast__icon" />
        <span class="toast__text">{{ toastMsg }}</span>
      </div>
    </Transition>
  </div>
</template>

<script setup lang="ts">
import { computed, nextTick, onMounted, onBeforeUnmount, ref, watch } from 'vue'
import { useRoute } from 'vue-router'
import LoginView from './views/LoginView.vue'
import AppNav from './components/layout/AppNav.vue'
import StatusBar from './components/layout/StatusBar.vue'
import CommandPalette from './components/layout/CommandPalette.vue'
import LightField from './components/background/LightField.vue'
import UiCard from './components/ui/UiCard.vue'
import UiIcon from './components/ui/UiIcon.vue'
import { dismissToast, pauseToast, resumeToast, toastMsg, toastType } from './toast'
import { NAV_ITEMS, NAV_SECTIONS } from './config/nav'
import { useAuth } from './composables/useAuth'
import { useTheme } from './composables/useTheme'
import { useCommandPalette } from './composables/useCommandPalette'
import { usePointerGlow } from './composables/usePointerGlow'
import { triggerRouteWarp, type WarpDirection } from './lib/lightFieldBus'

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
const { paletteOpen, recordVisitedPath } = useCommandPalette()
const route = useRoute()
const appRootRef = ref<HTMLElement | null>(null)
const contentEl = ref<HTMLElement | null>(null)
const routeMotionClass = ref('route-motion-forward')
const routeTraceKey = ref(0)

// 全站统一指针物理引擎（单监听器驱动邻近追光、3D 玻璃微倾与微磁吸）
usePointerGlow(appRootRef)

const activeDomain = computed(() => {
  const item = NAV_ITEMS.find(entry => entry.path === route.path)
  return item?.section || 'overview'
})

function routeDepth(path: string): number {
  if (path === '/') return 0
  return path.split('/').filter(Boolean).length
}

watch(
  () => route.path,
  (nextPath, prevPath) => {
    const nextDepth = routeDepth(nextPath)
    const prevDepth = prevPath ? routeDepth(prevPath) : nextDepth

    let warpDir: WarpDirection = 'switch'
    if (nextDepth > prevDepth) {
      routeMotionClass.value = 'route-motion-forward'
      warpDir = 'forward'
    } else if (nextDepth < prevDepth) {
      routeMotionClass.value = 'route-motion-back'
      warpDir = 'back'
    } else {
      routeMotionClass.value = 'route-motion-switch'
      warpDir = 'switch'
    }

    routeTraceKey.value += 1
    recordVisitedPath(nextPath)
    if (prevPath !== undefined && prevPath !== nextPath) {
      const prevDomain = NAV_ITEMS.find(entry => entry.path === prevPath)?.section || 'overview'
      const nextDomain = NAV_ITEMS.find(entry => entry.path === nextPath)?.section || 'overview'
      triggerRouteWarp(warpDir, prevDomain !== nextDomain ? 1.35 : 1)
    }

    void nextTick(() => {
      contentEl.value?.scrollTo({ top: 0 })
    })
  },
  { immediate: true },
)

if (import.meta.env.DEV) {
  (window as any).__qqToggleTheme = toggleTheme
}

onMounted(() => {
  loadTheme()
  attachUnauthorizedHandler()
  initializeAuth()
})

onBeforeUnmount(() => {
  detachUnauthorizedHandler()
  if (import.meta.env.DEV) {
    delete (window as any).__qqToggleTheme
  }
})
</script>

<style>
.app-root {
  display: flex;
  flex-direction: column;
  height: 100vh;
  height: 100dvh;
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
  transform-origin: 50% 44%;
  transition:
    transform 240ms var(--qq-ease-out),
    filter 240ms var(--qq-ease-out),
    border-radius 240ms var(--qq-ease-out);
}

/* Command Palette 打开时主界面微微退后，形成桌面级空间景深 */
.layout--receded {
  transform: scale(0.986);
  filter: blur(1.5px) brightness(0.94);
  border-radius: 10px;
  overflow: hidden;
  pointer-events: none;
}

@media (prefers-reduced-motion: reduce) {
  .layout {
    transition: none;
  }

  .layout--receded {
    transform: none;
    filter: none;
    border-radius: 0;
  }
}

html[data-motion="reduced"] .layout {
  transition: none;
}

html[data-motion="reduced"] .layout--receded {
  transform: none;
  filter: none;
  border-radius: 0;
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

/* Route trace sweep — 每次换页重新挂载触发顶部一道蓝青辉光流带横扫 */
.route-trace {
  position: sticky;
  top: 0;
  z-index: 6;
  height: 2px;
  margin-bottom: -2px;
  flex-shrink: 0;
  pointer-events: none;
  opacity: 0;
  border-radius: var(--qq-radius-full);
  background:
    linear-gradient(90deg, transparent, var(--qq-route-trace-color) 36%, var(--qq-route-trace-secondary) 64%, transparent);
  box-shadow: 0 0 12px var(--qq-primary-glow);
  transform: translateX(-48%);
  animation: route-trace-sweep 420ms var(--qq-ease-out) 1;
}

.page-stage {
  position: relative;
  width: 100%;
}

.auth-shell {
  position: relative;
  z-index: 1;
  height: 100vh;
  height: 100dvh;
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
  max-width: min(92vw, 480px);
  background:
    linear-gradient(180deg, var(--qq-shell-glass-highlight), transparent 58%),
    var(--qq-shell-drawer-bg);
  border: 1px solid var(--qq-shell-glass-border);
  border-radius: var(--qq-radius-card);
  padding: 10px 18px;
  font-size: var(--qq-text-sm);
  line-height: 1.45;
  color: var(--qq-text);
  z-index: var(--qq-z-toast);
  pointer-events: auto;
  cursor: pointer;
  white-space: normal;
  word-break: break-word;
  backdrop-filter: blur(16px) saturate(1.2);
  -webkit-backdrop-filter: blur(16px) saturate(1.2);
  box-shadow: var(--qq-shadow-lg);
}

.toast__icon {
  flex-shrink: 0;
}

.toast.error {
  border-color: var(--qq-toast-border-error);
  color: var(--qq-danger-ink);
}

.toast.info {
  border-color: var(--qq-toast-border-info);
  color: var(--qq-primary-ink);
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

  .toast {
    bottom: auto;
    top: calc(var(--qq-status-bar-height) + 56px + env(safe-area-inset-top, 0px));
    transform: translateX(-50%);
  }

  .toast.toast-enter-from,
  .toast.toast-leave-to {
    transform: translate(-50%, -8px);
  }
}
</style>
