<template>
  <div>
    <UiPageHeader title="限流实时状态" subtitle="内存状态，重启归零。scope=全局 的规则保护外部 API/共享资源；scope=按群 的规则每个群独立分桶"><template #actions><label class="auto"><input type="checkbox" v-model="autoRefresh" /><span>5s 刷新</span></label><UiButton icon="RefreshCw" :loading="loading" @click="load">刷新</UiButton></template></UiPageHeader>
    <p v-if="loadError" class="error">{{ loadError }}</p>
    <UiLoading v-if="loading && !rules.length" />
    <UiEmpty v-else-if="!rules.length" icon="Zap" title="无限流规则" />
    <div v-else class="rule-grid">
      <UiCard v-for="r in rules" :key="r.name" padding="md" shadow="sm">
        <div class="rule-head"><span class="rule-name">{{ r.name }}</span><div class="rule-tags"><UiTag size="sm" :variant="r.scope === 'global' ? 'warn' : 'info'">{{ r.scope === 'global' ? '全局' : '按群' }}</UiTag><span class="window">窗口 {{ r.window_seconds }}s · 上限 {{ r.global_limit }}/{{ r.user_limit }}</span></div></div>
        <div v-if="!r.buckets.length" class="empty"><span class="muted">当前窗口无命中</span></div>
        <div v-else class="buckets">
          <div v-for="b in r.buckets" :key="b.group_id || '__global__'" class="bucket">
            <div class="bucket-head"><span class="bucket-label">{{ bucketLabel(r, b) }}</span><span class="mono stat"><span :class="{ sat: b.global_used >= r.global_limit }">{{ b.global_used }}</span> / {{ r.global_limit }}</span></div>
            <div class="bar"><div class="bar-fill" :class="{ sat: b.global_used >= r.global_limit }" :style="{ width: pct(b.global_used, r.global_limit) + '%' }" /></div>
            <div v-if="b.top_users.length" class="top">
              <div class="top-head">活跃 {{ b.active_users }} 人</div>
              <div v-for="u in b.top_users" :key="u.user_id" class="top-row"><span class="mono">uid {{ u.user_id }}</span><div class="mini-bar"><div class="mini-fill" :class="{ sat: u.used >= r.user_limit }" :style="{ width: pct(u.used, r.user_limit) + '%' }" /></div><span class="mono used">{{ u.used }}/{{ r.user_limit }}</span></div>
            </div>
          </div>
        </div>
      </UiCard>
    </div>
  </div>
</template>

<script setup lang="ts">
import { onBeforeUnmount, ref, watch } from 'vue'
import UiPageHeader from '../components/ui/UiPageHeader.vue'; import UiButton from '../components/ui/UiButton.vue'; import UiCard from '../components/ui/UiCard.vue'; import UiTag from '../components/ui/UiTag.vue'; import UiLoading from '../components/ui/UiLoading.vue'; import UiEmpty from '../components/ui/UiEmpty.vue'
import { fetchRateLimit } from '../api/rateLimit'

const rules = ref<any[]>([]); const loading = ref(false); const loadError = ref<string | null>(null); const autoRefresh = ref(false); let timer: ReturnType<typeof setInterval> | null = null

function pct(u: number, l: number): number { if (!l) return 0; return Math.min(100, Math.round((u / l) * 100)) }
function bucketLabel(r: any, b: any): string { if (r.scope === 'global') return '全局桶'; if (!b.group_id) return '私聊/无群上下文'; return `群 ${b.group_id}` }

async function load() { loading.value = true; loadError.value = null; try { rules.value = (await fetchRateLimit()).rules || [] } catch (e: unknown) { loadError.value = (e as Error).message; if ((e as any)._isUnauthorized) stopTimer() } finally { loading.value = false } }
function startTimer() { stopTimer(); timer = setInterval(load, 5000) }
function stopTimer() { if (timer) { clearInterval(timer); timer = null } }
watch(autoRefresh, (on) => { if (on) startTimer(); else stopTimer() })
onBeforeUnmount(stopTimer)
load()
</script>

<style scoped>
.error { color: var(--qq-danger); }
.auto { display: inline-flex; align-items: center; gap: 6px; color: var(--qq-text-muted); font-size: var(--qq-text-sm); cursor: pointer; }
.rule-grid { display: grid; grid-template-columns: repeat(auto-fill, minmax(340px, 1fr)); gap: var(--qq-gap-md); }
.rule-head { display: flex; align-items: center; justify-content: space-between; gap: var(--qq-gap-sm); margin-bottom: var(--qq-gap-sm); flex-wrap: wrap; }
.rule-name { font-weight: 500; color: var(--qq-text); font-family: var(--qq-font-mono); }
.rule-tags { display: flex; align-items: center; gap: var(--qq-gap-xs); }
.window { font-size: var(--qq-text-xs); color: var(--qq-text-muted); }
.empty { padding: var(--qq-gap-sm) 0; }
.muted { color: var(--qq-text-muted); font-size: var(--qq-text-xs); }
.mono { font-family: var(--qq-font-mono); }
.buckets { display: flex; flex-direction: column; gap: var(--qq-gap-sm); }
.bucket { padding: var(--qq-gap-sm); border-radius: var(--qq-radius-sm); background: var(--qq-surface-strong); }
.bucket-head { display: flex; justify-content: space-between; align-items: center; font-size: var(--qq-text-xs); margin-bottom: 4px; }
.bucket-label { color: var(--qq-text); font-weight: 500; }
.stat { color: var(--qq-text); font-size: var(--qq-text-xs); }
.stat .sat { color: var(--qq-danger); font-weight: 600; }
.bar { height: 6px; background: var(--qq-surface); border-radius: var(--qq-radius-full); overflow: hidden; }
.bar-fill { height: 100%; background: var(--qq-primary); transition: width 0.3s var(--qq-ease-out); }
.bar-fill.sat { background: var(--qq-danger); }
.top { margin-top: var(--qq-gap-xs); padding-top: var(--qq-gap-xs); border-top: 1px solid var(--qq-border); }
.top-head { font-size: var(--qq-text-xs); color: var(--qq-text-muted); margin-bottom: 3px; }
.top-row { display: grid; grid-template-columns: minmax(100px, auto) 1fr auto; align-items: center; gap: var(--qq-gap-sm); font-size: var(--qq-text-xs); color: var(--qq-text-muted); }
.mini-bar { height: 4px; background: var(--qq-surface); border-radius: var(--qq-radius-full); overflow: hidden; }
.mini-fill { height: 100%; background: var(--qq-primary); transition: width 0.3s var(--qq-ease-out); }
.mini-fill.sat { background: var(--qq-danger); }
</style>
