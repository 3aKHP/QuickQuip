<template>
  <div class="awakening-view">
    <UiPageHeader title="唤醒管理" subtitle="查看群级唤醒参数，管理各唤醒规则和无聊唤醒 opt-in">
      <template #actions>
        <UiButton icon="RefreshCw" :loading="loading" @click="load">刷新</UiButton>
        <UiButton variant="primary" icon="Plus" @click="startAdd">添加群</UiButton>
      </template>
    </UiPageHeader>

    <p v-if="error" class="error">{{ error }}</p>
    <p v-if="data?.load_error" class="warn">
      <UiIcon name="AlertTriangle" :size="14" />
      awakening.toml 加载失败：{{ data.load_error }}
    </p>

    <div v-if="data" class="defaults-strip">
      <div class="default-item"><span>唤醒延长</span><strong>{{ data.defaults.extend_duration }}s</strong></div>
      <div class="default-item"><span>兜底概率</span><strong>{{ data.defaults.fallback_probability }}</strong></div>
      <div class="default-item"><span>无聊沉寂</span><strong>{{ data.defaults.boredom_silence_seconds }}s</strong></div>
      <div class="default-item"><span>无聊概率</span><strong>{{ data.defaults.boredom_probability }}</strong></div>
      <div class="default-item"><span>无聊扫描</span><strong>{{ scanIntervalText }}</strong></div>
      <div class="default-item"><span>相关阈值</span><strong>{{ data.defaults.relevance_threshold }}</strong></div>
      <div class="default-item"><span>答疑阈值</span><strong>{{ data.defaults.qa_threshold }}</strong></div>
    </div>

    <UiLoading v-if="loading && !data" />

    <div v-else-if="data" class="shell">
      <aside class="groups-panel">
        <div class="panel-head">
          <span>群组</span>
          <span class="mono">{{ groups.length }}</span>
        </div>
        <UiEmpty v-if="!groups.length" icon="BellRing" title="暂无唤醒群组记录" />
        <button
          v-for="g in groups"
          :key="g.group_id"
          class="group-item"
          :class="{ active: g.group_id === selectedGroupId }"
          @click="selectGroup(g.group_id)"
        >
          <span class="mono group-id">{{ g.group_id }}</span>
          <span class="tags">
            <UiTag v-if="g.has_override" size="sm" variant="warn">override</UiTag>
            <UiTag v-if="g.boredom_opt_in" size="sm" variant="success">无聊</UiTag>
          </span>
        </button>
      </aside>

      <main class="detail-panel">
        <UiEmpty v-if="!selectedGroup" icon="BellRing" title="选择或添加一个群查看唤醒状态" />
        <template v-else>
          <div class="detail-head">
            <div>
              <span class="kicker">当前群</span>
              <h3 class="mono">{{ selectedGroup.group_id }}</h3>
            </div>
            <div class="head-tags">
              <UiTag :variant="selectedGroup.has_override ? 'warn' : 'info'">
                {{ selectedGroup.has_override ? '群级覆盖' : '使用默认' }}
              </UiTag>
              <UiTag :variant="selectedGroup.boredom_opt_in ? 'success' : 'danger'">
                {{ selectedGroup.boredom_opt_in ? '无聊 opt-in' : '无聊未启用' }}
              </UiTag>
            </div>
          </div>

          <section class="detail-section">
            <h4>规则开关</h4>
            <div class="rule-grid">
              <div v-for="rule in selectedGroup.rules" :key="rule.name" class="rule-row">
                <div>
                  <span class="rule-label">{{ rule.label }}</span>
                  <span class="mono rule-name">{{ rule.name }}</span>
                </div>
                <UiToggle :model-value="rule.enabled" @update:model-value="toggleRule(rule.name, $event)" />
              </div>
              <div class="rule-row boredom-row">
                <div>
                  <span class="rule-label">无聊唤醒群启用</span>
                  <span class="mono rule-name">data/awakening_boredom_groups.json</span>
                </div>
                <UiToggle :model-value="selectedGroup.boredom_opt_in" @update:model-value="toggleBoredom" />
              </div>
            </div>
          </section>

          <section class="detail-section">
            <div class="section-head">
              <h4>群级参数</h4>
              <div class="section-actions">
                <UiButton size="sm" variant="ghost" icon="RotateCcw" :disabled="savingSettings || !hasDraftChanges" @click="resetDraft">重置</UiButton>
                <UiButton size="sm" variant="primary" icon="Save" :loading="savingSettings" :disabled="!hasDraftChanges" @click="saveSettings">保存</UiButton>
              </div>
            </div>
            <p class="section-note">留空表示跟随默认值；兴趣话题由人格和规则开关控制，此处只读。</p>
            <div class="form-grid">
              <label v-for="field in EDITABLE_FIELDS" :key="field.key" class="field">
                <span>{{ field.label }}</span>
                <div class="field-row">
                  <input
                    v-model="draft[field.key]"
                    :type="field.inputType"
                    :step="field.step"
                    :min="field.min"
                    :max="field.max"
                    :placeholder="defaultValueText(field.key, field.unit)"
                  />
                  <UiButton v-if="draft[field.key] !== ''" size="sm" variant="ghost" icon="X" @click="clearField(field.key)">跟随</UiButton>
                </div>
                <small v-if="field.hint" class="field-hint">{{ field.hint }}</small>
              </label>
            </div>
            <p v-if="settingsError" class="error">{{ settingsError }}</p>
          </section>

          <section class="detail-section">
            <h4>Resolved 设置</h4>
            <div class="settings-grid">
              <div class="setting"><span>唤醒延长</span><strong>{{ selectedGroup.settings.extend_duration }}s</strong></div>
              <div class="setting"><span>兴趣话题</span><strong>{{ topicsText }}</strong></div>
              <div class="setting"><span>兜底概率</span><strong>{{ selectedGroup.settings.fallback_probability }}</strong></div>
              <div class="setting"><span>无聊沉寂</span><strong>{{ selectedGroup.settings.boredom_silence_seconds }}s</strong></div>
              <div class="setting"><span>无聊概率</span><strong>{{ selectedGroup.settings.boredom_probability }}</strong></div>
              <div class="setting"><span>检查间隔</span><strong>{{ selectedGroup.settings.boredom_check_interval }}s</strong></div>
              <div class="setting"><span>免打扰</span><strong>{{ dndText }}</strong></div>
              <div class="setting"><span>相关阈值</span><strong>{{ selectedGroup.settings.relevance_threshold }}</strong></div>
              <div class="setting"><span>答疑阈值</span><strong>{{ selectedGroup.settings.qa_threshold }}</strong></div>
            </div>
          </section>
        </template>
      </main>
    </div>
  </div>
