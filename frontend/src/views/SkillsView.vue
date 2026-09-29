<template>
  <div class="skills-view page-view-fill">
    <UiPageHeader title="Skill 管理" subtitle="管理 LLM Skill 目录：在线编辑文本资源、安装第三方 Skill、同步仓库预置">
      <template #subtitle>
        <UiInfoTip text="Skill 每次群聊轮次现扫生效，保存文件后无需重启。scripts/ 下的脚本以 bot 进程权限在本机运行，编辑与安装前请确认来源可信。" />
      </template>
      <template #actions>
        <UiButton icon="RefreshCw" :disabled="listing" @click="loadAll">刷新</UiButton>
        <UiButton icon="Plus" @click="startCreate">新建</UiButton>
        <UiButton icon="Upload" @click="installOpen = true">安装</UiButton>
        <UiButton variant="danger" icon="Trash2" :disabled="!selectedName" @click="onDeleteSkill">删除</UiButton>
      </template>
    </UiPageHeader>
    <p v-if="listError" class="error">{{ listError }}</p>

    <div class="preset-panel">
      <div class="preset-head">
        <span class="preset-title">预置同步</span>
        <UiInfoTip text="对照仓库 skills.example/ 预置目录：missing 为尚未安装，diverged 为本地与预置不一致。同步 diverged 项前会将现有副本备份至 .preset-backups/。" />
        <span class="preset-spacer" />
        <UiButton size="sm" :disabled="!dirtyPresetCount || applyingPresets" :loading="applyingPresets" @click="onApplyPresets(false)">同步所选（{{ dirtyPresetCount }}）</UiButton>
        <UiButton size="sm" variant="secondary" :disabled="applyingPresets" @click="onApplyPresets(true)">一键同步全部待处理</UiButton>
      </div>
      <p v-if="presetError" class="error">{{ presetError }}</p>
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
                  :checked="selectedPresets.has(p.name)"
                  :disabled="p.state === 'current' || p.state === 'conflict'"
                  @change="togglePreset(p.name)"
                />
              </td>
              <td class="mono">{{ p.name }}</td>
              <td>
                <UiTag size="sm" :variant="presetVariant(p.state)">{{ p.label }}</UiTag>
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

    <div class="split">
      <nav class="list-panel">
        <UiLoading v-if="listing && !skills.length" />
        <UiEmpty v-else-if="!skills.length" icon="Sparkles" title="暂无 Skill" description="点击顶部「新建」或「安装」添加" />
        <div v-else class="list-scroll">
          <button
            v-for="s in skills"
            :key="s.name"
            class="list-item qq-selectable"
            :class="{ active: s.name === selectedName }"
            @click="selectSkill(s.name)"
          >
            <div class="list-item-head">
              <span class="skill-name mono">{{ s.name }}</span>
              <UiTag v-if="!s.ok" size="sm" variant="danger">解析失败</UiTag>
              <UiTag v-else-if="s.preset_state === 'current'" size="sm" variant="info">预置</UiTag>
              <UiTag v-else-if="s.preset_state === 'diverged'" size="sm" variant="warn">预置·已偏离</UiTag>
              <UiTag v-if="s.has_scripts" size="sm" variant="danger">含脚本</UiTag>
            </div>
            <div v-if="!s.ok && s.diagnostics.length" class="list-item-desc list-item-desc--error">{{ s.diagnostics[0].message }}</div>
            <div v-else-if="s.description" class="list-item-desc">{{ s.description }}</div>
          </button>
        </div>
      </nav>

      <div class="detail-col">
        <div v-if="!selectedName" class="hint-panel">
          <UiEmpty icon="Sparkles" title="从左侧选择一个 Skill 查看与编辑" />
        </div>
        <template v-else>
          <UiLoading v-if="loadingDetail" />
          <template v-else-if="detail">
            <div v-if="detail.diagnostics.length" class="diag-banner">
              <UiIcon name="AlertTriangle" :size="15" />
              <div class="diag-list">
                <div v-for="(d, i) in detail.diagnostics" :key="i" class="diag-item">
                  <UiTag size="sm" variant="danger">{{ d.kind }}</UiTag>
                  <span>{{ d.message }}</span>
                </div>
              </div>
            </div>
            <div class="meta-card">
              <div class="meta-row"><span class="meta-key">description</span><span class="meta-val">{{ detail.metadata.description || '（未填写）' }}</span></div>
              <div v-if="detail.metadata.license" class="meta-row">
                <span class="meta-key">license</span><span class="meta-val mono">{{ detail.metadata.license }}</span>
              </div>
              <div v-if="detail.metadata.compatibility" class="meta-row">
                <span class="meta-key">compatibility</span><span class="meta-val">{{ detail.metadata.compatibility }}</span>
              </div>
              <div class="meta-row" v-for="(v, k) in detail.metadata.metadata" :key="k">
                <span class="meta-key mono">{{ k }}</span><span class="meta-val">{{ v }}</span>
              </div>
              <div v-if="detail.metadata.unknown_fields.length" class="meta-row">
                <span class="meta-key">未识别字段</span>
                <span class="meta-val meta-val--muted">{{ detail.metadata.unknown_fields.join('、') }}（解析时忽略，不产生运行时行为）</span>
              </div>
            </div>

            <div class="file-table-wrap">
              <table class="file-table">
                <thead>
                  <tr><th>路径</th><th>类型</th><th>大小</th><th class="col-actions" /></tr>
                </thead>
                <tbody>
                  <tr v-for="r in detail.resources" :key="r.path" class="file-row" :class="{ active: r.path === filePath }">
                    <td>
                      <button class="file-open mono" @click="openFile(r.path)">
                        {{ r.path }}
                        <UiTag v-if="r.path.startsWith('scripts/')" size="sm" variant="danger">脚本</UiTag>
                      </button>
                    </td>
                    <td class="file-kind">{{ r.kind }}</td>
                    <td class="file-size">{{ formatSize(r.size_bytes) }}</td>
                    <td class="col-actions">
                      <UiButton
                        v-if="r.path !== 'SKILL.md'"
                        size="sm"
                        variant="ghost"
                        icon="Trash2"
                        @click="onDeleteFile(r.path)"
                      />
                    </td>
                  </tr>
                </tbody>
              </table>
            </div>

            <template v-if="filePath">
              <div v-if="filePath.startsWith('scripts/')" class="script-banner">
                <UiIcon name="AlertTriangle" :size="15" />
                该文件是可执行脚本，将以 bot 进程权限在本机运行
              </div>
              <div class="editor-bar">
                <span class="mono editor-path">{{ filePath }}</span>
                <span v-if="fileDirty" class="dirty-pill">未保存</span>
                <UiButton size="sm" variant="primary" icon="Save" :loading="savingFile" :disabled="!fileDirty" @click="onSaveFile">保存</UiButton>
              </div>
              <p v-if="fileError" class="error">{{ fileError }}</p>
              <UiLoading v-if="loadingFile" />
              <textarea v-else v-model="fileContent" class="file-editor" spellcheck="false" autocomplete="off" />
            </template>
          </template>
          <p v-else-if="detailError" class="error">{{ detailError }}</p>
        </template>
      </div>
    </div>

    <SkillInstallDialog v-if="installOpen" @close="installOpen = false" @installed="onInstalled" />
  </div>
