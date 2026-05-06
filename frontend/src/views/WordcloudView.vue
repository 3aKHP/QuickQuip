<template>
  <div>
    <UiPageHeader title="词云" subtitle="对选定群在指定时间窗内的消息做分词并渲染词云图"><template #actions><UiButton icon="RefreshCw" :disabled="loading" @click="loadGroups">刷新</UiButton></template></UiPageHeader>
    <p v-if="loadError" class="error">{{ loadError }}</p>
    <div class="controls">
      <label class="ctrl">群组<select v-model="groupId" :disabled="!groups.length"><option value="">-- 选择群 --</option><option v-for="g in groups" :key="g.group_id" :value="g.group_id">{{ g.group_id }}（{{ g.days }} 天 / {{ fmtBytes(g.total_bytes) }}）</option></select></label>
      <label class="ctrl">时间窗<div class="win-row"><button v-for="w in WINS" :key="w.k" class="win-btn" :class="{ active: windowKey === w.k }" @click="windowKey = w.k">{{ w.l }}</button></div></label>
      <UiButton variant="primary" icon="RefreshCw" :loading="rendering" :disabled="!groupId" @click="onRender">生成</UiButton>
    </div>
    <p class="hint"><UiIcon name="Info" :size="14" />分词与渲染都在后端进行，单群全年数据可能需要数秒到十几秒</p>
    <p v-if="renderError" class="error">{{ renderError }}</p>
    <div v-if="result">
      <div class="sum-row"><UiTag size="sm">{{ winLabel }}</UiTag><span class="muted">{{ result.message_count }} 条 · {{ result.word_count }} 词 · {{ result.unique_words }} unique</span><a :href="imgUrl" download="wordcloud.png" class="link">下载</a></div>
      <div class="res-grid"><div class="img-wrap"><img :src="imgUrl" class="wc-img" /></div>
        <UiCard padding="md" shadow="sm" class="top-wrap"><h3 class="top-t">Top {{ result.top_words.length }} 词频</h3><ol class="top-list"><li v-for="(w, i) in result.top_words" :key="w.word"><span class="rk">{{ i + 1 }}</span><span class="wd">{{ w.word }}</span><span class="ct">{{ w.count }}</span></li></ol></UiCard>
      </div>
    </div>
    <UiEmpty v-else-if="!groups.length && !loading" icon="BarChart3" title="暂无词云消息记录" />
  </div>
</template>

<script setup lang="ts">
import { computed, ref } from 'vue'
import UiPageHeader from '../components/ui/UiPageHeader.vue'; import UiButton from '../components/ui/UiButton.vue'; import UiCard from '../components/ui/UiCard.vue'; import UiTag from '../components/ui/UiTag.vue'; import UiIcon from '../components/ui/UiIcon.vue'; import UiEmpty from '../components/ui/UiEmpty.vue'
import { listWordcloudGroups, renderWordcloud } from '../api/wordcloud'; import { toast } from '../toast'

const WINS = [{ k: 'today', l: '今日' }, { k: 'week', l: '近7天' }, { k: 'month', l: '近30天' }, { k: 'year', l: '近一年' }]
const WL: Record<string, string> = { today: '今日', week: '近7天', month: '近30天', year: '近一年' }

const groups = ref<any[]>([]); const loading = ref(false); const loadError = ref<string | null>(null); const groupId = ref(''); const windowKey = ref('today'); const rendering = ref(false); const renderError = ref<string | null>(null); const result = ref<any>(null)
const imgUrl = computed(() => result.value ? `data:image/png;base64,${result.value.image_base64}` : '')
const winLabel = computed(() => WL[windowKey.value] || windowKey.value)

function fmtBytes(n: number): string { if (n < 1024) return n + ' B'; if (n < 1024 * 1024) return (n / 1024).toFixed(1) + ' KB'; return (n / 1024 / 1024).toFixed(1) + ' MB' }
async function loadGroups() { loading.value = true; loadError.value = null; try { groups.value = (await listWordcloudGroups()).groups || [] } catch (e: unknown) { loadError.value = (e as Error).message } finally { loading.value = false } }
async function onRender() { if (!groupId.value) return; rendering.value = true; renderError.value = null; try { result.value = await renderWordcloud(groupId.value, windowKey.value) } catch (e: unknown) { result.value = null; renderError.value = ((e as any).data?.detail as string) || (e as Error).message; toast('生成失败', 'error') } finally { rendering.value = false } }
loadGroups()
</script>

<style scoped>
.error { color: var(--qq-danger); }
.controls { display: flex; align-items: flex-end; gap: var(--qq-gap-md); flex-wrap: wrap; margin-bottom: var(--qq-gap-sm); padding: var(--qq-gap-md); background: var(--qq-surface); border-radius: var(--qq-radius-card); box-shadow: var(--qq-shadow-card); }
.ctrl { display: flex; flex-direction: column; gap: var(--qq-gap-xs); font-size: var(--qq-text-xs); color: var(--qq-text-muted); }
.win-row { display: inline-flex; gap: 1px; }
.win-btn { padding: 6px 12px; border: none; background: var(--qq-surface-strong); color: var(--qq-text-muted); font-size: var(--qq-text-sm); font-family: var(--qq-font-base); cursor: pointer; transition: all var(--qq-transition-fast); }
.win-btn:first-child { border-radius: var(--qq-radius-sm) 0 0 var(--qq-radius-sm); }
.win-btn:last-child { border-radius: 0 var(--qq-radius-sm) var(--qq-radius-sm) 0; }
.win-btn.active { background: var(--qq-primary); color: #fff; }
.hint { display: inline-flex; align-items: center; gap: 6px; color: var(--qq-text-muted); font-size: var(--qq-text-xs); margin: var(--qq-gap-sm) 0 var(--qq-gap-md); }
.muted { color: var(--qq-text-muted); font-size: var(--qq-text-sm); }
.sum-row { display: flex; align-items: center; gap: var(--qq-gap-sm); margin-bottom: var(--qq-gap-md); flex-wrap: wrap; }
.link { margin-left: auto; color: var(--qq-primary); text-decoration: none; font-size: var(--qq-text-sm); }
.res-grid { display: grid; grid-template-columns: minmax(0, 2fr) minmax(240px, 1fr); gap: var(--qq-gap-md); align-items: start; }
.img-wrap { border-radius: var(--qq-radius-card); overflow: hidden; box-shadow: var(--qq-shadow-card); }
.wc-img { width: 100%; display: block; background: #fff; }
.top-wrap { max-height: 500px; overflow-y: auto; }
.top-t { margin: 0 0 var(--qq-gap-sm); font-size: var(--qq-text-base); color: var(--qq-text); }
.top-list { list-style: none; padding: 0; margin: 0; display: flex; flex-direction: column; gap: 2px; }
.top-list li { display: grid; grid-template-columns: 24px 1fr auto; align-items: center; gap: var(--qq-gap-sm); padding: 4px 6px; border-radius: var(--qq-radius-sm); font-size: var(--qq-text-sm); }
.top-list li:hover { background: var(--qq-surface-hover); }
.rk { color: var(--qq-text-muted); font-family: var(--qq-font-mono); font-size: var(--qq-text-xs); text-align: right; }
.wd { color: var(--qq-text); overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
.ct { color: var(--qq-text-muted); font-family: var(--qq-font-mono); font-size: var(--qq-text-xs); }
@media (max-width: 900px) { .res-grid { grid-template-columns: 1fr; } }
</style>