</template>

<script setup lang="ts">
import { computed, ref, watch } from 'vue'
import UiButton from '../components/ui/UiButton.vue'
import UiEmpty from '../components/ui/UiEmpty.vue'
import UiIcon from '../components/ui/UiIcon.vue'
import UiLoading from '../components/ui/UiLoading.vue'
import UiPageHeader from '../components/ui/UiPageHeader.vue'
import UiTag from '../components/ui/UiTag.vue'
import UiToggle from '../components/ui/UiToggle.vue'
import { fetchAwakening, fetchAwakeningGroup, setAwakeningBoredom, setAwakeningRule, updateAwakeningSettings } from '../api/awakening'
import { toast } from '../toast'

const EDITABLE_FIELD_KEYS = [
  'extend_duration',
  'fallback_probability',
  'boredom_silence_seconds',
  'boredom_probability',
  'boredom_check_interval',
  'boredom_dnd_start',
  'boredom_dnd_end',
  'relevance_threshold',
  'qa_threshold',
] as const

type FieldKey = typeof EDITABLE_FIELD_KEYS[number]

type EditableField = {
  key: FieldKey
  label: string
  unit?: string
  inputType: 'number' | 'time'
  min?: number
  max?: number
  step?: number
  hint?: string
}

const EDITABLE_FIELDS: EditableField[] = [
  { key: 'extend_duration', label: '唤醒延长', unit: 's', inputType: 'number', min: 0, max: 604800, step: 1 },
  { key: 'fallback_probability', label: '兜底概率', unit: '', inputType: 'number', min: 0, max: 1, step: 0.01 },
  { key: 'boredom_silence_seconds', label: '无聊沉寂', unit: 's', inputType: 'number', min: 0, max: 604800, step: 1 },
  { key: 'boredom_probability', label: '无聊概率', unit: '', inputType: 'number', min: 0, max: 1, step: 0.01 },
  { key: 'boredom_check_interval', label: '检查间隔', unit: 's', inputType: 'number', min: 0, max: 604800, step: 1 },
  { key: 'boredom_dnd_start', label: '免打扰开始', unit: '', inputType: 'time' },
  { key: 'boredom_dnd_end', label: '免打扰结束', unit: '', inputType: 'time' },
  { key: 'relevance_threshold', label: '相关阈值', unit: '', inputType: 'number', min: 0, max: 1, step: 0.01, hint: '<= 0 或 >= 1 均关闭相关性 LLM 判定' },
  { key: 'qa_threshold', label: '答疑阈值', unit: '', inputType: 'number', min: 0, max: 1, step: 0.01, hint: '<= 0 或 >= 1 均关闭答疑 LLM 判定' },
]

