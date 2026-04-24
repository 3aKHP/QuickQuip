<template>
  <div class="wc-view">
    <UiPageHeader title="词云" subtitle="对选定群在指定时间窗内的消息做分词并渲染词云图">
      <template #actions>
        <UiButton icon="RefreshCw" :disabled="loading" @click="loadGroups">刷新</UiButton>
      </template>
    </UiPageHeader>

    <p v-if="loadError" class="error">{{ loadError }}</p>

    <UiCard padding="md" shadow="sm" class="controls-card">
      <div class="controls-row">
        <label class="control">
          群组
          <select v-model="groupId" :disabled="!groups.length">
            <option value="">-- 选择群 --</option>
            <option v-for="g in groups" :key="g.group_id" :value="g.group_id">
              {{ g.group_id }}（{{ g.days }} 天 / {{ formatBytes(g.total_bytes) }}）
            </option>
          </select>
        </label>

        <label class="control">
          时间窗
          <div class="window-row">
            <button
              v-for="w in WINDOWS"
              :key="w.key"
              class="window-btn"
              :class="{ active: windowKey === w.key }"
              type="button"
              @click="windowKey = w.key"
            >{{ w.label }}</button>
          </div>
        </label>

        <UiButton
          variant="primary"
          icon="Play"
          :loading="rendering"
          :disabled="!groupId"
          @click="onRender"
        >生成</UiButton>
      </div>
      <p class="hint">
        <UiIcon name="Info" :size="14" />
        分词与渲染都在后端进行，单群全年数据可能需要数秒到十几秒
      </p>
    </UiCard>

    <p v-if="renderError" class="error render-error">{{ renderError }}</p>

    <div v-if="result" class="result">
      <div class="summary">
        <UiTag size="sm">{{ result.window === 'today' ? '今日' : result.window === 'week' ? '近 7 天' : result.window === 'month' ? '近 30 天' : '近一年' }}</UiTag>
        <span>{{ result.message_count }} 条消息</span>
        <span>·</span>
        <span>{{ result.word_count }} 个有效词</span>
        <span>·</span>
        <span>{{ result.unique_words }} 个 unique</span>
        <a :href="imageDataUrl" download="wordcloud.png" class="download-link">下载图片</a>
      </div>

      <div class="result-body">
        <UiCard padding="none" shadow="md" class="image-card">
          <img :src="imageDataUrl" class="wc-image" />
        </UiCard>

        <UiCard padding="md" shadow="sm" class="top-card">
          <h3 class="top-title">Top {{ result.top_words.length }} 词频</h3>
          <ol class="top-list">
            <li v-for="(w, i) in result.top_words" :key="w.word">
              <span class="rank">{{ String(Number(i) + 1) }}</span>
              <span class="word">{{ w.word }}</span>
              <span class="count">{{ w.count }}</span>
            </li>
          </ol>
        </UiCard>
      </div>
    </div>

    <UiEmpty
      v-else-if="!groups.length && !loading"
      icon="BarChart2"
      title="尚无任何群的词云消息记录"
    />
  </div>
</template>

<script setup lang="ts">
import { computed, ref } from 'vue'
import UiPageHeader from '../components/ui/UiPageHeader.vue'
import UiButton from '../components/ui/UiButton.vue'
import UiCard from '../components/ui/UiCard.vue'
import UiTag from '../components/ui/UiTag.vue'
import UiIcon from '../components/ui/UiIcon.vue'
import UiEmpty from '../components/ui/UiEmpty.vue'
import { listWordcloudGroups, renderWordcloud } from '../api/wordcloud'
import { toast } from '../toast'

const WINDOWS = [
  { key: 'today', label: '今日' },
  { key: 'week', label: '近 7 天' },
  { key: 'month', label: '近 30 天' },
  { key: 'year', label: '近一年' },
]

const groups = ref<any[]>([])
const loading = ref(false)
const loadError = ref<string | null>(null)

const groupId = ref('')
const windowKey = ref('today')
const rendering = ref(false)
const renderError = ref<string | null>(null)
const result = ref<any>(null)

const imageDataUrl = computed(() =>
  result.value ? `data:image/png;base64,${result.value.image_base64}` : ''
)

function formatBytes(n: number): string {
  if (n < 1024) return `${n} B`
  if (n < 1024 * 1024) return `${(n / 1024).toFixed(1)} KB`
  return `${(n / 1024 / 1024).toFixed(1)} MB`
}

