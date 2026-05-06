<template>
  <div class="ui-card" :class="[variantClass, paddingClass, shadowClass, { clickable }]">
    <slot />
  </div>
</template>

<script setup lang="ts">
import { computed } from 'vue'

const props = defineProps({
  variant: { type: String, default: 'default' },
  padding: { type: String, default: 'md' },
  shadow: { type: String, default: 'sm' },
  clickable: { type: Boolean, default: false },
})

const variantClass = computed(() => `ui-card--${props.variant}`)
const paddingClass = computed(() => `ui-card--padding-${props.padding}`)
const shadowClass = computed(() => props.shadow === 'none' ? '' : `ui-card--shadow-${props.shadow}`)
</script>

<style scoped>
.ui-card {
  border-radius: var(--qq-radius-md);
  transition: border-color var(--qq-transition-fast),
              box-shadow var(--qq-transition-fast),
              transform var(--qq-transition-base);
}

/* Variants */
.ui-card--default {
  background: var(--qq-surface);
  border: 1px solid var(--qq-border);
}

.ui-card--bordered {
  background: var(--qq-surface);
  border: 1px solid var(--qq-border-strong);
}

.ui-card--ghost {
  background: transparent;
  border: 1px solid transparent;
}

.ui-card.clickable {
  cursor: pointer;
}

.ui-card.clickable:hover {
  border-color: var(--qq-border-strong);
}

/* Padding */
.ui-card--padding-sm { padding: var(--qq-gap-sm); }
.ui-card--padding-md { padding: var(--qq-gap-md); }
.ui-card--padding-lg { padding: var(--qq-gap-lg); }

/* Shadows */
.ui-card--shadow-sm { box-shadow: var(--qq-shadow-sm); }
.ui-card--shadow-md { box-shadow: var(--qq-shadow-md); }
.ui-card--shadow-lg { box-shadow: var(--qq-shadow-lg); }
</style>
