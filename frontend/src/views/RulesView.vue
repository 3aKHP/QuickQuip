<template>
  <div>
    <UiPageHeader title="规则开关" subtitle="按群开关文本彩蛋与语境规则；规则内容、优先级与语境模式在「配置」页编辑 chat_rules.toml">
      <template #actions>
        <UiButton icon="RefreshCw" :loading="loading" @click="load">刷新</UiButton>
      </template>
    </UiPageHeader>

    <div v-if="error" class="soft-note soft-note--danger rules-error" role="alert">{{ error }}</div>
    <UiLoading v-if="!loaded && loading" />

    <div v-else-if="loaded">
      <div class="toolbar">
        <label>
          群组
          <select v-model="selectedGroup">
            <option value="">— 选择群组 —</option>
            <option v-for="gid in allGroups" :key="gid" :value="gid">{{ gid }}</option>
          </select>
        </label>
        <label>
          手动添加
          <UiInfoTip text="群组下拉只列出 bot 已知的群；这里可以手动输入群号，为尚未有过消息的群预先配置开关。群号需为 5–12 位纯数字。" />
          <input v-model="newGroupId" placeholder="输入 5–12 位群号" @keyup.enter="addGroup" />
        </label>
        <UiButton icon="Plus" @click="addGroup">添加</UiButton>
      </div>

      <template v-if="selectedGroup">
        <div class="rules-head">
          <div class="rules-head__title">
            <span class="section-title">规则列表</span>
            <UiInfoTip text="规则名是内部标识，来源有三类：内置模块规则、chat_rules.toml 里 [[rules]] / [[context_rules]] 自定义规则的 name、连锁游戏自动派生的「游戏名」_start /「游戏名」_progress。开关按群记录「禁用名单」，默认全部启用，状态持久化在 data/rule_switch.json。" />
            <UiTag size="sm" variant="info">
              已启用 {{ enabledCount }} · 已禁用 {{ disabledCount }}
            </UiTag>
          </div>
          <div class="rules-head__filters">
            <input v-model="ruleSearch" type="search" placeholder="搜索规则名..." class="rule-search" />
            <label class="only-disabled">
              <input v-model="onlyDisabled" type="checkbox" />
              <span>仅看已禁用</span>
            </label>
          </div>
        </div>

        <div v-if="filteredRules.length" class="rule-grid">
          <UiCard
            v-for="rule in filteredRules"
            :key="rule"
            padding="sm"
            shadow="sm"
            class="rule-row"
            :class="{ 'rule-row--disabled': !isEnabled(rule) }"
          >
            <div class="rule-left">
              <span class="rule-dot" :class="{ 'rule-dot--off': !isEnabled(rule) }" />
              <span class="rule-name" :title="rule">{{ rule }}</span>
            </div>
            <UiToggle
              :model-value="isEnabled(rule)"
              :disabled="pendingRules.has(`${selectedGroup}:${rule}`)"
              @update:model-value="toggle(rule)"
            />
          </UiCard>
        </div>
        <UiEmpty v-else compact icon="Search" title="没有符合条件的规则" />
      </template>
      <UiEmpty v-else icon="BookOpen" title="请先选择或添加一个群组" />
    </div>
  </div>
</template>

<script setup lang="ts">
import { computed, onMounted, reactive, ref } from 'vue'
import UiPageHeader from '../components/ui/UiPageHeader.vue'
import UiCard from '../components/ui/UiCard.vue'
import UiButton from '../components/ui/UiButton.vue'
import UiTag from '../components/ui/UiTag.vue'
import UiToggle from '../components/ui/UiToggle.vue'
import UiLoading from '../components/ui/UiLoading.vue'
import UiEmpty from '../components/ui/UiEmpty.vue'
import UiInfoTip from '../components/ui/UiInfoTip.vue'
import { fetchRules, updateRule } from '../api/rules'
import { fetchKnownGroups } from '../api/groups'
import { toast } from '../toast'

const loaded = ref(false)
const loading = ref(false)
const error = ref<string | null>(null)
const disabled = ref<Record<string, string[]>>({})
const allRules = ref<string[]>([])
const allGroups = ref<string[]>([])
const selectedGroup = ref('')
const newGroupId = ref('')
const ruleSearch = ref('')
const onlyDisabled = ref(false)
const pendingRules = reactive(new Set<string>())

const disabledSetForSelected = computed(() => new Set(disabled.value[selectedGroup.value] || []))
const disabledCount = computed(() =>
  allRules.value.filter(rule => disabledSetForSelected.value.has(rule)).length,
)
const enabledCount = computed(() => allRules.value.length - disabledCount.value)

