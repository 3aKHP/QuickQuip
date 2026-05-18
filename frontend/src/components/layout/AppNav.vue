<template>
  <aside class="app-shell-nav">
    <div class="domain-rail">
      <router-link to="/" custom v-slot="{ navigate, isActive }">
        <button
          class="brand-mark"
          :class="{ active: isActive }"
          title="QuickQuip Admin"
          aria-label="QuickQuip Admin"
          @click="navigate"
        >
          <svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 48 48" fill="none" class="brand-mark__icon">
            <defs>
              <filter id="bm-shadow" x="-30%" y="-30%" width="160%" height="160%">
                <feDropShadow dx="0" dy="2" stdDeviation="3" flood-color="#000000" flood-opacity="0.2" />
              </filter>
              <linearGradient id="bm-grad1" x1="0%" y1="0%" x2="100%" y2="100%">
                <stop offset="0%" stop-color="#60A5FA" />
                <stop offset="100%" stop-color="#2563EB" />
              </linearGradient>
              <linearGradient id="bm-grad2" x1="0%" y1="100%" x2="100%" y2="0%">
                <stop offset="0%" stop-color="#818CF8" />
                <stop offset="100%" stop-color="#3730A3" />
              </linearGradient>
              <linearGradient id="bm-grad-tail" x1="0%" y1="0%" x2="100%" y2="100%">
                <stop offset="0%" stop-color="#2DD4BF" />
                <stop offset="100%" stop-color="#0F766E" />
              </linearGradient>
            </defs>
            <g filter="url(#bm-shadow)" transform="translate(24, 24) scale(0.82) translate(-24, -24)">
              <path d="M 24 42 A 18 18 0 1 0 11.27 11.27 A 22 22 0 1 1 24 42 Z" fill="url(#bm-grad2)" opacity="0.95" />
              <path d="M 24 6 A 18 18 0 1 0 36.73 36.73 A 22 22 0 1 1 24 6 Z" fill="url(#bm-grad1)" opacity="0.95" />
              <path d="M 22 26 C 28 26 38 34 44 44 C 38 40 30 32 24 30 C 22 29 20 27 22 26 Z" fill="url(#bm-grad-tail)" opacity="0.95" />
            </g>
          </svg>
        </button>
      </router-link>

      <nav class="domain-rail__items" aria-label="工作域">
        <button
          v-for="section in sections"
          :key="section.key"
          class="domain-btn"
          :class="{ active: activeSectionKey === section.key }"
          :title="section.label"
          @click="goToSection(section.key)"
        >
          <UiIcon :name="section.icon" :size="20" />
          <span>{{ section.label }}</span>
        </button>
      </nav>

      <div class="domain-rail__tools">
        <button class="rail-tool" :title="themeLabel" @click="$emit('toggleTheme')">
          <UiIcon :name="themeIcon" :size="18" />
        </button>
        <button class="rail-tool" title="退出" :disabled="logoutDisabled" @click="$emit('logout')">
          <UiIcon name="LogOut" :size="18" />
        </button>
      </div>
    </div>

    <div class="section-panel">
      <div class="section-panel__head">
        <span class="section-panel__eyebrow">QuickQuip</span>
        <h2>{{ activeSection?.label || '工作台' }}</h2>
        <p>{{ activeSection?.description || '选择一个工作域继续操作' }}</p>
      </div>

      <nav class="section-panel__nav" aria-label="当前工作域页面">
        <router-link
          v-for="item in activeItems"
          :key="item.key"
          :to="item.path"
          custom
          v-slot="{ navigate, isActive }"
        >
          <button class="page-link" :class="{ active: isActive }" @click="navigate">
            <UiIcon :name="item.icon" :size="17" />
            <span>{{ item.label }}</span>
          </button>
        </router-link>
      </nav>
    </div>
  </aside>

  <div class="mobile-bar">
    <button class="mobile-bar__menu-btn" aria-label="菜单" @click="drawerOpen = true">
      <UiIcon name="Menu" :size="20" />
    </button>
    <span class="mobile-bar__brand">
      <UiIcon name="Bot" :size="20" />
      <span>{{ activeSection?.label || 'QuickQuip' }}</span>
    </span>
    <div class="mobile-bar__actions">
      <button class="mobile-bar__theme-btn" :aria-label="themeLabel" @click="$emit('toggleTheme')">
        <UiIcon :name="themeIcon" :size="18" />
      </button>
      <button class="mobile-bar__theme-btn" title="退出" :disabled="logoutDisabled" @click="$emit('logout')">
        <UiIcon name="LogOut" :size="18" />
      </button>
    </div>
  </div>

  <Transition name="slide-up">
    <div v-if="drawerOpen" class="drawer-overlay" @click.self="drawerOpen = false">
      <aside class="drawer">
        <div class="drawer__head">
          <UiIcon name="Bot" :size="20" />
          <span>QuickQuip Admin</span>
          <button class="drawer__close" aria-label="关闭" @click="drawerOpen = false">
            <UiIcon name="X" :size="18" />
          </button>
        </div>

        <div class="drawer__groups">
          <section v-for="section in sections" :key="section.key" class="drawer-group">
            <button class="drawer-group__title" @click="toggleMobileSection(section.key)">
              <UiIcon :name="section.icon" :size="17" />
              <span>{{ section.label }}</span>
              <UiIcon :name="mobileOpenSections.has(section.key) ? 'ChevronUp' : 'ChevronDown'" :size="16" />
            </button>
            <div v-if="mobileOpenSections.has(section.key)" class="drawer-group__items">
              <router-link
                v-for="item in itemsForSection(section.key)"
                :key="item.key"
                :to="item.path"
                custom
                v-slot="{ navigate, isActive }"
              >
                <button class="drawer-link" :class="{ active: isActive }" @click="navigate(); drawerOpen = false">
                  <UiIcon :name="item.icon" :size="16" />
                  <span>{{ item.label }}</span>
                </button>
              </router-link>
            </div>
          </section>
        </div>

        <div class="drawer__footer">
          <button class="drawer-action" :disabled="logoutDisabled" @click="$emit('logout'); drawerOpen = false">
            <UiIcon name="LogOut" :size="14" />
            <span>退出</span>
          </button>
        </div>
      </aside>
    </div>
  </Transition>
