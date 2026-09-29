<template>
  <div class="skills-view page-view-fill">
    <UiPageHeader title="Skill 管理" subtitle="管理 LLM Skill 目录：在线编辑文本资源、安装第三方 Skill、同步仓库预置">
      <template #subtitle>
        <UiInfoTip text="Skill 每次群聊轮次现扫生效，保存文件后无需重启。scripts/ 下的脚本以 bot 进程权限在本机运行，编辑与安装前请确认来源可信。" />
      </template>
      <template #actions>
        <UiButton icon="RefreshCw" :disabled="listing" @click="onRefresh">刷新</UiButton>
        <UiButton icon="Plus" @click="startCreate">新建</UiButton>
        <UiButton icon="Upload" @click="installOpen = true">安装</UiButton>
        <UiButton variant="danger" icon="Trash2" :disabled="!selectedName" @click="onDeleteSkill">删除</UiButton>
      </template>
    </UiPageHeader>
    <p v-if="listError" class="error">{{ listError }}</p>

    <PresetSyncPanel ref="presetPanelRef" :before-apply="confirmEditorLeave" @applied="onPresetsApplied" />

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
            <SkillFileEditor
              ref="editorRef"
              :skill-name="selectedName"
              :resources="detail.resources"
              @saved="onFileSaved"
              @file-deleted="onFileDeleted"
            />
          </template>
          <template v-else-if="repairDiagnostics">
            <div class="diag-banner">
              <UiIcon name="AlertTriangle" :size="15" />
              <div class="diag-list">
                <div v-for="(d, i) in repairDiagnostics" :key="i" class="diag-item">
                  <UiTag size="sm" variant="danger">{{ d.kind }}</UiTag>
                  <span>{{ d.message }}</span>
                </div>
              </div>
            </div>
            <div class="repair-card">
              <p class="repair-text">该 Skill 的 SKILL.md 缺失或未通过解析校验，运行时会被扫描跳过。修复 SKILL.md 并保存后即可恢复加载，也可以直接删除整个目录。</p>
              <div class="repair-actions">
                <UiButton size="sm" variant="primary" icon="Pencil" @click="openSkillFileForRepair">编辑 SKILL.md</UiButton>
                <UiButton size="sm" variant="danger" icon="Trash2" @click="onDeleteSkill">删除该 Skill</UiButton>
              </div>
            </div>
            <SkillFileEditor
              ref="editorRef"
              :skill-name="selectedName"
              :resources="[]"
              @saved="onFileSaved"
              @file-deleted="onFileDeleted"
            />
          </template>
          <p v-else-if="detailError" class="error">{{ detailError }}</p>
        </template>
      </div>
    </div>

    <SkillInstallDialog v-if="installOpen" @close="installOpen = false" @installed="onInstalled" />
  </div>
</template>

<script setup lang="ts">
import { nextTick, onMounted, ref } from 'vue'
import UiPageHeader from '../components/ui/UiPageHeader.vue'
import UiButton from '../components/ui/UiButton.vue'
import UiTag from '../components/ui/UiTag.vue'
import UiIcon from '../components/ui/UiIcon.vue'
import UiLoading from '../components/ui/UiLoading.vue'
import UiEmpty from '../components/ui/UiEmpty.vue'
import UiInfoTip from '../components/ui/UiInfoTip.vue'
import SkillInstallDialog from '../components/skills/SkillInstallDialog.vue'
import SkillFileEditor from '../components/skills/SkillFileEditor.vue'
import PresetSyncPanel from '../components/skills/PresetSyncPanel.vue'
import { listSkills, createSkill, fetchSkill, deleteSkill } from '../api/skills'
import type { SkillSummary, SkillDetail, SkillDiagnostic } from '../api/skills'
import { toast } from '../toast'

const SKILL_NAME_PATTERN = /^[a-z0-9][a-z0-9-]*$/

const skills = ref<SkillSummary[]>([])
const listing = ref(false)
const listError = ref<string | null>(null)
const selectedName = ref('')
const detail = ref<SkillDetail | null>(null)
/** 修复模式：详情 404（坏 skill）时从错误结构解析出的诊断 */
const repairDiagnostics = ref<SkillDiagnostic[] | null>(null)
const loadingDetail = ref(false)
const detailError = ref<string | null>(null)

const editorRef = ref<InstanceType<typeof SkillFileEditor> | null>(null)
const presetPanelRef = ref<InstanceType<typeof PresetSyncPanel> | null>(null)

const installOpen = ref(false)

onMounted(loadList)

