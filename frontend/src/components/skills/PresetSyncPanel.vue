<template>
  <div v-if="hasPending || loadError || localOnly.length" class="preset-panel">
    <div class="preset-head">
      <h3 class="section-title">预置同步</h3>
      <UiInfoTip text="对照仓库 skills.example/ 预置目录：missing 为尚未安装，diverged 为本地与预置不一致。同步 diverged 项前会将现有副本备份至 .preset-backups/。" />
      <span class="preset-spacer" />
      <UiButton size="sm" :disabled="!dirtyPresetCount || applying" :loading="applying" @click="onApply(false)">同步所选（{{ dirtyPresetCount }}）</UiButton>
      <UiButton size="sm" variant="secondary" :disabled="applying" @click="onApply(true)">一键同步全部待处理</UiButton>
    </div>
    <p v-if="loadError" class="error">{{ loadError }}</p>
    <div v-if="presets.length" class="preset-table-wrap">
      <table class="preset-table">
        <thead>
          <tr><th class="col-check" /><th>名称</th><th>状态</th><th>备注</th></tr>
        </thead>
        <tbody>
          <tr v-for="p in presets" :key="p.name">
            <td class="col-check">
              <input
                type="checkbox"
                :checked="selected.has(p.name)"
                :disabled="p.state === 'current' || p.state === 'conflict'"
                @change="toggle(p.name)"
              />
            </td>
            <td class="mono">{{ p.name }}</td>
            <td>
              <UiTag size="sm" :variant="stateVariant(p.state)">{{ STATE_SHORT[p.state] }}</UiTag>
              <UiInfoTip :text="p.label" />
            </td>
            <td class="preset-note">
              <span v-if="p.state === 'diverged'">同步将备份现有副本</span>
              <span v-else-if="p.state === 'conflict'">与预置同名但来源不同，请手动处理</span>
            </td>
          </tr>
        </tbody>
      </table>
    </div>
    <p v-if="localOnly.length" class="preset-local">
      仅本地（非预置）：{{ localOnly.join('、') }}
    </p>
  </div>
</template>

<script setup lang="ts">
import { computed, onMounted, ref } from 'vue'
import UiButton from '../ui/UiButton.vue'
import UiTag from '../ui/UiTag.vue'
import UiInfoTip from '../ui/UiInfoTip.vue'
import { listSkillPresets, applySkillPresets } from '../../api/skills'
import type { PresetRow, PresetSyncState } from '../../api/skills'
import { toast } from '../../toast'

const props = defineProps<{
  /** 执行同步前的闸门（返回 false 则中止），用于父级未保存编辑确认 */
  beforeApply?: () => boolean
}>()

const emit = defineEmits<{
  applied: []
}>()

const presets = ref<PresetRow[]>([])
const localOnly = ref<string[]>([])
const loadError = ref<string | null>(null)
const selected = ref<Set<string>>(new Set())
const applying = ref(false)
const dirtyPresetCount = computed(() => presets.value.filter(p => selected.value.has(p.name)).length)
// 面板渲染条件：有待处理项（missing/diverged/conflict）、加载失败，或存在仅本地 Skill
// （「仅本地」属常驻信息，不随待处理项清空而隐藏）
const hasPending = computed(() => presets.value.some(p => p.state !== 'current'))

// 状态列短词化：表格内短词受列宽限制，后端长文案 label 由旁边的 UiInfoTip 承载
const STATE_SHORT: Record<PresetSyncState, string> = {
  current: '已同步',
  missing: '未安装',
  diverged: '已偏离',
  conflict: '冲突',
}

onMounted(reload)

async function reload() {
  loadError.value = null
  try {
    const data = await listSkillPresets()
    presets.value = data.presets || []
    localOnly.value = data.local_only || []
  } catch (e: unknown) {
    loadError.value = (e as Error).message
  }
}

function stateVariant(state: PresetSyncState) {
  if (state === 'current') return 'success' as const
  if (state === 'diverged') return 'warn' as const
  if (state === 'conflict') return 'danger' as const
  return 'info' as const
}

function toggle(name: string) {
  const next = new Set(selected.value)
  if (next.has(name)) next.delete(name)
  else next.add(name)
  selected.value = next
}

async function onApply(all: boolean) {
  const names = all ? presets.value.filter(p => p.state === 'missing' || p.state === 'diverged').map(p => p.name) : [...selected.value]
  if (!names.length) return
  if (props.beforeApply && !props.beforeApply()) return
  if (!confirm(all
    ? `将同步全部 ${names.length} 个待处理预置 Skill，已偏离项的旧副本会备份至 .preset-backups/。是否继续？`
    : `将同步所选 ${names.length} 个预置 Skill，已偏离项的旧副本会备份至 .preset-backups/。是否继续？`)) return
  applying.value = true
  loadError.value = null
  try {
    const res = await applySkillPresets(names)
    if (res.failures.length) {
      toast(`同步完成，${res.outcomes.length} 项成功，${res.failures.length} 项失败：${res.failures.join('、')}`, 'error', 5000)
    } else {
      toast(`已同步 ${res.outcomes.length} 个预置 Skill`)
    }
    selected.value = new Set()
    await reload()
    emit('applied')
  } catch (e: unknown) {
    loadError.value = (e as Error).message
    toast('预置同步失败', 'error')
  } finally {
    applying.value = false
  }
}

defineExpose({ reload })
</script>

<style scoped>
.error { color: var(--qq-danger); font-size: var(--qq-text-sm); }
.mono { font-family: var(--qq-font-mono); }

.preset-panel {
  background: var(--qq-surface);
  border: 1px solid var(--qq-border);
  border-radius: var(--qq-radius-card);
  box-shadow: var(--qq-shadow-card);
  padding: var(--qq-gap-sm) var(--qq-gap-md);
  display: flex;
  flex-direction: column;
  gap: var(--qq-gap-xs);
}

.preset-head {
  display: flex;
  align-items: center;
  gap: var(--qq-gap-xs);
}

.preset-spacer { flex: 1; }

.preset-table-wrap { overflow-x: auto; }

.preset-table {
  width: 100%;
  border-collapse: collapse;
  font-size: var(--qq-text-sm);
  color: var(--qq-text);
}

.preset-table th {
  text-align: left;
  color: var(--qq-text-muted);
  font-size: var(--qq-text-xs);
  font-weight: 600;
  padding: 4px var(--qq-gap-xs);
  border-bottom: 1px solid var(--qq-border);
}

.preset-table td {
  padding: 4px var(--qq-gap-xs);
  border-bottom: 1px solid var(--qq-border-soft);
}

.preset-table tr:last-child td { border-bottom: none; }

.preset-table .col-check { width: 28px; }

.preset-table input[type="checkbox"] { accent-color: var(--qq-primary); }

.preset-note {
  color: var(--qq-text-muted);
  font-size: var(--qq-text-xs);
}

.preset-local {
  margin: 0;
  color: var(--qq-text-muted);
  font-size: var(--qq-text-xs);
}
</style>