</template>

<script setup lang="ts">
import { computed, ref, watch } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import UiIcon from '../ui/UiIcon.vue'
import type { NavItem, NavSection } from '../../config/nav'

const props = defineProps<{
  items: NavItem[]
  sections: NavSection[]
  logoutDisabled?: boolean
  themeIcon: string
  themeLabel: string
}>()

defineEmits<{
  logout: []
  toggleTheme: []
}>()

const route = useRoute()
const router = useRouter()
const drawerOpen = ref(false)
const mobileOpenSections = ref(new Set<string>())

const activeItem = computed(() => {
  return props.items.find(item => item.path === route.path) || props.items[0]
})

const activeSectionKey = computed(() => activeItem.value?.section || props.sections[0]?.key || '')

const activeSection = computed(() => {
  return props.sections.find(section => section.key === activeSectionKey.value) || props.sections[0]
})

const activeItems = computed(() => itemsForSection(activeSectionKey.value))

function itemsForSection(sectionKey: string): NavItem[] {
  return props.items.filter(item => item.section === sectionKey)
}

function goToSection(sectionKey: string) {
  const first = itemsForSection(sectionKey)[0]
  if (first) router.push(first.path)
}

function toggleMobileSection(sectionKey: string) {
  const next = new Set(mobileOpenSections.value)
  if (next.has(sectionKey)) next.delete(sectionKey)
  else next.add(sectionKey)
  mobileOpenSections.value = next
}

watch(activeSectionKey, (sectionKey) => {
  mobileOpenSections.value = new Set([sectionKey])
}, { immediate: true })
</script>

<style scoped>
.app-shell-nav {
  position: sticky;
  top: 0;
  height: 100vh;
  width: var(--qq-nav-width);
  display: grid;
  grid-template-columns: var(--qq-domain-rail-width) 1fr;
  background: var(--qq-surface);
  border-right: 1px solid var(--qq-border);
  flex-shrink: 0;
  z-index: 100;
}

