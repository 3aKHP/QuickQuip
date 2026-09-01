<template>
  <strong class="ui-stat-value">{{ display }}</strong>
</template>

<script setup lang="ts">
import { computed } from 'vue'
import { useCountUp } from '../../composables/useCountUp'

const props = withDefaults(defineProps<{
  value: number
  format?: (n: number) => string
}>(), {
  format: undefined,
})

const counted = useCountUp(() => props.value)
const display = computed(() => {
  const n = Math.round(counted.value)
  return props.format ? props.format(n) : n.toLocaleString()
})
</script>

<style scoped>
.ui-stat-value {
  font-size: var(--qq-text-lg);
  font-weight: 700;
  color: var(--qq-text);
  font-variant-numeric: tabular-nums;
  line-height: 1.2;
}
</style>