async function loadGroups() {
  loading.value = true
  loadError.value = null
  try {
    const data = await listWordcloudGroups()
    groups.value = data.groups || []
  } catch (e: unknown) {
    loadError.value = (e as Error).message
  } finally {
    loading.value = false
  }
}

async function onRender() {
  if (!groupId.value) return
  rendering.value = true
  renderError.value = null
  try {
    result.value = await renderWordcloud(groupId.value, windowKey.value)
  } catch (e: unknown) {
    result.value = null
    renderError.value = ((e as any).data?.detail as string) || (e as Error).message
    toast('生成失败', 'error')
  } finally {
    rendering.value = false
  }
}

loadGroups()
</script>

<style scoped>
.wc-view {
  display: flex;
  flex-direction: column;
  flex: 1;
  min-height: 0;
}

.error { color: var(--qq-danger); }
.render-error { margin-top: var(--qq-gap-sm); }

.controls-card {
  margin-bottom: var(--qq-gap-md);
}

.controls-row {
  display: flex;
  align-items: flex-end;
  gap: var(--qq-gap-md);
  flex-wrap: wrap;
}

.control {
  display: flex;
  flex-direction: column;
  gap: var(--qq-gap-xs);
  font-size: 12px;
  color: var(--qq-text-muted);
}

.control select {
  background: var(--qq-surface-strong);
  border: 1px solid var(--qq-border);
  border-radius: var(--qq-radius-sm);
  color: var(--qq-text);
  padding: 6px 10px;
  font-size: 13px;
  outline: none;
  min-width: 280px;
}

.control select:focus {
  border-color: var(--qq-accent);
  box-shadow: 0 0 0 3px var(--qq-accent-soft);
}

.window-row {
  display: inline-flex;
  gap: 2px;
}

.window-btn {
  padding: 6px 12px;
  background: var(--qq-surface-strong);
  border: 1px solid var(--qq-border);
  color: var(--qq-text-muted);
  font-size: 13px;
  cursor: pointer;
  transition: color var(--qq-transition-fast), background var(--qq-transition-fast);
}

.window-btn:first-child {
  border-top-left-radius: var(--qq-radius-sm);
  border-bottom-left-radius: var(--qq-radius-sm);
}

.window-btn:last-child {
  border-top-right-radius: var(--qq-radius-sm);
  border-bottom-right-radius: var(--qq-radius-sm);
}

.window-btn:hover:not(.active) {
  color: var(--qq-text);
  background: var(--qq-surface-elevated);
}

.window-btn.active {
  background: var(--qq-accent-soft);
  color: var(--qq-accent);
  border-color: var(--qq-accent);
}

.hint {
  display: inline-flex;
  align-items: center;
  gap: 6px;
  color: var(--qq-text-muted);
  font-size: 12px;
  margin: var(--qq-gap-sm) 0 0;
}

.summary {
  display: flex;
  align-items: center;
  gap: var(--qq-gap-sm);
  color: var(--qq-text-muted);
  font-size: 13px;
  margin-bottom: var(--qq-gap-sm);
  flex-wrap: wrap;
}

.download-link {
  margin-left: auto;
  color: var(--qq-accent);
  text-decoration: none;
  font-size: 13px;
}

.download-link:hover { text-decoration: underline; }

.result-body {
  display: grid;
  grid-template-columns: minmax(0, 2fr) minmax(240px, 1fr);
  gap: var(--qq-gap-md);
  align-items: start;
}

.image-card {
  overflow: hidden;
}

.wc-image {
  width: 100%;
  display: block;
  background: #fff;
}

.top-card {
  max-height: 600px;
  overflow-y: auto;
}

.top-title {
  margin: 0 0 var(--qq-gap-sm);
  font-size: 14px;
  color: var(--qq-text);
}

.top-list {
  list-style: none;
  padding: 0;
  margin: 0;
  display: flex;
  flex-direction: column;
  gap: 2px;
}

.top-list li {
  display: grid;
  grid-template-columns: 28px 1fr auto;
  align-items: center;
  gap: var(--qq-gap-sm);
  padding: 4px 6px;
  border-radius: var(--qq-radius-sm);
  font-size: 13px;
}

.top-list li:hover { background: var(--qq-surface-elevated); }

.rank {
  color: var(--qq-text-muted);
  font-family: var(--qq-font-mono);
  font-size: 12px;
  text-align: right;
}

.word {
  color: var(--qq-text);
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.count {
  color: var(--qq-text-muted);
  font-family: var(--qq-font-mono);
  font-size: 12px;
}

@media (max-width: 900px) {
  .result-body {
    grid-template-columns: 1fr;
  }
  .top-card { max-height: 400px; }
}
</style>