.domain-rail {
  display: flex;
  flex-direction: column;
  align-items: center;
  gap: var(--qq-gap-sm);
  padding: var(--qq-gap-sm) 0;
  background: var(--qq-rail-bg);
  border-right: 1px solid var(--qq-border);
}

.brand-mark,
.domain-btn,
.rail-tool {
  border: 0;
  color: var(--qq-text-muted);
  cursor: pointer;
  transition: color var(--qq-transition-fast), background var(--qq-transition-fast), transform var(--qq-transition-fast);
}

.brand-mark {
  width: 44px;
  height: 44px;
  display: grid;
  place-items: center;
  border-radius: var(--qq-radius-sm);
  background: #fff;
  border: 1px solid rgba(18, 183, 245, 0.22);
  box-shadow: var(--qq-shadow-sm);
}

.brand-mark__icon {
  width: 34px;
  height: 34px;
}

.brand-mark.active {
  box-shadow: 0 0 0 3px var(--qq-primary-soft);
}

.domain-rail__items {
  display: flex;
  flex-direction: column;
  gap: var(--qq-gap-xs);
  width: 100%;
  padding: var(--qq-gap-xs);
}

.domain-btn {
  height: 58px;
  width: 100%;
  display: flex;
  flex-direction: column;
  align-items: center;
  justify-content: center;
  gap: 3px;
  border-radius: var(--qq-radius-sm);
  background: transparent;
  font-family: var(--qq-font-base);
  font-size: 11px;
  line-height: 1;
}

.domain-btn:hover,
.rail-tool:hover {
  color: var(--qq-text);
  background: var(--qq-surface-hover);
}

.domain-btn:active {
  transform: scale(0.97);
}

.domain-btn.active {
  color: var(--qq-primary);
  background: var(--qq-primary-soft);
}

.domain-rail__tools {
  margin-top: auto;
  display: flex;
  flex-direction: column;
  gap: var(--qq-gap-xs);
}

.rail-tool {
  width: 38px;
  height: 38px;
  display: grid;
  place-items: center;
  border-radius: var(--qq-radius-sm);
  background: transparent;
  text-decoration: none;
}

.rail-tool:disabled {
  opacity: 0.45;
  cursor: not-allowed;
}

.section-panel {
  min-width: 0;
  display: flex;
  flex-direction: column;
  padding: var(--qq-gap-md) var(--qq-gap-sm);
}

.section-panel__head {
  padding: var(--qq-gap-sm) var(--qq-gap-sm) var(--qq-gap-md);
}

.section-panel__eyebrow {
  display: block;
  margin-bottom: 4px;
  color: var(--qq-primary);
  font-size: var(--qq-text-xs);
  font-weight: 700;
  letter-spacing: 0.05em;
  text-transform: uppercase;
}

.section-panel__head h2 {
  color: var(--qq-text);
  font-size: var(--qq-text-lg);
  line-height: 1.2;
  margin-bottom: 6px;
}

.section-panel__head p {
  color: var(--qq-text-muted);
  font-size: var(--qq-text-xs);
  line-height: 1.5;
}

.section-panel__nav {
  display: flex;
  flex-direction: column;
  gap: 3px;
  overflow-y: auto;
  min-height: 0;
}

.page-link {
  width: 100%;
  height: 38px;
  display: flex;
  align-items: center;
  gap: var(--qq-gap-sm);
  padding: 0 12px;
  border: 0;
  border-radius: var(--qq-radius-sm);
  background: transparent;
  color: var(--qq-text-muted);
  font-family: var(--qq-font-base);
  font-size: var(--qq-text-sm);
  font-weight: 500;
  cursor: pointer;
  text-align: left;
  transition: color var(--qq-transition-fast), background var(--qq-transition-fast), transform var(--qq-transition-fast);
}

.page-link:hover {
  color: var(--qq-text);
  background: var(--qq-surface-hover);
}

.page-link:active {
  transform: scale(0.97);
}

.page-link.active {
  color: var(--qq-text);
  background: var(--qq-surface-strong);
}