</template>

<script setup lang="ts">
import { computed, onMounted, ref } from 'vue'
import UiPageHeader from '../components/ui/UiPageHeader.vue'
import UiButton from '../components/ui/UiButton.vue'
import UiTag from '../components/ui/UiTag.vue'
import UiIcon from '../components/ui/UiIcon.vue'
import UiLoading from '../components/ui/UiLoading.vue'
import UiEmpty from '../components/ui/UiEmpty.vue'
import UiInfoTip from '../components/ui/UiInfoTip.vue'
import SkillInstallDialog from '../components/skills/SkillInstallDialog.vue'
import {
  listSkills, createSkill, fetchSkill, deleteSkill,
  fetchSkillFile, saveSkillFile, deleteSkillFile,
  listSkillPresets, applySkillPresets,
} from '../api/skills'
import type { SkillSummary, SkillDetail, PresetRow, PresetSyncState } from '../api/skills'
import { toast } from '../toast'

const SKILL_NAME_PATTERN = /^[a-z0-9][a-z0-9-]*$/

const skills = ref<SkillSummary[]>([])
const listing = ref(false)
const listError = ref<string | null>(null)
const selectedName = ref('')
const detail = ref<SkillDetail | null>(null)
const loadingDetail = ref(false)
const detailError = ref<string | null>(null)

const filePath = ref('')
const fileContent = ref('')
const fileOriginal = ref('')
const loadingFile = ref(false)
const savingFile = ref(false)
const fileError = ref<string | null>(null)
const fileDirty = computed(() => fileContent.value !== fileOriginal.value)

const presets = ref<PresetRow[]>([])
const localOnly = ref<string[]>([])
const presetError = ref<string | null>(null)
const selectedPresets = ref<Set<string>>(new Set())
const applyingPresets = ref(false)
const dirtyPresetCount = computed(() => presets.value.filter(p => selectedPresets.value.has(p.name)).length)

