<template>
  <div class="install-overlay" @click.self="emit('close')">
    <UiCard padding="lg" shadow="lg" class="install-card">
      <div class="install-head">
        <h3 class="install-title">安装 Skill</h3>
        <button class="install-close" @click="emit('close')"><UiIcon name="X" :size="18" /></button>
      </div>

      <div class="install-tabs">
        <button
          v-for="t in SOURCE_TABS"
          :key="t.key"
          class="install-tab"
          :class="{ active: tab === t.key }"
          @click="switchTab(t.key)"
        >{{ t.label }}</button>
      </div>

      <div class="install-body">
        <template v-if="!candidates.length">
          <div v-if="tab === 'zip'" class="source-pane">
            <p class="source-hint">选择本地 .zip 压缩包（≤16MiB）。包内每个含 SKILL.md 的目录都会成为一个候选。</p>
            <input ref="zipInput" type="file" accept=".zip" class="source-file" :disabled="inspecting" @change="onZipChange" />
          </div>
          <div v-else-if="tab === 'folder'" class="source-pane">
            <p class="source-hint">选择本地文件夹，将整目录上传检查。文件夹内每个含 SKILL.md 的目录都会成为一个候选。</p>
            <input ref="folderInput" type="file" class="source-file" :disabled="inspecting" @change="onFolderChange" />
          </div>
          <div v-else class="source-pane">
            <p class="source-hint">支持 https://github.com/&lt;owner&gt;/&lt;repo&gt;[/tree/&lt;ref&gt;[/&lt;子目录&gt;]]，将从 codeload.github.com 下载 zip。</p>
            <div class="source-url">
              <input v-model="githubUrl" type="text" class="source-url-input" placeholder="https://github.com/owner/repo" :disabled="inspecting" @keyup.enter="onGithubInspect" />
              <UiButton variant="primary" icon="Download" :loading="inspecting" :disabled="!githubUrl.trim()" @click="onGithubInspect">检查</UiButton>
            </div>
          </div>
          <UiLoading v-if="inspecting" text="正在解析候选…" />
        </template>

        <template v-else>
          <div class="result-head">
            <span class="result-title">候选报告（{{ candidates.length }}）</span>
            <span v-if="sourceUrl" class="result-source mono">{{ sourceUrl }}</span>
            <UiButton size="sm" variant="ghost" icon="RotateCw" @click="resetResult">重新选择</UiButton>
          </div>

          <div class="candidate-list">
            <label
              v-for="c in candidates"
              :key="c.root"
              class="candidate-item"
              :class="{ active: c.root === selectedRoot, disabled: !c.ok }"
            >
              <input type="radio" name="import-candidate" :value="c.root" v-model="selectedRoot" :disabled="!c.ok" />
              <div class="candidate-main">
                <div class="candidate-head">
                  <span class="candidate-name mono">{{ c.ok ? c.name : (c.root || '（根目录）') }}</span>
                  <UiTag v-if="!c.ok" size="sm" variant="danger">解析失败</UiTag>
                  <UiTag v-else-if="c.conflict" size="sm" variant="warn">同名冲突</UiTag>
                  <UiTag v-else size="sm" variant="success">可安装</UiTag>
                </div>
                <div v-if="c.description" class="candidate-desc">{{ c.description }}</div>
                <div class="candidate-meta">{{ c.file_count }} 个文件 · {{ formatSize(c.total_bytes) }}</div>
                <ul v-if="c.diagnostics.length" class="candidate-diagnostics">
                  <li v-for="(d, i) in c.diagnostics" :key="i"><span class="diag-kind mono">{{ d.kind }}</span>{{ d.message }}</li>
                </ul>
              </div>
            </label>
          </div>

          <div v-if="selected && selected.has_scripts" class="scripts-warning">
            <div class="scripts-warning__head">
              <UiIcon name="AlertTriangle" :size="15" />
              该 Skill 携带可执行脚本，安装后将以 bot 进程权限在本机运行
            </div>
            <ul class="scripts-warning__list">
              <li v-for="f in selected.script_files" :key="f" class="mono">{{ f }}</li>
            </ul>
          </div>

          <label v-if="selected && selected.conflict" class="overwrite-check">
            <input type="checkbox" v-model="overwrite" />
            覆盖安装（旧副本将备份至 .preset-backups/）
          </label>
        </template>

        <p v-if="error" class="error">{{ error }}</p>
      </div>

      <div class="install-foot">
        <UiButton variant="ghost" @click="emit('close')">取消</UiButton>
        <UiButton
          v-if="candidates.length"
          variant="primary"
          icon="Check"
          :loading="confirming"
          :disabled="!canConfirm"
          @click="onConfirm"
        >确认安装</UiButton>
      </div>
    </UiCard>
  </div>