const filteredRules = computed(() => {
  const q = ruleSearch.value.trim().toLowerCase()
  return allRules.value.filter((rule) => {
    if (onlyDisabled.value && !disabledSetForSelected.value.has(rule)) return false
    if (q && !rule.toLowerCase().includes(q)) return false
    return true
  })
})

async function load() {
  loading.value = true
  error.value = null
  try {
    const [r, k] = await Promise.all([fetchRules(), fetchKnownGroups()])
    disabled.value = r.disabled || {}
    allRules.value = r.all_rules || []
    const merged = new Set([...Object.keys(disabled.value), ...(k.groups || [])])
    if (selectedGroup.value) merged.add(selectedGroup.value)
    allGroups.value = [...merged].sort()
    loaded.value = true
  } catch (e: unknown) {
    error.value = (e as Error).message
  } finally {
    loading.value = false
  }
}

onMounted(() => { load() })

function isEnabled(rule: string): boolean {
  return !disabledSetForSelected.value.has(rule)
}

function addGroup() {
  const gid = newGroupId.value.trim()
  if (!/^\d{5,12}$/.test(gid)) {
    toast('群号必须为 5–12 位纯数字', 'error')
    return
  }
  if (!allGroups.value.includes(gid)) {
    allGroups.value.push(gid)
    allGroups.value.sort()
  }
  if (!disabled.value[gid]) disabled.value[gid] = []
  selectedGroup.value = gid
  newGroupId.value = ''
}

async function toggle(rule: string) {
  const gid = selectedGroup.value
  if (!gid) return
  const key = `${gid}:${rule}`
  if (pendingRules.has(key)) return
  const now = !(disabled.value[gid] || []).includes(rule)
  pendingRules.add(key)
  try {
    await updateRule(gid, rule, !now)
    if (!disabled.value[gid]) disabled.value[gid] = []
    if (now) {
      if (!disabled.value[gid].includes(rule)) disabled.value[gid].push(rule)
    } else {
      disabled.value[gid] = disabled.value[gid].filter(r => r !== rule)
    }
    toast(`${rule} 已${!now ? '启用' : '禁用'}`)
  } catch (e: unknown) {
    toast(`操作失败：${(e as Error).message}`, 'error')
  } finally {
    pendingRules.delete(key)
  }
}
</script>

<style scoped>
.rules-error { margin-bottom: var(--qq-gap-md); }
.toolbar {
  display: flex;
  align-items: center;
  gap: var(--qq-gap-md);
  flex-wrap: wrap;
  margin-bottom: var(--qq-gap-md);
  padding: var(--qq-gap-sm) var(--qq-gap-md);
  background: var(--qq-surface);
  border: 1px solid var(--qq-border);
  border-radius: var(--qq-radius-card);
  box-shadow: var(--qq-shadow-card);
}
.toolbar label { display: flex; align-items: center; gap: var(--qq-gap-xs); color: var(--qq-text-muted); font-size: var(--qq-text-sm); }

.rules-head {
  display: flex;
  align-items: center;
  justify-content: space-between;
  flex-wrap: wrap;
  gap: var(--qq-gap-sm);
  margin-bottom: var(--qq-gap-md);
}
.rules-head__title {
  display: inline-flex;
  align-items: center;
  gap: var(--qq-gap-xs);
  flex-wrap: wrap;
}
.rules-head__filters {
  display: inline-flex;
  align-items: center;
  gap: var(--qq-gap-md);
  flex-wrap: wrap;
}
.rule-search { width: 220px; }
.only-disabled {
  display: inline-flex;
  align-items: center;
  gap: 6px;
  color: var(--qq-text-muted);
  font-size: var(--qq-text-sm);
  cursor: pointer;
}

.rule-grid {
  display: grid;
  grid-template-columns: repeat(auto-fill, minmax(260px, 1fr));
  gap: var(--qq-gap-sm);
}
.rule-row {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: var(--qq-gap-sm);
  min-width: 0;
}
.rule-row--disabled .rule-name {
  color: var(--qq-text-muted);
}
.rule-left {
  display: flex;
  align-items: center;
  gap: var(--qq-gap-sm);
  min-width: 0;
  flex: 1;
}
.rule-dot {
  width: 6px;
  height: 6px;
  border-radius: 50%;
  background: var(--qq-primary);
  flex-shrink: 0;
}
.rule-dot--off {
  background: var(--qq-border-strong);
}
.rule-name {
  font-size: var(--qq-text-sm);
  font-family: var(--qq-font-mono);
  color: var(--qq-text);
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}
</style>
