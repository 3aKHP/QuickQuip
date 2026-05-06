<template>
  <!-- Desktop sidebar (≥768px) -->
  <aside class="app-sidebar">
    <span class="brand">
      <UiIcon name="Bot" :size="20" />
      <span class="brand-text">QuickQuip</span>
    </span>

    <div class="nav-items">
      <router-link
        v-for="item in items"
        :key="item.key"
        :to="item.path"
        custom
        v-slot="{ navigate, isActive }"
      >
        <UiNavItem
          :label="item.label"
          :icon="item.icon"
          :active="isActive"
          @click="navigate"
        />
      </router-link>
    </div>

    <span class="nav-spacer" />

    <div class="sidebar-footer">
      <a href="/ops/" class="version-link" title="试试新版 QQ 风格界面">
        <UiIcon name="RotateCw" :size="14" />
        <span>新版</span>
      </a>
      <button class="theme-toggle" title="切换亮/暗主题" @click="toggleTheme">
        <UiIcon name="Settings" :size="15" />
      </button>
      <UiButton size="sm" variant="ghost" icon="LogOut" :disabled="logoutDisabled" @click="$emit('logout')">
        退出
      </UiButton>
    </div>
  </aside>

  <!-- Mobile top bar + drawer (<768px) -->
  <div class="mobile-bar">
    <button class="hamburger" @click="drawerOpen = true" aria-label="打开菜单">
      <UiIcon name="Menu" :size="20" />
    </button>
    <span class="brand">
      <UiIcon name="Bot" :size="18" />
      <span>QuickQuip</span>
    </span>
    <button class="theme-toggle-mobile" title="切换亮/暗主题" @click="toggleTheme">
      <UiIcon name="Settings" :size="16" />
    </button>
  </div>

  <!-- Slide-in drawer overlay -->
  <Transition name="fade">
    <div v-if="drawerOpen" class="drawer-overlay" @click.self="drawerOpen = false">
      <Transition name="slide-up">
        <nav v-if="drawerOpen" class="drawer">
          <div class="drawer-head">
            <span class="brand">
              <UiIcon name="Bot" :size="18" />
              <span>QuickQuip</span>
            </span>
            <button class="drawer-close" @click="drawerOpen = false" aria-label="关闭菜单">
              <UiIcon name="X" :size="20" />
            </button>
          </div>

          <div class="nav-items">
            <router-link
              v-for="item in items"
              :key="item.key"
              :to="item.path"
              custom
              v-slot="{ navigate, isActive }"
            >
              <UiNavItem
                :label="item.label"
                :icon="item.icon"
                :active="isActive"
                @click="drawerOpen = false; navigate()"
              />
            </router-link>
          </div>

          <div class="drawer-footer">
            <a href="/ops/" class="version-link" @click="drawerOpen = false">
              <UiIcon name="RotateCw" :size="14" />
              <span>新版</span>
            </a>
            <UiButton size="sm" variant="ghost" icon="LogOut" :disabled="logoutDisabled" @click="$emit('logout'); drawerOpen = false">
              退出
            </UiButton>
          </div>
        </nav>
      </Transition>
    </div>
  </Transition>
</template>

<script setup lang="ts">
import { ref } from 'vue'
import type { NavItem } from '../../config/nav'
import UiNavItem from '../ui/UiNavItem.vue'
import UiButton from '../ui/UiButton.vue'
import UiIcon from '../ui/UiIcon.vue'

defineProps<{
  items: NavItem[]
  logoutDisabled?: boolean
}>()

defineEmits<{
  logout: []
}>()

const drawerOpen = ref(false)

function toggleTheme() {
  const fn = (window as any).__qqToggleTheme
  if (fn) fn()
}
</script>

<style scoped>
/* ========================================================================
   Desktop Sidebar (≥768px)
   ======================================================================== */
.app-sidebar {
  width: var(--qq-sidebar-width);
  flex-shrink: 0;
  background: var(--qq-surface);
  border-right: 1px solid var(--qq-border);
  display: flex;
  flex-direction: column;
  padding: var(--qq-gap-md) 0;
  height: 100vh;
  position: sticky;
  top: 0;
  overflow-y: auto;
}

.brand {
  display: inline-flex;
  align-items: center;
  gap: var(--qq-gap-sm);
  font-weight: 600;
  color: var(--qq-accent);
  padding: 0 var(--qq-gap-md);
  margin-bottom: var(--qq-gap-md);
  font-size: var(--qq-text-md);
}

.brand-text {
  white-space: nowrap;
}

.nav-items {
  display: flex;
  flex-direction: column;
  gap: 2px;
  padding: 0 var(--qq-gap-sm);
}

