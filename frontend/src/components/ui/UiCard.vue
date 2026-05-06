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
  accent?: 'primary' | 'success' | 'warn' | 'danger'
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
  border-radius: var(--qq-radius-card);
  overflow: hidden;
  transition: transform 0.2s ease, box-shadow 0.2s ease;
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

.ui-card--clickable:hover {
  transform: translateY(-2px);
  box-shadow: var(--qq-shadow-card-hover);
}

/* Semantic accent bar */
.ui-card__accent {
  position: absolute;
  top: 0;
  left: 0;
  right: 0;
  height: 3px;
}

.ui-card__accent--primary { background: var(--qq-primary); }
.ui-card__accent--success { background: var(--qq-success); }
.ui-card__accent--warn    { background: var(--qq-warn); }
.ui-card__accent--danger  { background: var(--qq-danger); }
</style>
