<template>
  <div :class="classes">
    <div v-if="accent" class="ui-card__accent" :class="`ui-card__accent--${accent}`" />
    <slot />
  </div>
</template>

<script setup lang="ts">
import { computed } from 'vue'

const props = withDefaults(defineProps<{
  padding?: 'sm' | 'md' | 'lg' | 'none'
  shadow?: 'none' | 'sm' | 'md' | 'lg'
  clickable?: boolean
  accent?: 'primary' | 'cyan' | 'accent' | 'success' | 'warn' | 'danger'
}>(), {
  padding: 'md',
  shadow: 'sm',
})

const classes = computed(() => [
  'ui-card',
  `ui-card--p-${props.padding}`,
  `ui-card--shadow-${props.shadow}`,
  { 'ui-card--clickable': props.clickable },
])
</script>

<style scoped>
.ui-card {
  position: relative;
  background: var(--qq-surface);
  border: 1px solid var(--qq-border);
  border-radius: var(--qq-radius-card);
  overflow: hidden;
  transition: border-color var(--qq-transition-fast), box-shadow var(--qq-transition-fast);
}

.ui-card--shadow-sm { box-shadow: var(--qq-shadow-card); }
.ui-card--shadow-md { box-shadow: var(--qq-shadow-md); }
.ui-card--shadow-lg { box-shadow: var(--qq-shadow-lg); }

.ui-card--p-sm { padding: var(--qq-gap-sm); }
.ui-card--p-md { padding: var(--qq-gap-md); }
.ui-card--p-lg { padding: var(--qq-gap-lg); }

.ui-card--clickable {
  cursor: pointer;
}

/* 描边式 hover，替代浮起投影 */
.ui-card--clickable:hover {
  border-color: var(--qq-primary-border);
  box-shadow: var(--qq-shadow-card-hover);
}

/* 语义色条 — 左侧 2px */
.ui-card__accent {
  position: absolute;
  top: 0;
  left: 0;
  bottom: 0;
  width: 2px;
  z-index: 2;
}

.ui-card__accent--primary { background: var(--qq-primary); }
.ui-card__accent--cyan    { background: var(--qq-cyan); }
.ui-card__accent--accent  { background: var(--qq-accent); }
.ui-card__accent--success { background: var(--qq-success); }
.ui-card__accent--warn    { background: var(--qq-warn); }
.ui-card__accent--danger  { background: var(--qq-danger); }
</style>