.nav-spacer {
  flex: 1;
}

.sidebar-footer {
  padding: var(--qq-gap-sm) var(--qq-gap-sm) 0;
  display: flex;
  flex-direction: column;
  gap: var(--qq-gap-xs);
  border-top: 1px solid var(--qq-border);
  margin-top: var(--qq-gap-sm);
}

.version-link {
  display: inline-flex;
  align-items: center;
  gap: var(--qq-gap-sm);
  padding: 6px 8px;
  border: 1px solid transparent;
  border-radius: var(--qq-radius-sm);
  color: var(--qq-text-muted);
  text-decoration: none;
  font-size: var(--qq-text-sm);
  transition: color var(--qq-transition-fast), background var(--qq-transition-fast);
  align-self: center;
}

.version-link:hover {
  color: var(--qq-accent);
  background: var(--qq-surface-elevated);
}

.theme-toggle {
  display: inline-flex;
  align-items: center;
  justify-content: center;
  padding: 6px;
  border: 1px solid transparent;
  border-radius: var(--qq-radius-sm);
  background: transparent;
  color: var(--qq-text-muted);
  cursor: pointer;
  transition: color var(--qq-transition-fast), background var(--qq-transition-fast), border-color var(--qq-transition-fast);
  align-self: center;
}

.theme-toggle:hover {
  color: var(--qq-text);
  background: var(--qq-surface-elevated);
  border-color: var(--qq-border);
}

/* ========================================================================
   Mobile Bar (<768px)
   ======================================================================== */
.mobile-bar {
  display: none;
}

/* ========================================================================
   Drawer (mobile slide-in)
   ======================================================================== */
.drawer-overlay {
  position: fixed;
  inset: 0;
  background: rgba(0, 0, 0, 0.5);
  z-index: 9990;
  display: flex;
}

.drawer {
  width: 280px;
  max-width: 85vw;
  background: var(--qq-surface);
  border-right: 1px solid var(--qq-border);
  display: flex;
  flex-direction: column;
  height: 100%;
  padding: var(--qq-gap-md) 0;
  box-shadow: var(--qq-shadow-lg);
}

.drawer-head {
  display: flex;
  align-items: center;
  justify-content: space-between;
  padding: 0 var(--qq-gap-md);
  margin-bottom: var(--qq-gap-md);
}

.drawer-close {
  display: flex;
  align-items: center;
  justify-content: center;
  background: transparent;
  border: 1px solid transparent;
  border-radius: var(--qq-radius-sm);
  color: var(--qq-text-muted);
  cursor: pointer;
  padding: 4px;
  transition: color var(--qq-transition-fast), background var(--qq-transition-fast);
}

.drawer-close:hover {
  color: var(--qq-text);
  background: var(--qq-surface-elevated);
}

.drawer-footer {
  padding: var(--qq-gap-sm);
  border-top: 1px solid var(--qq-border);
  margin-top: auto;
}

/* ========================================================================
   Responsive Switching
   ======================================================================== */
@media (max-width: 767px) {
  .app-sidebar {
    display: none;
  }

  .mobile-bar {
    display: flex;
    align-items: center;
    justify-content: space-between;
    padding: 0 var(--qq-gap-md);
    height: 52px;
    background: var(--qq-surface);
    border-bottom: 1px solid var(--qq-border);
    position: sticky;
    top: 0;
    z-index: 100;
  }

  .mobile-bar .brand {
    margin-bottom: 0;
    padding: 0;
  }

  .hamburger {
    display: flex;
    align-items: center;
    justify-content: center;
    background: transparent;
    border: 1px solid transparent;
    border-radius: var(--qq-radius-sm);
    color: var(--qq-text-muted);
    cursor: pointer;
    padding: 6px;
    transition: color var(--qq-transition-fast), background var(--qq-transition-fast);
  }

  .hamburger:hover {
    color: var(--qq-text);
    background: var(--qq-surface-elevated);
  }

  .theme-toggle-mobile {
    display: flex;
    align-items: center;
    justify-content: center;
    background: transparent;
    border: 1px solid transparent;
    border-radius: var(--qq-radius-sm);
    color: var(--qq-text-muted);
    cursor: pointer;
    padding: 6px;
    transition: color var(--qq-transition-fast), background var(--qq-transition-fast);
  }

  .theme-toggle-mobile:hover {
    color: var(--qq-text);
    background: var(--qq-surface-elevated);
  }
}

@media (min-width: 768px) {
  .mobile-bar, .drawer-overlay, .drawer {
    display: none;
  }
}
</style>
