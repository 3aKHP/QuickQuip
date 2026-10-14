<template>
  <div class="string-list">
    <div v-if="modelValue.length" class="string-list__items">
      <span v-for="(item, index) in modelValue" :key="index" class="string-list__chip">
        <span class="string-list__text">{{ item }}</span>
        <button type="button" class="string-list__remove" :aria-label="`移除 ${item}`" @click="remove(index)">
          <UiIcon name="X" :size="12" />
        </button>
      </span>
    </div>
    <form class="string-list__adder" @submit.prevent="add">
      <input v-model="draft" :placeholder="placeholder || '输入后回车添加'" autocomplete="off" spellcheck="false" />
      <UiButton size="sm" icon="Plus" :disabled="!canAdd" type="submit">添加</UiButton>
    </form>
  </div>
</template>

<script setup lang="ts">
import { computed, ref } from 'vue'
import UiButton from '../ui/UiButton.vue'
import UiIcon from '../ui/UiIcon.vue'

const props = withDefaults(defineProps<{ modelValue: string[]; placeholder?: string; unique?: boolean }>(), { placeholder: undefined, unique: true })
const emit = defineEmits<{ 'update:modelValue': [value: string[]] }>()

const draft = ref('')
const canAdd = computed(() => {
  const value = draft.value.trim()
  return value !== '' && (!props.unique || !props.modelValue.includes(value))
})

function add() {
  if (!canAdd.value) return
  emit('update:modelValue', [...props.modelValue, draft.value.trim()])
  draft.value = ''
}

function remove(index: number) {
  emit('update:modelValue', props.modelValue.filter((_, i) => i !== index))
}
</script>

<style scoped>
.string-list {
  display: grid;
  gap: 8px;
}

.string-list__items {
  display: flex;
  flex-wrap: wrap;
  gap: 6px;
}

.string-list__chip {
  display: inline-flex;
  align-items: center;
  gap: 4px;
  padding: 3px 6px 3px 10px;
  border: 1px solid var(--qq-border);
  border-radius: var(--qq-radius-full);
  background: var(--qq-token-bg);
  font-family: var(--qq-font-mono);
  font-size: var(--qq-text-xs);
  color: var(--qq-text);
}

.string-list__text {
  overflow-wrap: anywhere;
}

.string-list__remove {
  display: inline-flex;
  align-items: center;
  justify-content: center;
  width: 16px;
  height: 16px;
  border: 0;
  border-radius: 50%;
  background: transparent;
  color: var(--qq-text-muted);
  cursor: pointer;
  padding: 0;
}

.string-list__remove:hover {
  background: var(--qq-danger-soft);
  color: var(--qq-danger);
}

.string-list__adder {
  display: flex;
  gap: 8px;
}

.string-list__adder input {
  flex: 1;
  min-width: 0;
  padding: 7px 10px;
  border: 1px solid var(--qq-border);
  border-radius: var(--qq-radius-md);
  background: var(--qq-bg);
  color: var(--qq-text);
  font: inherit;
  font-size: var(--qq-text-sm);
}
</style>