const installOpen = ref(false)

onMounted(loadAll)

async function loadAll() {
  await Promise.all([loadList(), loadPresets()])
}

async function loadList() {
  listing.value = true
  listError.value = null
  try {
    const data = await listSkills()
    skills.value = data.skills || []
  } catch (e: unknown) {
    listError.value = (e as Error).message
  } finally {
    listing.value = false
  }
}

async function loadPresets() {
  presetError.value = null
  try {
    const data = await listSkillPresets()
    presets.value = data.presets || []
    localOnly.value = data.local_only || []
  } catch (e: unknown) {
    presetError.value = (e as Error).message
  }
}

function presetVariant(state: PresetSyncState) {
  if (state === 'current') return 'success' as const
  if (state === 'diverged') return 'warn' as const
  if (state === 'conflict') return 'danger' as const
  return 'info' as const
}

function togglePreset(name: string) {
  const next = new Set(selectedPresets.value)
  if (next.has(name)) next.delete(name)
  else next.add(name)
  selectedPresets.value = next
}

async function onApplyPresets(all: boolean) {
  const names = all ? presets.value.filter(p => p.state === 'missing' || p.state === 'diverged').map(p => p.name) : [...selectedPresets.value]
  if (!names.length) return
  if (!confirm(all
    ? `将同步全部 ${names.length} 个待处理预置 Skill，已偏离项的旧副本会备份至 .preset-backups/。是否继续？`
    : `将同步所选 ${names.length} 个预置 Skill，已偏离项的旧副本会备份至 .preset-backups/。是否继续？`)) return
  applyingPresets.value = true
  presetError.value = null
  try {
    const res = await applySkillPresets(names)
    if (res.failures.length) {
      toast(`同步完成，${res.outcomes.length} 项成功，${res.failures.length} 项失败：${res.failures.join('、')}`, 'error', 5000)
    } else {
      toast(`已同步 ${res.outcomes.length} 个预置 Skill`)
    }
    selectedPresets.value = new Set()
    await loadAll()
    if (selectedName.value) await reloadDetail()
  } catch (e: unknown) {
    presetError.value = (e as Error).message
    toast('预置同步失败', 'error')
  } finally {
    applyingPresets.value = false
  }
}

async function selectSkill(name: string) {
  if (name === selectedName.value) return
  if (fileDirty.value && !confirm('当前文件有未保存的修改，切换后将丢失。是否继续？')) return
  selectedName.value = name
  await reloadDetail()
}

async function reloadDetail() {
  loadingDetail.value = true
  detailError.value = null
  fileError.value = null
  try {
    detail.value = await fetchSkill(selectedName.value)
    filePath.value = ''
    fileContent.value = ''
    fileOriginal.value = ''
  } catch (e: unknown) {
    detail.value = null
    detailError.value = (e as Error).message
  } finally {
    loadingDetail.value = false
  }
}

async function openFile(path: string) {
  if (path === filePath.value) return
  if (fileDirty.value && !confirm('当前文件有未保存的修改，切换后将丢失。是否继续？')) return
  filePath.value = path
  loadingFile.value = true
  fileError.value = null
  try {
    const data = await fetchSkillFile(selectedName.value, path)
    fileContent.value = data.content
    fileOriginal.value = data.content
  } catch (e: unknown) {
    filePath.value = ''
    fileError.value = (e as Error).message
    toast((e as Error).message, 'error')
  } finally {
    loadingFile.value = false
  }
}

async function onSaveFile() {
  savingFile.value = true
  fileError.value = null
  try {
    await saveSkillFile(selectedName.value, filePath.value, fileContent.value)
    fileOriginal.value = fileContent.value
    toast('已保存')
    await loadList()
  } catch (e: unknown) {
    fileError.value = (e as Error).message
    toast('保存失败', 'error')
  } finally {
    savingFile.value = false
  }
}

async function onDeleteFile(path: string) {
  if (!confirm(`确定删除文件 ${path}？该操作不可撤销。`)) return
  try {
    await deleteSkillFile(selectedName.value, path)
    toast('已删除')
    if (filePath.value === path) {
      filePath.value = ''
      fileContent.value = ''
      fileOriginal.value = ''
    }
    await reloadDetail()
    await loadList()
  } catch (e: unknown) {
    toast((e as Error).message, 'error')
  }
}

function startCreate() {
  const raw = prompt('Skill 名称（小写字母/数字/连字符，字母或数字开头，≤64 字符）')
  if (!raw) return
  const name = raw.trim()
  if (!SKILL_NAME_PATTERN.test(name) || name.length > 64) {
    toast('名称不合法：需匹配 ^[a-z0-9][a-z0-9-]*$ 且不超过 64 字符', 'error')
    return
  }
  if (skills.value.some(s => s.name === name)) {
    toast('同名 Skill 已存在', 'error')
    return
  }
  void doCreate(name)
}

