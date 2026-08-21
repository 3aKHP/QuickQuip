import { computed, ref } from 'vue'
import type {
  GroupOverrideDraft,
  GroupOverrideField,
  GroupOverridePatch,
  GroupOverrideValue,
} from '../api/groupSettings'

/** 可编辑字段表：草稿/原始快照/diff 的键集合唯一来源 */
const FIELDS: readonly GroupOverrideField[] = [
  'enabled', 'memory_enabled', 'auto_memory_enabled', 'provider_id', 'model', 'persona_id',
  'trigger_prefix', 'allow_prefix', 'allow_at', 'history_limit',
]

function emptyDraft(): GroupOverrideDraft {
  // fromEntries 按 FIELDS 全量构造，键集合与 GroupOverrideDraft 一一对应
  return Object.fromEntries(FIELDS.map(field => [field, null])) as GroupOverrideDraft
}

/**
 * 群级 override 草稿的 tri-state 编辑机制：
 * null = 跟随默认；draft vs original 的逐字段 diff 即保存时提交的 patch（缺省字段不发送）。
 */
export function useGroupOverrideDraft() {
  const original = ref<GroupOverrideDraft>(emptyDraft())
  const draft = ref<GroupOverrideDraft>(emptyDraft())

  const modelInput = computed({
    get: () => draft.value.model ?? '',
    set: (value) => { draft.value.model = value === '' ? null : value },
  })

  const prefixInput = computed({
    get: () => draft.value.trigger_prefix ?? '',
    set: (value) => { draft.value.trigger_prefix = value === '' ? null : value },
  })

  const historyInput = computed({
    get: () => draft.value.history_limit ?? '',
    set: (value) => {
      if (value === '' || value == null || Number.isNaN(Number(value))) {
        draft.value.history_limit = null
      } else {
        draft.value.history_limit = Number(value)
      }
    },
  })

  const hasChanges = computed(() => {
    for (const field of FIELDS) {
      if (draft.value[field] !== original.value[field]) return true
    }
    return false
  })

  function clearModel() { draft.value.model = null }
  function clearPrefix() { draft.value.trigger_prefix = null }
  function clearHistory() { draft.value.history_limit = null }

  /** 用远端数据重建草稿与原始快照；undefined 字段视为未覆盖，保持 null */
  function applyData(data: Partial<Record<GroupOverrideField, GroupOverrideValue>>) {
    const snapshot = emptyDraft()
    for (const field of FIELDS) {
      const value = data[field]
      if (value !== undefined) Object.assign(snapshot, { [field]: value })
    }
    original.value = snapshot
    draft.value = { ...snapshot }
  }

  /** 草稿与原始快照一起重置为空（新增覆盖对象 / 清空 override 后） */
  function resetDraft() {
    original.value = emptyDraft()
    draft.value = emptyDraft()
  }

  /** 相对原始快照的逐字段 diff；无变化时返回空对象 */
  function buildPatch(): GroupOverridePatch {
    const diff: GroupOverridePatch = {}
    for (const field of FIELDS) {
      if (draft.value[field] !== original.value[field]) {
        diff[field] = draft.value[field]
      }
    }
    return diff
  }

  return {
    draft,
    hasChanges,
    modelInput,
    prefixInput,
    historyInput,
    clearModel,
    clearPrefix,
    clearHistory,
    applyData,
    resetDraft,
    buildPatch,
  }
}