function onRefresh() {
  void loadList()
  void presetPanelRef.value?.reload()
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

/** 详情 404 的 detail 结构为 {message, diagnostics:[{kind,message}]}，经 request 封装挂到 error.data */
function extractDetailDiagnostics(e: unknown): SkillDiagnostic[] | null {
  const err = e as { status?: number; data?: unknown }
  if (err.status !== 404 || typeof err.data !== 'object' || err.data === null) return null
  const body = (err.data as Record<string, unknown>).detail
  if (typeof body !== 'object' || body === null) return null
  const diagnostics = (body as Record<string, unknown>).diagnostics
  if (!Array.isArray(diagnostics)) return null
  const parsed: SkillDiagnostic[] = []
  for (const item of diagnostics) {
    if (typeof item !== 'object' || item === null) return null
    const record = item as Record<string, unknown>
    if (typeof record.kind !== 'string' || typeof record.message !== 'string') return null
    parsed.push({ kind: record.kind, message: record.message })
  }
  return parsed
}

function confirmEditorLeave(): boolean {
  return editorRef.value?.confirmLeave() ?? true
}

async function selectSkill(name: string) {
  if (name === selectedName.value) return
  if (!confirmEditorLeave()) return
  selectedName.value = name
  await reloadDetail()
}

/** 切换/新建/安装后的全量加载；坏 skill 进入修复模式 */
async function reloadDetail() {
  loadingDetail.value = true
  detailError.value = null
  repairDiagnostics.value = null
  try {
    detail.value = await fetchSkill(selectedName.value)
  } catch (e: unknown) {
    detail.value = null
    const diagnostics = extractDetailDiagnostics(e)
    if (diagnostics) repairDiagnostics.value = diagnostics
    else detailError.value = (e as Error).message
  } finally {
    loadingDetail.value = false
  }
}

/** 保存/删文件后的轻量刷新：只替换详情数据，编辑器状态由子组件自持不受影响 */
async function refreshDetail() {
  try {
    detail.value = await fetchSkill(selectedName.value)
    repairDiagnostics.value = null
  } catch (e: unknown) {
    const diagnostics = extractDetailDiagnostics(e)
    if (diagnostics) {
      detail.value = null
      repairDiagnostics.value = diagnostics
    } else {
      toast((e as Error).message, 'error')
    }
  }
}

async function onFileSaved() {
  await loadList()
  await refreshDetail()
}

async function onFileDeleted() {
  await loadList()
  await refreshDetail()
}

async function onPresetsApplied() {
  await loadList()
  if (!selectedName.value) return
  // 同步会改写磁盘上的目录内容，编辑器内容可能已过期，关闭之
  editorRef.value?.reset()
  await refreshDetail()
}

function skillSkeleton(name: string): string {
  return [
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
  if (!confirmEditorLeave()) return
  void doCreate(name)
}

async function doCreate(name: string) {
  try {
    await createSkill(name, skillSkeleton(name))
    toast('已创建')
    await loadList()
    selectedName.value = name
    await reloadDetail()
    await nextTick()
    await editorRef.value?.openPath('SKILL.md')
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
    repairDiagnostics.value = null
    await loadList()
  } catch (e: unknown) {
    toast((e as Error).message, 'error')
  }
}

async function onInstalled(name: string) {
  if (!confirmEditorLeave()) {
    await loadList()
    return
  }
  await loadList()
  selectedName.value = name
  await reloadDetail()
}

function openSkillFileForRepair() {
  // SKILL.md 可能整个缺失（GET 404）：以骨架模板开路，保存即创建（PUT upsert）
  void editorRef.value?.openPath('SKILL.md', skillSkeleton(selectedName.value))
}
</script>

<style scoped>
.skills-view { display: flex; flex-direction: column; flex: 1; min-height: 0; }
.error { color: var(--qq-danger); font-size: var(--qq-text-sm); }
.mono { font-family: var(--qq-font-mono); }

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

.repair-card {
  background: var(--qq-surface);
  border: 1px solid var(--qq-border);
  border-radius: var(--qq-radius-card);
  box-shadow: var(--qq-shadow-card);
  padding: var(--qq-gap-md);
  display: flex;
  align-items: center;
  gap: var(--qq-gap-md);
  flex-wrap: wrap;
}

.repair-text {
  flex: 1;
  min-width: 240px;
  margin: 0;
  color: var(--qq-text-muted);
  font-size: var(--qq-text-sm);
  line-height: 1.6;
}

.repair-actions {
  display: flex;
  gap: var(--qq-gap-sm);
  flex-shrink: 0;
}

@media (max-width: 900px) {
  .split { flex-direction: column; }
  .list-panel { width: 100%; max-height: 200px; }
  .meta-key { width: 88px; }
}
</style>