</template>

<script setup lang="ts">
import { computed, onMounted, ref } from 'vue'
import UiCard from '../ui/UiCard.vue'
import UiIcon from '../ui/UiIcon.vue'
import UiButton from '../ui/UiButton.vue'
import UiTag from '../ui/UiTag.vue'
import UiLoading from '../ui/UiLoading.vue'
import { inspectSkillImport, inspectGithubImport, confirmSkillImport } from '../../api/skills'
import type { ImportCandidate } from '../../api/skills'
import { toast } from '../../toast'

const emit = defineEmits<{
  close: []
  installed: [name: string]
}>()

type SourceTab = 'zip' | 'folder' | 'github'
const SOURCE_TABS: { key: SourceTab; label: string }[] = [
  { key: 'zip', label: '压缩包' },
  { key: 'folder', label: '文件夹' },
  { key: 'github', label: 'GitHub 链接' },
]

const ZIP_LIMIT = 16 * 1024 * 1024

const tab = ref<SourceTab>('zip')
const inspecting = ref(false)
const confirming = ref(false)
const error = ref<string | null>(null)
const githubUrl = ref('')
const sourceUrl = ref('')
const token = ref('')
const candidates = ref<ImportCandidate[]>([])
const selectedRoot = ref('')
const overwrite = ref(false)

const zipInput = ref<HTMLInputElement | null>(null)
const folderInput = ref<HTMLInputElement | null>(null)

// TS 不识别非标准属性 webkitdirectory，挂载时以 setAttribute 透传
onMounted(() => {
  folderInput.value?.setAttribute('webkitdirectory', '')
})

const selected = computed(() => candidates.value.find(c => c.root === selectedRoot.value) || null)
const canConfirm = computed(() => {
  const c = selected.value
  if (!c || !c.ok) return false
  if (c.conflict && !overwrite.value) return false
  return true
})

function switchTab(t: SourceTab) {
  if (t === tab.value) return
  tab.value = t
  resetResult()
}

function resetResult() {
  token.value = ''
  candidates.value = []
  selectedRoot.value = ''
  overwrite.value = false
  error.value = null
  sourceUrl.value = ''
}

/** 分块 base64：避免大参数展开导致栈溢出 */
function bytesToBase64(bytes: Uint8Array): string {
  let binary = ''
  const CHUNK = 0x8000
  for (let i = 0; i < bytes.length; i += CHUNK) {
    binary += String.fromCharCode(...bytes.subarray(i, i + CHUNK))
  }
  return btoa(binary)
}

function formatSize(n: number): string {
  if (n < 1024) return `${n} B`
  if (n < 1024 * 1024) return `${(n / 1024).toFixed(1)} KiB`
  return `${(n / 1024 / 1024).toFixed(2)} MiB`
}

async function runInspect(fn: () => Promise<{ token: string; candidates: ImportCandidate[] }>, source = '') {
  inspecting.value = true
  error.value = null
  try {
    const res = await fn()
    if (!res.candidates.length) {
      error.value = '未检出任何 SKILL.md，无法识别为 Skill'
      return
    }
    token.value = res.token
    candidates.value = res.candidates
    sourceUrl.value = source
    const firstOk = res.candidates.find(c => c.ok)
    selectedRoot.value = (firstOk || res.candidates[0]).root
  } catch (e: unknown) {
    error.value = (e as Error).message
  } finally {
    inspecting.value = false
  }
}

