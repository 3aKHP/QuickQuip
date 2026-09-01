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
          <img
            class="brand-mark__icon"
            src="/brand.svg"
            alt=""
            width="34"
            height="34"
            aria-hidden="true"
          >
        </button>
      </router-link>

      <nav class="domain-rail__items" aria-label="工作域">
        <button
          v-for="section in sections"
          :key="section.key"
          class="domain-btn"
          :class="{ active: activeSectionKey === section.key }"
          :style="activeSectionKey === section.key ? domainActiveStyle(section.key) : undefined"
          :title="section.label"
          @click="goToSection(section.key)"
        >
          <UiIcon :name="section.icon" :size="20" />
          <span>{{ section.label }}</span>
        </button>
      </nav>

      <div class="domain-rail__tools">
        <button class="rail-tool" :title="themeLabel" @click="$emit('toggleTheme')">
          <Transition name="icon-swap" mode="out-in">
            <UiIcon :key="themeIcon" :name="themeIcon" :size="18" />
          </Transition>
        </button>
        <button
          class="rail-tool"
          :class="{ 'rail-tool--on': lowMotion }"
          :title="lowMotion ? '已开启低动态模式（光场静态渲染）' : '动态效果正常，点击开启低动态模式'"
          @click="toggleLowMotion"
        >
          <Transition name="icon-swap" mode="out-in">
            <UiIcon :key="lowMotion ? 'off' : 'on'" :name="lowMotion ? 'ZapOff' : 'Zap'" :size="18" />
          </Transition>
        </button>
        <button class="rail-tool" title="退出" :disabled="logoutDisabled" @click="$emit('logout')">
          <UiIcon name="LogOut" :size="18" />
        </button>
      </div>
    </div>

    <div class="section-panel">
      <div class="section-panel__head">
        <span class="section-panel__eyebrow">
          <img class="section-panel__brand-logo" src="/brand.svg" alt="" width="16" height="16" aria-hidden="true">
          <span class="section-panel__brand-word">QuickQuip</span>
        </span>
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
        <Transition name="icon-swap" mode="out-in">
          <UiIcon :key="themeIcon" :name="themeIcon" :size="18" />
        </Transition>
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
          <button
            class="drawer-action"
            :class="{ 'drawer-action--on': lowMotion }"
            @click="toggleLowMotion"
          >
            <UiIcon :name="lowMotion ? 'ZapOff' : 'Zap'" :size="14" />
            <span>{{ lowMotion ? '已开启低动态' : '低动态模式' }}</span>
          </button>
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
import { useMotionPrefs } from '../../composables/useMotionPrefs'
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
const { lowMotion, toggleLowMotion } = useMotionPrefs()
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

// 域导航 active 态染域色（六域锚点；总览域回退主色）
function domainActiveStyle(sectionKey: string) {
  const color = sectionKey === 'overview' ? 'var(--qq-primary)' : `var(--qq-domain-${sectionKey})`
  return { color, boxShadow: `inset 2px 0 0 ${color}` }
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
  background:
    linear-gradient(90deg, var(--qq-shell-glass-highlight), transparent 44%),
    var(--qq-shell-glass-bg);
  border-right: 1px solid var(--qq-shell-glass-border);
  box-shadow:
    10px 0 34px var(--qq-shell-shadow),
    inset -1px 0 0 var(--qq-shell-glass-highlight);
  backdrop-filter: blur(18px) saturate(1.22);
  -webkit-backdrop-filter: blur(18px) saturate(1.22);
  flex-shrink: 0;
  z-index: 100;
}

.domain-rail {
  display: flex;
  flex-direction: column;
  align-items: center;
  gap: var(--qq-gap-sm);
  padding: var(--qq-gap-sm) 0;
  background:
    linear-gradient(180deg, var(--qq-shell-glass-highlight), transparent 38%),
    var(--qq-shell-rail-bg);
  border-right: 1px solid var(--qq-shell-glass-border);
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
  background: transparent;
  padding: 0;
}

.brand-mark.active {
  box-shadow: 0 0 0 3px var(--qq-primary-soft);
}

.brand-mark__icon {
  width: 34px;
  height: 34px;
  display: block;
  border-radius: var(--qq-radius-sm);
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
  background: var(--qq-shell-control-hover);
}

.domain-btn:active {
  transform: scale(0.97);
}

