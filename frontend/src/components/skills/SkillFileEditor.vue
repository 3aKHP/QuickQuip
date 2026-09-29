<template>
  <div class="file-editor-col">
    <div v-if="resources.length" class="file-table-wrap">
      <table class="file-table">
        <thead>
          <tr><th>路径</th><th>类型</th><th>大小</th><th class="col-actions" /></tr>
        </thead>
        <tbody>
          <tr v-for="r in resources" :key="r.path" class="file-row" :class="{ active: r.path === filePath }">
            <td>
              <button class="file-open mono" @click="openPath(r.path)">
                {{ r.path }}
                <UiTag v-if="r.path.startsWith('scripts/')" size="sm" variant="warn">脚本</UiTag>
              </button>
            </td>
            <td class="file-kind">{{ r.kind }}</td>
            <td class="file-size">{{ formatSize(r.size_bytes) }}</td>
            <td class="col-actions">
              <UiButton
                v-if="r.path !== 'SKILL.md'"
                size="sm"
                variant="danger"
                icon="Trash2"
                title="删除该文件"
                @click="onDeleteFile(r.path)"
              >删除</UiButton>
            </td>
          </tr>
        </tbody>
      </table>
    </div>

    <UiEmpty v-if="!filePath && resources.length" compact icon="FileText" title="从上方资源表选择一个文件开始编辑" />

    <template v-if="filePath">
      <div v-if="filePath.startsWith('scripts/')" class="script-banner soft-note soft-note--warn">
        <UiIcon name="AlertTriangle" :size="15" />
        该文件是可执行脚本，将以 bot 进程权限在本机运行
      </div>
      <div class="editor-bar">
        <span class="mono editor-path">{{ filePath }}</span>
        <span v-if="dirty" class="dirty-pill">未保存</span>
        <UiButton variant="primary" icon="Save" :loading="saving" :disabled="!dirty" @click="onSave">保存</UiButton>
      </div>
      <p v-if="loadError" class="error">{{ loadError }}</p>
      <UiLoading v-if="loading" />
      <textarea v-else v-model="content" class="file-editor" spellcheck="false" autocomplete="off" />
    </template>
  </div>
</template>

<script setup lang="ts">
import { computed, ref, watch } from 'vue'
import UiButton from '../ui/UiButton.vue'
import UiTag from '../ui/UiTag.vue'
import UiIcon from '../ui/UiIcon.vue'
import UiLoading from '../ui/UiLoading.vue'
import UiEmpty from '../ui/UiEmpty.vue'
import { fetchSkillFile, saveSkillFile, deleteSkillFile } from '../../api/skills'
import type { SkillResource } from '../../api/skills'
import { formatSize } from '../../lib/formatSize'
import { toast } from '../../toast'

const props = defineProps<{
  skillName: string
  /** 资源清单；修复模式（坏 skill）下传空数组，仅经 openPath 打开文件 */
  resources: SkillResource[]
}>()

const emit = defineEmits<{
  saved: []
  fileDeleted: []
}>()

const filePath = ref('')
const content = ref('')
const original = ref('')
const loading = ref(false)
const saving = ref(false)
const loadError = ref<string | null>(null)
const dirty = computed(() => content.value !== original.value)

watch(() => props.skillName, () => reset())

function reset() {
  filePath.value = ''
  content.value = ''
  original.value = ''
  loadError.value = null
}

/** 未保存编辑确认：安全（无脏内容或用户确认放弃）返回 true */
function confirmLeave(): boolean {
  if (!dirty.value) return true
  return confirm('当前文件有未保存的修改，切换后将丢失。是否继续？')
}

async function openPath(path: string, seedContent?: string) {
  if (path === filePath.value) return
  if (!confirmLeave()) return
  filePath.value = path
  loading.value = true
  loadError.value = null
  try {
    const data = await fetchSkillFile(props.skillName, path)
    content.value = data.content
    original.value = data.content
  } catch (e: unknown) {
    if (seedContent !== undefined && (e as { status?: number }).status === 404) {
      // 文件缺失：以种子内容开路，保存时由 PUT upsert 创建
      content.value = seedContent
      original.value = ''
    } else {
      filePath.value = ''
      loadError.value = (e as Error).message
      toast((e as Error).message, 'error')
    }
  } finally {
    loading.value = false
  }
}

async function onSave() {
  saving.value = true
  loadError.value = null
  try {
    await saveSkillFile(props.skillName, filePath.value, content.value)
    original.value = content.value
    toast('已保存')
    emit('saved')
  } catch (e: unknown) {
    loadError.value = (e as Error).message
    toast('保存失败', 'error')
  } finally {
    saving.value = false
  }
}

async function onDeleteFile(path: string) {
  if (!confirm(`确定删除文件 ${path}？该操作不可撤销。`)) return
  try {
    await deleteSkillFile(props.skillName, path)
    toast('已删除')
    // 仅被删文件正在打开时才关闭编辑器；删除其他文件保持编辑器现状
    if (filePath.value === path) reset()
    emit('fileDeleted')
  } catch (e: unknown) {
    toast((e as Error).message, 'error')
  }
}

defineExpose({ confirmLeave, openPath, reset })
</script>

<style scoped>
.mono { font-family: var(--qq-font-mono); }
.error { color: var(--qq-danger); font-size: var(--qq-text-sm); }

.file-editor-col {
  display: flex;
  flex-direction: column;
  gap: var(--qq-gap-sm);
  min-height: 0;
  flex: 1;
}

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

/* 选中行对齐 qq-selectable 语言：primary-soft 底 + 左侧内嵌指示条 */
.file-row.active td { background: var(--qq-primary-soft); }

.file-row.active td:first-child { box-shadow: inset 3px 0 0 var(--qq-primary); }

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

.col-actions { width: 64px; text-align: right; }

.script-banner {
  display: flex;
  align-items: center;
  gap: 6px;
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
</style>