async function onZipChange(e: Event) {
  const input = e.target as HTMLInputElement
  const file = input.files?.[0]
  input.value = ''
  if (!file) return
  if (file.size > ZIP_LIMIT) {
    error.value = `压缩包体积 ${formatSize(file.size)} 超过 16MiB 上限，请压缩精简或改用 GitHub 导入`
    return
  }
  const buf = new Uint8Array(await file.arrayBuffer())
  await runInspect(() => inspectSkillImport({ kind: 'zip', archive_b64: bytesToBase64(buf) }))
}

async function onFolderChange(e: Event) {
  const input = e.target as HTMLInputElement
  const list = Array.from(input.files || [])
  input.value = ''
  if (!list.length) return
  const files: Record<string, string> = {}
  for (const f of list) {
    const rel = (f.webkitRelativePath || f.name).replace(/^[^/]+\//, '')
    if (!rel) continue
    files[rel] = bytesToBase64(new Uint8Array(await f.arrayBuffer()))
  }
  if (!Object.keys(files).length) {
    error.value = '所选文件夹为空'
    return
  }
  await runInspect(() => inspectSkillImport({ kind: 'folder', files }))
}

async function onGithubInspect() {
  const url = githubUrl.value.trim()
  if (!url) return
  await runInspect(() => inspectGithubImport(url), url)
}

async function onConfirm() {
  const c = selected.value
  if (!c || !canConfirm.value) return
  confirming.value = true
  error.value = null
  try {
    const res = await confirmSkillImport(token.value, c.root, overwrite.value)
    toast(res.backup ? `已安装 ${res.name}（旧副本已备份）` : `已安装 ${res.name}`)
    emit('installed', res.name)
    emit('close')
  } catch (e: unknown) {
    error.value = (e as Error).message
  } finally {
    confirming.value = false
  }
}
</script>

<style scoped>
.mono { font-family: var(--qq-font-mono); }
.error { color: var(--qq-danger); font-size: var(--qq-text-sm); }

.install-overlay {
  position: fixed;
  inset: 0;
  background: var(--qq-overlay-strong);
  display: flex;
  align-items: flex-start;
  justify-content: center;
  z-index: 9998;
  padding: var(--qq-gap-lg);
  overflow-y: auto;
}

.install-card {
  width: min(680px, 100%);
  max-height: calc(100vh - 64px);
  display: flex;
  flex-direction: column;
}

.install-head {
  display: flex;
  align-items: center;
  justify-content: space-between;
  margin-bottom: var(--qq-gap-md);
}

.install-title {
  margin: 0;
  font-size: var(--qq-text-lg);
  color: var(--qq-text);
}

.install-close {
  background: transparent;
  border: none;
  color: var(--qq-text-muted);
  cursor: pointer;
  padding: 4px;
  border-radius: var(--qq-radius-sm);
}

.install-close:hover {
  color: var(--qq-text);
  background: var(--qq-surface-elevated);
}

.install-tabs {
  display: flex;
  gap: var(--qq-gap-xs);
  border-bottom: 1px solid var(--qq-border);
  margin-bottom: var(--qq-gap-md);
}

.install-tab {
  border: none;
  background: transparent;
  color: var(--qq-text-muted);
  font-family: var(--qq-font-base);
  font-size: var(--qq-text-sm);
  font-weight: 600;
  padding: var(--qq-gap-xs) var(--qq-gap-sm);
  cursor: pointer;
  border-bottom: 2px solid transparent;
  margin-bottom: -1px;
}

.install-tab.active {
  color: var(--qq-primary);
  border-bottom-color: var(--qq-primary);
}

.install-body {
  flex: 1;
  min-height: 0;
  overflow-y: auto;
  display: flex;
  flex-direction: column;
  gap: var(--qq-gap-sm);
}

.source-pane {
  display: flex;
  flex-direction: column;
  gap: var(--qq-gap-sm);
}

.source-hint {
  margin: 0;
  color: var(--qq-text-muted);
  font-size: var(--qq-text-sm);
  line-height: 1.6;
}

.source-file {
  color: var(--qq-text);
  font-size: var(--qq-text-sm);
}

.source-url {
  display: flex;
  gap: var(--qq-gap-sm);
}

.source-url-input {
  flex: 1;
  min-width: 0;
  min-height: 36px;
  padding: 0 var(--qq-gap-sm);
  border: 1px solid var(--qq-border);
  border-radius: var(--qq-radius-md);
  background: var(--qq-surface);
  color: var(--qq-text);
  font-family: var(--qq-font-mono);
  font-size: var(--qq-text-sm);
  outline: none;
}

.source-url-input:focus {
  border-color: var(--qq-primary);
}

.result-head {
  display: flex;
  align-items: center;
  gap: var(--qq-gap-sm);
}

.result-title {
  font-size: var(--qq-text-sm);
  font-weight: 700;
  color: var(--qq-text);
}

.result-source {
  flex: 1;
  min-width: 0;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
  color: var(--qq-text-muted);
  font-size: var(--qq-text-xs);
}

.result-head .ui-btn {
  margin-left: auto;
}

.candidate-list {
  display: flex;
  flex-direction: column;
  gap: var(--qq-gap-xs);
}

.candidate-item {
  display: flex;
  gap: var(--qq-gap-sm);
  padding: var(--qq-gap-sm);
  border: 1px solid var(--qq-border);
  border-radius: var(--qq-radius-sm);
  cursor: pointer;
  transition: border-color var(--qq-transition-fast);
}

.candidate-item.active {
  border-color: var(--qq-primary);
  background: var(--qq-primary-soft);
}

.candidate-item.disabled {
  opacity: 0.65;
  cursor: not-allowed;
}

.candidate-item input[type="radio"] {
  margin-top: 3px;
  accent-color: var(--qq-primary);
}

.candidate-main {
  flex: 1;
  min-width: 0;
  display: flex;
  flex-direction: column;
  gap: 3px;
}

.candidate-head {
  display: flex;
  align-items: center;
  gap: var(--qq-gap-xs);
}

.candidate-name {
  font-size: var(--qq-text-sm);
  font-weight: 600;
  color: var(--qq-text);
  word-break: break-all;
}

.candidate-desc {
  font-size: var(--qq-text-xs);
  color: var(--qq-text-muted);
  line-height: 1.5;
}

.candidate-meta {
  font-size: var(--qq-text-xs);
  color: var(--qq-text-quiet);
}

.candidate-diagnostics {
  margin: 0;
  padding-left: 18px;
  color: var(--qq-danger);
  font-size: var(--qq-text-xs);
  line-height: 1.6;
}

.diag-kind {
  display: inline-block;
  margin-right: 6px;
  padding: 0 6px;
  border-radius: var(--qq-radius-full);
  background: var(--qq-danger-soft);
  font-size: var(--qq-text-xs);
}

.scripts-warning {
  border: 1px solid var(--qq-danger);
  border-radius: var(--qq-radius-sm);
  background: var(--qq-danger-soft);
  padding: var(--qq-gap-sm);
}

.scripts-warning__head {
  display: flex;
  align-items: center;
  gap: 6px;
  color: var(--qq-danger);
  font-size: var(--qq-text-sm);
  font-weight: 600;
}

.scripts-warning__list {
  margin: 6px 0 0;
  padding-left: 20px;
  color: var(--qq-danger);
  font-size: var(--qq-text-xs);
  line-height: 1.6;
  word-break: break-all;
}

.overwrite-check {
  display: flex;
  align-items: center;
  gap: 6px;
  color: var(--qq-warn);
  font-size: var(--qq-text-sm);
  font-weight: 600;
  cursor: pointer;
}

.overwrite-check input {
  accent-color: var(--qq-warn);
}

.install-foot {
  display: flex;
  justify-content: flex-end;
  gap: var(--qq-gap-sm);
  margin-top: var(--qq-gap-md);
  padding-top: var(--qq-gap-md);
  border-top: 1px solid var(--qq-border);
}
</style>