async function doCreate(name: string) {
  const content = [
    '---',
    `name: ${name}`,
    'description: 一句话说明这个 Skill 能做什么、何时该被调用',
    '---',
    '',
    `# ${name}`,
    '',
    '<!-- 在这里编写给 LLM 的指令正文 -->',
    '',
  ].join('\n')
  try {
    await createSkill(name, content)
    toast('已创建')
    await loadList()
    selectedName.value = name
    await reloadDetail()
    await openFile('SKILL.md')
  } catch (e: unknown) {
    toast((e as Error).message, 'error')
  }
}

async function onDeleteSkill() {
  if (!selectedName.value) return
  const s = skills.value.find(x => x.name === selectedName.value)
  const scriptNote = s?.has_scripts ? '\n注意：该 Skill 携带可执行脚本。' : ''
  if (!confirm(`确定删除 Skill「${selectedName.value}」？整个目录将被移除且不可恢复。${scriptNote}`)) return
  try {
    await deleteSkill(selectedName.value)
    toast('已删除')
    selectedName.value = ''
    detail.value = null
    filePath.value = ''
    await loadAll()
  } catch (e: unknown) {
    toast((e as Error).message, 'error')
  }
}

async function onInstalled(name: string) {
  await loadAll()
  selectedName.value = name
  await reloadDetail()
}

function formatSize(n: number): string {
  if (n < 1024) return `${n} B`
  if (n < 1024 * 1024) return `${(n / 1024).toFixed(1)} KiB`
  return `${(n / 1024 / 1024).toFixed(2)} MiB`
}
</script>

<style scoped>
.skills-view { display: flex; flex-direction: column; flex: 1; min-height: 0; }
.error { color: var(--qq-danger); font-size: var(--qq-text-sm); }
.mono { font-family: var(--qq-font-mono); }

.preset-panel {
  background: var(--qq-surface);
  border: 1px solid var(--qq-border);
  border-radius: var(--qq-radius-card);
  box-shadow: var(--qq-shadow-card);
  padding: var(--qq-gap-sm) var(--qq-gap-md);
  margin-bottom: var(--qq-gap-md);
  display: flex;
  flex-direction: column;
  gap: var(--qq-gap-xs);
}

.preset-head {
  display: flex;
  align-items: center;
  gap: var(--qq-gap-xs);
}