const data = ref<any>(null)
const loading = ref(false)
const error = ref<string | null>(null)
const selectedGroupId = ref('')
const savingSettings = ref(false)
const settingsError = ref<string | null>(null)
const draft = ref<Record<FieldKey, string>>(emptyDraft())
const originalDraft = ref<Record<FieldKey, string>>(emptyDraft())

const groups = computed(() => data.value?.groups || [])
// 扫描周期为全局字段：未设置时回退检查间隔（后端 effective_boredom_scan_interval 同源规则）
const scanIntervalText = computed(() => {
  const defaults = data.value?.defaults || {}
  const scan = defaults.boredom_scan_interval ?? defaults.boredom_check_interval ?? 300
  const suffix = defaults.boredom_scan_interval == null ? '（回退）' : ''
  return `${scan}s${suffix}`
})
const selectedGroup = computed(() => groups.value.find((g: any) => g.group_id === selectedGroupId.value) || null)
const topicsText = computed(() => {
  const topics = selectedGroup.value?.settings?.interest_topics || []
  return topics.length ? topics.join('、') : '未配置'
})
const dndText = computed(() => {
  const s = selectedGroup.value?.settings || {}
  return s.boredom_dnd_start && s.boredom_dnd_end ? `${s.boredom_dnd_start}-${s.boredom_dnd_end}` : '未配置'
})
const hasDraftChanges = computed(() => {
  return EDITABLE_FIELDS.some(field => draft.value[field.key] !== originalDraft.value[field.key])
})

function emptyDraft(): Record<FieldKey, string> {
  return Object.fromEntries(EDITABLE_FIELDS.map(field => [field.key, ''])) as Record<FieldKey, string>
}

function stringValue(value: unknown): string {
  if (value === null || value === undefined) return ''
  return String(value)
}

function snapshotFromGroup(group: any): Record<FieldKey, string> {
  const override = group?.override || {}
  return Object.fromEntries(
    EDITABLE_FIELDS.map(field => [field.key, stringValue(override[field.key])]),
  ) as Record<FieldKey, string>
}

function applyDraft(group: any) {
  const snapshot = snapshotFromGroup(group)
  draft.value = { ...snapshot }
  originalDraft.value = { ...snapshot }
  settingsError.value = null
}

function defaultValueText(key: FieldKey, unit = ''): string {
  const value = data.value?.defaults?.[key]
  if (value === undefined || value === null || value === '') return '跟随默认'
  return `默认 ${value}${unit}`
}

function clearField(key: FieldKey) {
  draft.value[key] = ''
}

function resetDraft() {
  draft.value = { ...originalDraft.value }
}

function parseDraftValue(key: FieldKey, raw: string): number | string | null {
  if (raw === '') return null
  if (key === 'boredom_dnd_start' || key === 'boredom_dnd_end') return raw
  const value = Number(raw)
  if (!Number.isFinite(value)) throw new Error(`${fieldLabel(key)} 不是有效数字`)
  const field = EDITABLE_FIELDS.find(item => item.key === key)
  if (typeof field?.min === 'number' && value < field.min) throw new Error(`${fieldLabel(key)} 不能小于 ${field.min}`)
  if (typeof field?.max === 'number' && value > field.max) throw new Error(`${fieldLabel(key)} 不能大于 ${field.max}`)
  if (['extend_duration', 'boredom_silence_seconds', 'boredom_check_interval'].includes(key)) {
    if (!Number.isInteger(value)) throw new Error(`${fieldLabel(key)} 必须是整数`)
    return value
  }
  return value
}

function fieldLabel(key: FieldKey): string {
  return EDITABLE_FIELDS.find(field => field.key === key)?.label || key
}

function buildPayload(): Record<string, number | string | null> {
  const payload: Record<string, number | string | null> = {}
  for (const field of EDITABLE_FIELDS) {
    if (draft.value[field.key] !== originalDraft.value[field.key]) {
      payload[field.key] = parseDraftValue(field.key, draft.value[field.key])
    }
  }
  return payload
}

async function load() {
  loading.value = true
  error.value = null
  try {
    data.value = await fetchAwakening()
    if (selectedGroupId.value && !groups.value.find((g: any) => g.group_id === selectedGroupId.value)) {
      selectedGroupId.value = ''
    }
    if (!selectedGroupId.value && groups.value.length) selectedGroupId.value = groups.value[0].group_id
    if (selectedGroup.value) applyDraft(selectedGroup.value)
  } catch (e: unknown) {
    error.value = (e as Error).message
  } finally {
    loading.value = false
  }
}

