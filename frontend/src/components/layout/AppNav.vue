<template>
  <nav class="app-nav">
    <span class="brand">
      <UiIcon name="Bot" :size="18" />
      <span>QuickQuip</span>
    </span>

    <div class="nav-items">
      <UiNavItem
        v-for="item in items"
        :key="item.key"
        :label="item.label"
        :icon="item.icon"
        :active="activeKey === item.key"
        @click="$emit('update:activeKey', item.key)"
      />
    </div>

    <span class="nav-spacer" />

    <UiButton size="sm" variant="ghost" icon="LogOut" :disabled="logoutDisabled" @click="$emit('logout')">
      退出
    </UiButton>
  </nav>
</template>

<script>
import UiNavItem from '../ui/UiNavItem.vue'
import UiButton from '../ui/UiButton.vue'
import UiIcon from '../ui/UiIcon.vue'

export default {
  name: 'AppNav',
  components: { UiNavItem, UiButton, UiIcon },
  props: {
    items: { type: Array, required: true },
    activeKey: { type: String, required: true },
    logoutDisabled: { type: Boolean, default: false },
  },
  emits: ['update:activeKey', 'logout'],
}
</script>

<style scoped>
.app-nav {
  background: var(--qq-surface);
  border-bottom: 1px solid var(--qq-border);
  padding: 0 var(--qq-gap-md);
  display: flex;
  align-items: center;
  gap: var(--qq-gap-sm);
  height: 52px;
}

.brand {
  display: inline-flex;
  align-items: center;
  gap: var(--qq-gap-xs);
  font-weight: 600;
  color: var(--qq-accent);
  margin-right: var(--qq-gap-sm);
  font-size: 15px;
}

.nav-items {
  display: flex;
  align-items: center;
  gap: 2px;
}

.nav-spacer {
  flex: 1;
}

@media (max-width: 720px) {
  .app-nav {
    padding: 0 var(--qq-gap-sm);
  }
  .nav-items .ui-nav-item .label {
    display: none;
  }
}
</style>
