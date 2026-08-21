<template>
  <div class="detail-overlay" @click.self="emit('close')">
    <UiCard padding="lg" shadow="lg" class="detail-card">
      <div class="detail-head">
        <span class="mono">#{{ detail.tid }} · {{ detail.forum_keyword }}吧</span>
        <button class="detail-close" @click="emit('close')"><UiIcon name="X" :size="18" /></button>
      </div>
      <h3 class="detail-title">{{ detail.title }}</h3>
      <div class="detail-meta">
        <span v-if="detail.author_name">{{ detail.author_name }}</span>
        <span>· {{ formatTime(detail.last_seen_at) }}</span>
        <a :href="detail.thread_url" target="_blank" rel="noreferrer" class="detail-link">在贴吧打开</a>
      </div>
      <div class="detail-content">{{ detail.main_post_text || '（正文为空）' }}</div>
      <div v-if="detail.image_urls && detail.image_urls.length" class="detail-images">
        <img v-for="(src, i) in detail.image_urls" :key="i" :src="tiebaImgProxyUrl(src)" loading="lazy" />
      </div>
    </UiCard>
  </div>
</template>

<script setup lang="ts">
import UiCard from '../ui/UiCard.vue'
import UiIcon from '../ui/UiIcon.vue'
import { tiebaImgProxyUrl } from '../../api/tieba'
import type { TiebaThread } from '../../api/tieba'

defineProps<{
  detail: TiebaThread
}>()

const emit = defineEmits<{
  close: []
}>()

function formatTime(ts: number): string {
  if (!ts) return ''
  const d = new Date(ts * 1000)
  if (Number.isNaN(d.getTime())) return ''
  const pad = (n: number) => String(n).padStart(2, '0')
  return `${d.getFullYear()}-${pad(d.getMonth() + 1)}-${pad(d.getDate())} ${pad(d.getHours())}:${pad(d.getMinutes())}`
}
</script>

<style scoped>
.mono { font-family: var(--qq-font-mono); }

.detail-overlay {
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

.detail-card {
  width: min(720px, 100%);
  max-height: calc(100vh - 64px);
  overflow-y: auto;
}

.detail-head {
  display: flex;
  align-items: center;
  justify-content: space-between;
  font-size: var(--qq-text-xs);
  color: var(--qq-text-muted);
  margin-bottom: var(--qq-gap-sm);
}

.detail-close {
  background: transparent;
  border: none;
  color: var(--qq-text-muted);
  cursor: pointer;
  padding: 4px;
  border-radius: var(--qq-radius-sm);
}

.detail-close:hover {
  color: var(--qq-text);
  background: var(--qq-surface-elevated);
}

.detail-title {
  font-size: var(--qq-text-lg);
  color: var(--qq-text);
  margin: 0 0 var(--qq-gap-sm) 0;
}

.detail-meta {
  font-size: var(--qq-text-xs);
  color: var(--qq-text-muted);
  display: flex;
  gap: 6px;
  margin-bottom: var(--qq-gap-md);
}

.detail-link {
  color: var(--qq-primary);
  text-decoration: none;
}

.detail-link:hover { text-decoration: underline; }

.detail-content {
  font-size: var(--qq-text-sm);
  line-height: 1.7;
  color: var(--qq-text);
  white-space: pre-wrap;
  word-break: break-word;
  padding: var(--qq-gap-sm);
  background: var(--qq-surface-strong);
  border-radius: var(--qq-radius-sm);
  margin-bottom: var(--qq-gap-md);
}

.detail-images {
  display: grid;
  grid-template-columns: repeat(auto-fill, minmax(160px, 1fr));
  gap: var(--qq-gap-xs);
}

.detail-images img {
  width: 100%;
  border-radius: var(--qq-radius-sm);
  background: var(--qq-surface-strong);
}
</style>