.preset-title {
  font-size: var(--qq-text-sm);
  font-weight: 700;
  color: var(--qq-text);
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

.split { display: flex; gap: var(--qq-gap-md); flex: 1; min-height: 0; }

.list-panel {
  width: 280px;
  flex-shrink: 0;
  background: var(--qq-surface);
  border: 1px solid var(--qq-border);
  border-radius: var(--qq-radius-card);
  box-shadow: var(--qq-shadow-card);
  overflow: hidden;
  display: flex;
  flex-direction: column;
}

.list-scroll { overflow-y: auto; flex: 1; }

.list-item {
  display: block;
  width: 100%;
  text-align: left;
  padding: var(--qq-gap-sm) var(--qq-gap-md);
  border: none;
  border-bottom: 1px solid var(--qq-border-soft);
  background: transparent;
  cursor: pointer;
  font-family: var(--qq-font-base);
  transition: background var(--qq-transition-fast);
}

.list-item-head {
  display: flex;
  align-items: center;
  gap: var(--qq-gap-xs);
  flex-wrap: wrap;
  margin-bottom: 2px;
}

.skill-name {
  font-size: var(--qq-text-sm);
  font-weight: 600;
  color: var(--qq-text);
  word-break: break-all;
}

.list-item-desc {
  font-size: var(--qq-text-xs);
  color: var(--qq-text-muted);
  line-height: 1.5;
  display: -webkit-box;
  -webkit-line-clamp: 2;
  -webkit-box-orient: vertical;
  overflow: hidden;
}

.list-item-desc--error { color: var(--qq-danger); }

.detail-col {
  display: flex;
  flex-direction: column;
  flex: 1;
  min-width: 0;
  min-height: 0;
  gap: var(--qq-gap-sm);
  overflow-y: auto;
}

.hint-panel {
  flex: 1;
  display: flex;
  align-items: center;
  justify-content: center;
  background: var(--qq-surface);
  border-radius: var(--qq-radius-card);
  box-shadow: var(--qq-shadow-card);
}

.diag-banner {
  display: flex;
  align-items: flex-start;
  gap: 6px;
  padding: var(--qq-gap-sm) var(--qq-gap-md);
  border: 1px solid var(--qq-danger);
  border-radius: var(--qq-radius-sm);
  background: var(--qq-danger-soft);
  color: var(--qq-danger);
  font-size: var(--qq-text-sm);
}

.diag-banner > :first-child { margin-top: 2px; }

.diag-list { display: flex; flex-direction: column; gap: 4px; min-width: 0; }

.diag-item { display: flex; align-items: center; gap: 6px; flex-wrap: wrap; }

.meta-card {
  background: var(--qq-surface);
  border: 1px solid var(--qq-border);
  border-radius: var(--qq-radius-card);
  box-shadow: var(--qq-shadow-card);
  padding: var(--qq-gap-sm) var(--qq-gap-md);
  display: flex;
  flex-direction: column;
  gap: 4px;
}

.meta-row {
  display: flex;
  gap: var(--qq-gap-sm);
  font-size: var(--qq-text-sm);
  align-items: baseline;
}

.meta-key {
  flex-shrink: 0;
  width: 120px;
  color: var(--qq-text-muted);
  font-size: var(--qq-text-xs);
}

.meta-val { color: var(--qq-text); word-break: break-word; }

.meta-val--muted { color: var(--qq-text-muted); font-size: var(--qq-text-xs); }

.file-table-wrap {
  background: var(--qq-surface);
  border: 1px solid var(--qq-border);
  border-radius: var(--qq-radius-card);
  box-shadow: var(--qq-shadow-card);
  overflow-x: auto;
}

.file-table {
  width: 100%;
  border-collapse: collapse;
  font-size: var(--qq-text-sm);
}

.file-table th {
  text-align: left;
  color: var(--qq-text-muted);
  font-size: var(--qq-text-xs);
  font-weight: 600;
  padding: var(--qq-gap-xs) var(--qq-gap-sm);
  border-bottom: 1px solid var(--qq-border);
}

.file-table td {
  padding: var(--qq-gap-xs) var(--qq-gap-sm);
  border-bottom: 1px solid var(--qq-border-soft);
  color: var(--qq-text);
}

.file-table tr:last-child td { border-bottom: none; }

.file-row.active td { background: var(--qq-primary-soft); }

.file-open {
  display: inline-flex;
  align-items: center;
  gap: 6px;
  border: none;
  background: transparent;
  color: var(--qq-primary);
  font-size: var(--qq-text-sm);
  cursor: pointer;
  padding: 0;
  word-break: break-all;
  text-align: left;
}

.file-open:hover { text-decoration: underline; }

.file-kind { color: var(--qq-text-muted); font-size: var(--qq-text-xs); }

.file-size {
  color: var(--qq-text-muted);
  font-family: var(--qq-font-mono);
  font-size: var(--qq-text-xs);
  white-space: nowrap;
}

.col-actions { width: 44px; text-align: right; }

.script-banner {
  display: flex;
  align-items: center;
  gap: 6px;
  padding: var(--qq-gap-sm) var(--qq-gap-md);
  border: 1px solid var(--qq-warn);
  border-radius: var(--qq-radius-sm);
  background: var(--qq-warn-soft);
  color: var(--qq-warn);
  font-size: var(--qq-text-sm);
  font-weight: 600;
}

.editor-bar {
  display: flex;
  align-items: center;
  gap: var(--qq-gap-sm);
}

.editor-path {
  flex: 1;
  min-width: 0;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
  color: var(--qq-text);
  font-size: var(--qq-text-sm);
}

.dirty-pill {
  flex-shrink: 0;
  height: 24px;
  display: inline-flex;
  align-items: center;
  padding: 0 10px;
  border-radius: var(--qq-radius-full);
  background: var(--qq-primary-soft);
  color: var(--qq-primary);
  font-size: var(--qq-text-xs);
  font-weight: 700;
}

.file-editor {
  flex: 1;
  width: 100%;
  min-height: 300px;
  padding: var(--qq-gap-md);
  border: 1px solid var(--qq-border);
  border-radius: var(--qq-radius-card);
  background: var(--qq-surface);
  color: var(--qq-text);
  font-family: var(--qq-font-mono);
  font-size: var(--qq-text-sm);
  line-height: 1.7;
  resize: none;
  outline: none;
  box-shadow: var(--qq-shadow-card);
}

.file-editor:focus { border-color: var(--qq-primary); }

@media (max-width: 900px) {
  .split { flex-direction: column; }
  .list-panel { width: 100%; max-height: 200px; }
  .meta-key { width: 88px; }
}
</style>