async function selectGroup(groupId: string) {
  if (groupId !== selectedGroupId.value && hasDraftChanges.value && !confirm('当前唤醒参数未保存，切换会丢失。是否继续？')) return
  selectedGroupId.value = groupId
  if (selectedGroup.value) applyDraft(selectedGroup.value)
}

async function startAdd() {
  const raw = prompt('输入 5-12 位群号')
  if (!raw) return
  const gid = raw.trim()
  if (!/^\d{5,12}$/.test(gid)) {
    toast('群号格式不合法', 'error')
    return
  }
  try {
    const group = await fetchAwakeningGroup(gid)
    const list = groups.value
    const idx = list.findIndex((g: any) => g.group_id === gid)
    if (idx >= 0) list[idx] = group
    else list.push(group)
    selectedGroupId.value = gid
    applyDraft(group)
  } catch (e: unknown) {
    toast((e as Error).message, 'error')
  }
}

async function refreshSelected() {
  if (!selectedGroupId.value) return
  const group = await fetchAwakeningGroup(selectedGroupId.value)
  const idx = groups.value.findIndex((g: any) => g.group_id === selectedGroupId.value)
  if (idx >= 0) groups.value[idx] = group
  applyDraft(group)
}

async function toggleRule(ruleName: string, enabled: boolean) {
  if (!selectedGroupId.value) return
  try {
    await setAwakeningRule(selectedGroupId.value, ruleName, enabled)
    await refreshSelected()
    toast(`${ruleName} 已${enabled ? '启用' : '禁用'}`)
  } catch (e: unknown) {
    toast((e as Error).message, 'error')
  }
}

async function toggleBoredom(enabled: boolean) {
  if (!selectedGroupId.value) return
  try {
    await setAwakeningBoredom(selectedGroupId.value, enabled)
    await refreshSelected()
    toast(`无聊唤醒群启用已${enabled ? '开启' : '关闭'}`)
  } catch (e: unknown) {
    toast((e as Error).message, 'error')
  }
}

async function saveSettings() {
  if (!selectedGroupId.value) return
  settingsError.value = null
  let payload: Record<string, number | string | null>
  try {
    payload = buildPayload()
  } catch (e: unknown) {
    settingsError.value = (e as Error).message
    return
  }
  if (!Object.keys(payload).length) return
  savingSettings.value = true
  try {
    const result = await updateAwakeningSettings(selectedGroupId.value, payload)
    const group = result.group
    const idx = groups.value.findIndex((g: any) => g.group_id === selectedGroupId.value)
    if (idx >= 0) groups.value[idx] = group
    else groups.value.push(group)
    applyDraft(group)
    toast(result.queued ? '唤醒参数已保存，重载规则已入队' : '唤醒参数已保存')
  } catch (e: unknown) {
    settingsError.value = (e as Error).message
    toast('保存失败', 'error')
  } finally {
    savingSettings.value = false
  }
}

watch(selectedGroup, (group) => {
  if (group && !hasDraftChanges.value) applyDraft(group)
})

load()
</script>

<style scoped>
.awakening-view { display: flex; flex-direction: column; flex: 1; min-height: 0; }
.error { color: var(--qq-danger); }
.warn { display: inline-flex; align-items: center; gap: 6px; color: var(--qq-warn); font-size: var(--qq-text-sm); }
.mono { font-family: var(--qq-font-mono); }

.defaults-strip { display: grid; grid-template-columns: repeat(6, minmax(0, 1fr)); gap: var(--qq-gap-sm); margin-bottom: var(--qq-gap-md); }
.default-item, .setting { min-width: 0; padding: var(--qq-gap-sm); border-radius: var(--qq-radius-sm); background: var(--qq-surface-strong); }
.default-item span, .setting span { display: block; color: var(--qq-text-muted); font-size: var(--qq-text-xs); }
.default-item strong, .setting strong { display: block; overflow: hidden; color: var(--qq-text); font-size: var(--qq-text-sm); text-overflow: ellipsis; white-space: nowrap; }

