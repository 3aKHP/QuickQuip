<template>
  <component :is="iconComp" v-if="iconComp" :size="size" :stroke-width="strokeWidth" />
</template>

<script>
import { computed } from 'vue'
import * as icons from 'lucide-vue-next'

export default {
  name: 'UiIcon',
  props: {
    name: { type: String, required: true },
    size: { type: [String, Number], default: 16 },
    strokeWidth: { type: [String, Number], default: 2 },
  },
  setup(props) {
    const iconComp = computed(() => icons[props.name] || null)
    return { iconComp }
  },
}
</script>