.page-link.active::before {
  content: "";
  width: 3px;
  height: 18px;
  border-radius: var(--qq-radius-full);
  background: var(--qq-primary);
}

.mobile-bar,
.drawer-overlay {
  display: none;
}

@media (max-width: 767px) {
  .app-shell-nav {
    display: none;
  }

  .mobile-bar {
    display: flex;
    align-items: center;
    justify-content: space-between;
    height: 52px;
    padding: 0 var(--qq-gap-md);
    padding-top: env(safe-area-inset-top, 0px);
    background: var(--qq-surface);
    border-bottom: 1px solid var(--qq-border);
    color: var(--qq-text);
    position: sticky;
    top: 0;
    z-index: 100;
  }

  .mobile-bar__menu-btn,
  .mobile-bar__theme-btn {
    width: 36px;
    height: 36px;
    display: grid;
    place-items: center;
    border: 0;
    border-radius: var(--qq-radius-sm);
    background: var(--qq-surface-strong);
    color: var(--qq-text);
    cursor: pointer;
  }

  .mobile-bar__actions {
    display: flex;
    align-items: center;
    gap: var(--qq-gap-xs);
  }

  .mobile-bar__theme-btn:disabled {
    opacity: 0.45;
    cursor: not-allowed;
  }

  .mobile-bar__brand {
    display: flex;
    align-items: center;
    gap: var(--qq-gap-xs);
    color: var(--qq-text);
    font-weight: 700;
    font-size: var(--qq-text-md);
  }

  .drawer-overlay {
    display: block;
    position: fixed;
    inset: 0;
    background: rgba(0, 0, 0, 0.42);
    z-index: 200;
  }

  .drawer {
    width: min(86vw, 320px);
    height: 100vh;
    display: flex;
    flex-direction: column;
    background: var(--qq-surface);
    box-shadow: var(--qq-shadow-lg);
  }

  .drawer__head {
    display: flex;
    align-items: center;
    gap: var(--qq-gap-sm);
    height: 54px;
    padding: 0 var(--qq-gap-md);
    padding-top: env(safe-area-inset-top, 0px);
    border-bottom: 1px solid var(--qq-border);
    color: var(--qq-text);
    font-weight: 700;
  }

  .drawer__close {
    margin-left: auto;
    width: 32px;
    height: 32px;
    display: grid;
    place-items: center;
    border: 0;
    border-radius: var(--qq-radius-sm);
    background: var(--qq-surface-strong);
    color: var(--qq-text);
    cursor: pointer;
  }

  .drawer__groups {
    flex: 1;
    overflow-y: auto;
    padding: var(--qq-gap-sm);
  }

  .drawer-group {
    border-bottom: 1px solid var(--qq-border);
    padding: var(--qq-gap-xs) 0;
  }

  .drawer-group__title,
  .drawer-link,
  .drawer-action {
    width: 100%;
    min-height: 38px;
    display: flex;
    align-items: center;
    gap: var(--qq-gap-sm);
    padding: 0 10px;
    border: 0;
    border-radius: var(--qq-radius-sm);
    background: transparent;
    color: var(--qq-text);
    font-family: var(--qq-font-base);
    font-size: var(--qq-text-sm);
    text-decoration: none;
    cursor: pointer;
  }

  .drawer-group__title {
    font-weight: 700;
  }

  .drawer-group__title :last-child {
    margin-left: auto;
  }

  .drawer-group__items {
    display: flex;
    flex-direction: column;
    gap: 2px;
    padding: var(--qq-gap-xs) 0 var(--qq-gap-sm) var(--qq-gap-md);
  }

  .drawer-link {
    color: var(--qq-text-muted);
  }

  .drawer-link.active {
    color: var(--qq-primary);
    background: var(--qq-primary-soft);
  }

  .drawer__footer {
    padding: var(--qq-gap-sm);
    padding-bottom: calc(var(--qq-gap-sm) + env(safe-area-inset-bottom, 0px));
    border-top: 1px solid var(--qq-border);
  }

  .drawer-action:disabled {
    opacity: 0.45;
    cursor: not-allowed;
  }
}
</style>