.shell { display: grid; grid-template-columns: 280px minmax(0, 1fr); gap: var(--qq-gap-md); flex: 1; min-height: 0; }
.groups-panel, .detail-panel { min-width: 0; min-height: 0; overflow: hidden; border: 1px solid var(--qq-border); border-radius: var(--qq-radius-card); background: var(--qq-surface); box-shadow: var(--qq-shadow-card); }
.groups-panel { display: flex; flex-direction: column; }
.panel-head { display: flex; align-items: center; justify-content: space-between; height: 48px; padding: 0 var(--qq-gap-md); border-bottom: 1px solid var(--qq-border); color: var(--qq-text); font-size: var(--qq-text-sm); font-weight: 700; }
.group-item { display: flex; align-items: center; justify-content: space-between; gap: var(--qq-gap-sm); width: 100%; padding: var(--qq-gap-sm) var(--qq-gap-md); border: 0; border-bottom: 1px solid var(--qq-border); background: transparent; color: var(--qq-text); cursor: pointer; font-family: var(--qq-font-base); text-align: left; }
.group-item:hover, .group-item.active { background: var(--qq-surface-hover); }
.group-item.active { box-shadow: inset 3px 0 0 var(--qq-primary); }
.group-id { min-width: 0; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
.tags, .head-tags { display: flex; gap: var(--qq-gap-xs); flex-wrap: wrap; justify-content: flex-end; }

.detail-panel { display: flex; flex-direction: column; gap: var(--qq-gap-md); overflow-y: auto; padding: var(--qq-gap-md); }
.detail-head { display: flex; align-items: center; justify-content: space-between; gap: var(--qq-gap-md); padding-bottom: var(--qq-gap-md); border-bottom: 1px solid var(--qq-border); }
.kicker { display: block; margin-bottom: 4px; color: var(--qq-primary); font-size: var(--qq-text-xs); font-weight: 700; }
.detail-head h3 { margin: 0; color: var(--qq-text); font-size: var(--qq-text-lg); }
.detail-section { display: flex; flex-direction: column; gap: var(--qq-gap-sm); }
.detail-section h4 { margin: 0; color: var(--qq-text); font-size: var(--qq-text-base); }
.section-head { display: flex; align-items: center; justify-content: space-between; gap: var(--qq-gap-sm); }
.section-actions { display: flex; align-items: center; gap: var(--qq-gap-xs); flex: 0 0 auto; }
.section-note { margin: 0; color: var(--qq-text-muted); font-size: var(--qq-text-xs); }
.rule-grid { display: grid; grid-template-columns: repeat(auto-fit, minmax(260px, 1fr)); gap: var(--qq-gap-sm); }
.rule-row { display: flex; align-items: center; justify-content: space-between; gap: var(--qq-gap-md); min-height: 62px; padding: var(--qq-gap-sm); border: 1px solid var(--qq-border); border-radius: var(--qq-radius-sm); background: var(--qq-surface-strong); }
.rule-row > div { min-width: 0; }
.rule-row :deep(.ui-toggle) { flex: 0 0 auto; }
.boredom-row { border-color: var(--qq-primary-border); }
.rule-label { display: block; color: var(--qq-text); font-size: var(--qq-text-sm); font-weight: 600; }
.rule-name { display: block; margin-top: 3px; overflow: hidden; color: var(--qq-text-muted); font-size: var(--qq-text-xs); text-overflow: ellipsis; white-space: nowrap; }
.form-grid { display: grid; grid-template-columns: repeat(auto-fit, minmax(220px, 1fr)); gap: var(--qq-gap-sm); }
.field { display: flex; min-width: 0; flex-direction: column; gap: var(--qq-gap-xs); color: var(--qq-text-muted); font-size: var(--qq-text-xs); font-weight: 600; }
.field-row { display: flex; align-items: center; gap: var(--qq-gap-xs); min-width: 0; }
.field-row input { flex: 1 1 auto; min-width: 0; height: 36px; border: 1px solid var(--qq-border-strong); border-radius: var(--qq-radius-btn); background: var(--qq-surface); color: var(--qq-text); font-family: var(--qq-font-base); font-size: var(--qq-text-md); padding: 7px 11px; outline: none; }
.field-row input:focus { border-color: var(--qq-primary); background: var(--qq-surface-elevated); box-shadow: 0 0 0 3px var(--qq-primary-soft); }
.field-row :deep(.ui-btn) { flex: 0 0 auto; }
.field-hint { color: var(--qq-text-muted); font-size: var(--qq-text-xs); font-weight: 400; }
.settings-grid { display: grid; grid-template-columns: repeat(auto-fit, minmax(190px, 1fr)); gap: var(--qq-gap-sm); }

@media (max-width: 1000px) { .defaults-strip { grid-template-columns: repeat(3, minmax(0, 1fr)); } .shell { grid-template-columns: 1fr; } .groups-panel { max-height: 240px; } }
@media (max-width: 640px) { .defaults-strip { grid-template-columns: 1fr 1fr; } .detail-head, .section-head { align-items: flex-start; flex-direction: column; } .form-grid { grid-template-columns: 1fr; } }
</style>
