<template>
  <div>
    <UiPageHeader title="规则开关" />
    <p v-if="error" class="error">{{ error }}</p>
    <UiLoading v-else-if="!loaded" />
    <div v-else>
      <UiCard padding="md" shadow="sm" class="toolbar-card">
        <div class="toolbar-inner">
          <label>群组
            <select v-model="selectedGroup">
              <option value="">— 选择群组 —</option>
              <option v-for="gid in allGroups" :key="gid" :value="gid">{{ gid }}</option>
            </select>
          </label>
          <label>手动添加
            <input v-model="newGroupId" placeholder="输入群号" @keyup.enter="addGroup" />
          </label>
          <UiButton icon="Plus" @click="addGroup">添加</UiButton>
        </div>
      </UiCard>

      <div v-if="selectedGroup" class="rule-grid">
        <UiCard
          v-for="rule in allRules"
          :key="rule"
          padding="sm"
          shadow="sm"
          class="rule-row"
        >
          <div class="rule-left">
            <span class="rule-dot" />
            <span class="rule-name">{{ rule }}</span>
          </div>
          <UiToggle
            :model-value="isEnabled(rule)"
            @update:model-value="toggle(rule)"
          />
        </UiCard>
      </div>
      <UiEmpty v-else icon="MousePointerClick" title="请先选择或添加一个群组" />
    </div>
  </div>
</template>

<script setup lang="ts">
import { onMounted, ref } from 'vue'
import UiPageHeader from '../components/ui/UiPageHeader.vue'
import UiCard from '../components/ui/UiCard.vue'
import UiButton from '../components/ui/UiButton.vue'
import UiToggle from '../components/ui/UiToggle.vue'
import UiLoading from '../components/ui/UiLoading.vue'
import UiEmpty from '../components/ui/UiEmpty.vue'
import { fetchRules, updateRule } from '../api/rules'
import { fetchKnownGroups } from '../api/groups'
import { toast } from '../toast'

const loaded = ref(false)
const error = ref<string | null>(null)
const disabled = ref<Record<string, string[]>>({})
const allRules = ref<string[]>([])
const allGroups = ref<string[]>([])
const selectedGroup = ref('')
const newGroupId = ref('')

onMounted(async () => {
  try {
    const [rulesData, knownData] = await Promise.all([
      fetchRules(),
      fetchKnownGroups(),
    ])
    disabled.value = rulesData.disabled
    allRules.value = rulesData.all_rules
    const fromRules = Object.keys(rulesData.disabled)
    const fromKnown = knownData.groups || []
    allGroups.value = [...new Set([...fromKnown, ...fromRules])].sort()
    loaded.value = true
  } catch (e: unknown) {
    error.value = (e as Error).message
  }
})

function isEnabled(rule: string): boolean {
  return !(disabled.value[selectedGroup.value] || []).includes(rule)
}

function addGroup() {
  const gid = newGroupId.value.trim()
  if (!gid || !/^\d+$/.test(gid)) return
  if (!allGroups.value.includes(gid)) allGroups.value.push(gid)
  if (!disabled.value[gid]) disabled.value[gid] = []
  selectedGroup.value = gid
  newGroupId.value = ''
}

async function toggle(rule: string) {
  const nowEnabled = isEnabled(rule)
  try {
    await updateRule(selectedGroup.value, rule, !nowEnabled)
    if (!disabled.value[selectedGroup.value]) disabled.value[selectedGroup.value] = []
    if (nowEnabled) {
      disabled.value[selectedGroup.value].push(rule)
    } else {
      disabled.value[selectedGroup.value] = disabled.value[selectedGroup.value].filter(r => r !== rule)
    }
    toast(`${rule} 已${!nowEnabled ? '启用' : '禁用'}`)
  } catch (e: unknown) {
    toast(`操作失败：${(e as Error).message}`, 'error')
  }
}
</script>

<style scoped>
.error {
  color: var(--qq-danger);
}

.toolbar-card {
  margin-bottom: var(--qq-gap-md);
}

.toolbar-inner {
  display: flex;
  align-items: center;
  gap: var(--qq-gap-md);
  flex-wrap: wrap;
}

.toolbar-inner label {
  display: flex;
  align-items: center;
  gap: var(--qq-gap-xs);
  color: var(--qq-text-muted);
  font-size: 13px;
}

.toolbar-inner select,
.toolbar-inner input {
  background: var(--qq-surface-strong);
  border: 1px solid var(--qq-border);
  border-radius: var(--qq-radius-sm);
  color: var(--qq-text);
  padding: 5px 10px;
  font-size: 14px;
  outline: none;
}

.toolbar-inner select:focus,
.toolbar-inner input:focus {
  border-color: var(--qq-accent);
  box-shadow: 0 0 0 3px var(--qq-accent-soft);
}

.rule-grid {
  display: flex;
  flex-direction: column;
  gap: var(--qq-gap-sm);
}

.rule-row {
  display: flex;
  align-items: center;
  justify-content: space-between;
}

.rule-left {
  display: flex;
  align-items: center;
  gap: var(--qq-gap-sm);
}

.rule-dot {
  width: 6px;
  height: 6px;
  border-radius: 50%;
  background: var(--qq-accent);
}

.rule-name {
  font-size: 13px;
  font-family: var(--qq-font-mono);
  color: var(--qq-text);
}
</style>
