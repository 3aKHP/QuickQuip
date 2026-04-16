<template>
  <div class="ui-card" :class="[paddingClass, shadowClass, { clickable }]">
    <slot />
  </div>
</template>

<script>
export default {
  name: 'UiCard',
  props: {
    padding: { type: String, default: 'md' }, // sm | md | lg
    shadow: { type: String, default: 'sm' }, // sm | md | lg | none
    clickable: { type: Boolean, default: false },
  },
  computed: {
    paddingClass() {
      return `ui-card--padding-${this.padding}`
    },
    shadowClass() {
      return this.shadow === 'none' ? '' : `ui-card--shadow-${this.shadow}`
    },
  },
}
</script>

<style scoped>
.ui-card {
  background: var(--qq-surface);
  border: 1px solid var(--qq-border);
  border-radius: var(--qq-radius-md);
  transition: border-color var(--qq-transition-fast), box-shadow var(--qq-transition-fast);
}

.ui-card.clickable {
  cursor: pointer;
}
.ui-card.clickable:hover {
  border-color: var(--qq-border-strong);
}

.ui-card--padding-sm { padding: var(--qq-gap-sm); }
.ui-card--padding-md { padding: var(--qq-gap-md); }
.ui-card--padding-lg { padding: var(--qq-gap-lg); }

.ui-card--shadow-sm { box-shadow: var(--qq-shadow-sm); }
.ui-card--shadow-md { box-shadow: var(--qq-shadow-md); }
.ui-card--shadow-lg { box-shadow: var(--qq-shadow-lg); }
</style>