.domain-btn.active {
  color: var(--qq-primary);
  background: var(--qq-shell-control-active);
  box-shadow: inset 2px 0 0 var(--qq-primary);
  backdrop-filter: blur(10px) saturate(1.14);
  -webkit-backdrop-filter: blur(10px) saturate(1.14);
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

.rail-tool--on {
  color: var(--qq-accent);
  background: var(--qq-accent-soft);
}

.rail-tool:focus-visible {
  outline: none;
  box-shadow: 0 0 0 2px var(--qq-primary-glow);
}

.brand-mark:focus-visible {
  outline: none;
  box-shadow: 0 0 0 2px var(--qq-primary-glow);
}

.domain-btn:focus-visible {
  outline: none;
  box-shadow: inset 0 0 0 2px var(--qq-primary-glow);
}

.section-panel {
  position: relative;
  min-width: 0;
  display: flex;
  flex-direction: column;
  padding: var(--qq-gap-md) var(--qq-gap-sm);
  overflow: hidden;
}

.section-panel::before {
  content: "";
  position: absolute;
  inset: 0;
  pointer-events: none;
  background:
    linear-gradient(145deg, var(--qq-shell-glass-sheen), transparent 34%),
    radial-gradient(ellipse at 80% 18%, var(--qq-shell-glass-sheen), transparent 38%);
  opacity: 0.55;
}

.section-panel__head,
.section-panel__nav {
  position: relative;
  z-index: 1;
}

.section-panel__head {
  padding: var(--qq-gap-sm) var(--qq-gap-sm) var(--qq-gap-md);
}

.section-panel__eyebrow {
  display: flex;
  align-items: center;
  gap: 6px;
  margin-bottom: 4px;
  color: var(--qq-primary);
  font-family: var(--qq-font-mono);
  font-size: var(--qq-text-xs);
  font-weight: 600;
}

.section-panel__brand-logo {
  display: block;
  border-radius: var(--qq-radius-sm);
}

.section-panel__brand-word {
  letter-spacing: 0.04em;
}

.section-panel__head h2 {
  color: var(--qq-text);
  font-family: var(--qq-font-display);
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
  position: relative;
  box-sizing: border-box;
  width: 100%;
  height: 38px;
  display: flex;
  align-items: center;
  gap: var(--qq-gap-sm);
  padding: 0 12px;
  border: 1px solid transparent;
  border-radius: var(--qq-radius-sm);
  background: transparent;
  color: var(--qq-text-muted);
  font-family: var(--qq-font-display);
  font-size: var(--qq-text-sm);
  font-weight: 500;
  cursor: pointer;
  text-align: left;
  transition: color var(--qq-transition-fast), background var(--qq-transition-fast);
}

/* Hover left bar indicator */
.page-link::after {
  content: "";
  position: absolute;
  left: 4px;
  top: 50%;
  transform: translateY(-50%) scaleY(0);
  width: 2px;
  height: 14px;
  border-radius: var(--qq-radius-full);
  background: var(--qq-primary);
  opacity: 0;
  transition: transform 0.2s var(--qq-ease-out), opacity 0.2s var(--qq-ease-out);
}

.page-link:hover {
  color: var(--qq-text);
  background: var(--qq-shell-control-hover);
}

.page-link:hover::after {
  transform: translateY(-50%) scaleY(1);
  opacity: 0.5;
}

.page-link.active {
  color: var(--qq-text);
  background: var(--qq-shell-control-active);
  border: 1px solid var(--qq-shell-glass-border);
  box-shadow: inset 0 1px 0 var(--qq-shell-glass-highlight);
  backdrop-filter: blur(10px) saturate(1.14);
  -webkit-backdrop-filter: blur(10px) saturate(1.14);
}

.page-link.active::before {
  transform: scaleY(1);
}

.page-link::before {
  content: "";
  width: 3px;
  height: 18px;
  border-radius: var(--qq-radius-full);
  background: var(--qq-primary);
  transform: scaleY(0);
  transform-origin: 50% 50%;
  transition: transform var(--qq-transition-base);
}

.page-link svg {
  transition: transform var(--qq-transition-base), color var(--qq-transition-fast);
}

.page-link.active svg {
  transform: scale(1.08);
  color: var(--qq-primary);
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
    background:
      linear-gradient(180deg, var(--qq-shell-glass-highlight), transparent 58%),
      var(--qq-shell-status-bg);
    border-bottom: 1px solid var(--qq-shell-glass-border);
    box-shadow: 0 10px 28px var(--qq-shell-shadow);
    backdrop-filter: blur(16px) saturate(1.2);
    -webkit-backdrop-filter: blur(16px) saturate(1.2);
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
    background: var(--qq-shell-control-active);
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
    background: var(--qq-overlay);
    z-index: 200;
  }

  .drawer {
    width: min(86vw, 320px);
    height: 100vh;
    display: flex;
    flex-direction: column;
    background:
      linear-gradient(145deg, var(--qq-shell-glass-highlight), transparent 42%),
      var(--qq-shell-drawer-bg);
    box-shadow: var(--qq-shadow-lg);
    border-right: 1px solid var(--qq-shell-glass-border);
    backdrop-filter: blur(18px) saturate(1.22);
    -webkit-backdrop-filter: blur(18px) saturate(1.22);
  }

  .drawer__head {
    display: flex;
    align-items: center;
    gap: var(--qq-gap-sm);
    height: 54px;
    padding: 0 var(--qq-gap-md);
    padding-top: env(safe-area-inset-top, 0px);
    border-bottom: 1px solid var(--qq-shell-glass-border);
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
    background: var(--qq-shell-control-active);
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
    display: flex;
    gap: var(--qq-gap-xs);
    padding: var(--qq-gap-sm);
    padding-bottom: calc(var(--qq-gap-sm) + env(safe-area-inset-bottom, 0px));
    border-top: 1px solid var(--qq-border);
  }

  .drawer-action--on {
    color: var(--qq-accent);
    background: var(--qq-accent-soft);
  }

  .drawer-action:disabled {
    opacity: 0.45;
    cursor: not-allowed;
  }
}
</style>
