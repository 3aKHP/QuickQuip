<template>
  <div>
    <UiPageHeader title="牛牛大作战" subtitle="查看全局排行、用户详情，手动修正异常数据" />
    <p v-if="loadError" class="error">{{ loadError }}</p>
    <UiCard padding="md" shadow="sm" class="section">
      <div class="toolbar"><h3 class="st">排行</h3><div class="tab-row"><button :class="{ active: rankType === 'length' }" @click="switchRank('length')">长度</button><button :class="{ active: rankType === 'depth' }" @click="switchRank('depth')">深度</button></div><span class="muted" style="margin-left:auto">共 {{ totalUsers.toLocaleString() }} 用户</span><UiButton size="sm" icon="RefreshCw" :loading="rankLoading" @click="loadRankings" /></div>
      <UiLoading v-if="rankLoading && !rankings.length" />
      <UiEmpty v-else-if="!rankings.length" icon="BarChart3" :title="rankType === 'length' ? '暂无长度数据' : '暂无深度数据'" />
      <table v-else><thead><tr><th class="num">#</th><th>QQ</th><th class="num">{{ rankType === 'length' ? '长度 (cm)' : '深度 (cm)' }}</th></tr></thead><tbody><tr v-for="(r, i) in rankings" :key="r.uid"><td class="num">{{ i + 1 }}</td><td><a href="#" @click.prevent="selectUser(r.uid)" class="link">{{ r.uid }}</a></td><td class="num">{{ r.length }}</td></tr></tbody></table>
    </UiCard>

    <UiCard padding="md" shadow="sm" class="section">
      <h3 class="st">用户查询</h3>
      <div class="lookup"><input v-model="searchUid" placeholder="QQ 号" style="width:160px" @keyup.enter="searchUser" /><UiButton icon="Search" :loading="userLoading" @click="searchUser">查询</UiButton></div>
      <div v-if="userDetail" class="user-detail">
        <div class="acct-info"><span class="al">QQ</span><span class="mono">{{ userDetail.uid }}</span><span class="al">长度</span><strong>{{ userDetail.length }} cm</strong><span v-if="userDetail.rank > 0" class="al">排名</span><span>第 {{ userDetail.rank }} 名</span></div>
        <div class="adj-row"><input v-model.number="adjustLengthVal" type="number" step="0.01" placeholder="新长度" class="adj-amt" /><input v-model="adjustReason" placeholder="原因（可选）" class="adj-reason" maxlength="200" /><UiButton variant="primary" icon="Send" :loading="adjLoading" @click="doAdjust">修正</UiButton></div>
        <p v-if="adjustResult" class="adj-res" :class="{ 'adj-err': adjustError }">{{ adjustResult }}</p>
        <h4 class="st" style="margin-top:var(--qq-gap-md)">操作记录（最近 30 条）</h4>
        <table v-if="userDetail.records.length"><thead><tr><th>动作</th><th class="num">前</th><th class="num">后</th><th class="num">差值</th><th>时间</th></tr></thead><tbody><tr v-for="r in userDetail.records" :key="r.created_at"><td><UiTag size="sm" :variant="tv(r.action)">{{ al(r.action) }}</UiTag></td><td class="num">{{ r.origin_length }}</td><td class="num">{{ r.new_length }}</td><td class="num" :class="{ pos: r.diff > 0, neg: r.diff < 0 }">{{ r.diff > 0 ? '+' : '' }}{{ r.diff }}</td><td class="time">{{ r.created_at?.slice(0, 16).replace('T', ' ') }}</td></tr></tbody></table>
        <UiEmpty v-else icon="FileText" title="暂无记录" />
      </div>
      <p v-else-if="userSearched" class="muted" style="margin-top:12px">未找到该用户</p>
    </UiCard>
  </div>
</template>

<script setup lang="ts">
import { onMounted, ref } from 'vue'
import UiPageHeader from '../components/ui/UiPageHeader.vue'; import UiCard from '../components/ui/UiCard.vue'; import UiButton from '../components/ui/UiButton.vue'; import UiTag from '../components/ui/UiTag.vue'; import UiLoading from '../components/ui/UiLoading.vue'; import UiEmpty from '../components/ui/UiEmpty.vue'
import { getRankings, getUser, adjustLength } from '../api/niuniu'; import { toast } from '../toast'

const loadError = ref<string | null>(null); const rankType = ref('length'); const rankLoading = ref(false); const rankings = ref<any[]>([]); const totalUsers = ref(0)
const searchUid = ref(''); const userLoading = ref(false); const userSearched = ref(false); const userDetail = ref<any>(null)
const adjustLengthVal = ref<number | null>(null); const adjustReason = ref(''); const adjLoading = ref(false); const adjustResult = ref(''); const adjustError = ref(false)

const AL: Record<string, string> = { register: '注册', unsubscribe: '注销', gluing: '打胶', fencing: '击剑', fenced: '被击', admin_adjust: '修正' }
function al(a: string) { return AL[a] || a }
function tv(a: string): string { return ({ fencing: 'success', fenced: 'danger', gluing: 'info', admin_adjust: 'warn' } as any)[a] || '' }

onMounted(() => loadRankings())
async function loadRankings() { rankLoading.value = true; try { const data = await getRankings(rankType.value); rankings.value = data.rankings || []; totalUsers.value = data.total_users || 0 } catch (e: any) { loadError.value = e.message || String(e) } finally { rankLoading.value = false } }
async function switchRank(type: string) { rankType.value = type; await loadRankings() }
async function selectUser(uid: string) { searchUid.value = uid; await searchUser() }
async function searchUser() { if (!searchUid.value.trim()) return; userLoading.value = true; userSearched.value = true; userDetail.value = null; try { userDetail.value = await getUser(searchUid.value.trim()) } catch { userDetail.value = null } finally { userLoading.value = false } }
async function doAdjust() { if (adjustLengthVal.value == null || !userDetail.value) return; adjLoading.value = true; adjustResult.value = ''; adjustError.value = false; try { const data = await adjustLength(userDetail.value.uid, adjustLengthVal.value, adjustReason.value); adjustResult.value = `修正成功：${data.old_length} → ${data.new_length}`; userDetail.value.length = data.new_length; adjustLengthVal.value = null; adjustReason.value = ''; toast('修正成功') } catch (e: any) { adjustResult.value = `修正失败：${e.message || e}`; adjustError.value = true; toast(adjustResult.value, 'error') } finally { adjLoading.value = false } }
</script>

<style scoped>
.error { color: var(--qq-danger); }
.muted { color: var(--qq-text-muted); font-size: var(--qq-text-sm); }
.mono { font-family: var(--qq-font-mono); }
.section { margin-bottom: var(--qq-gap-md); }
.toolbar { display: flex; align-items: center; gap: var(--qq-gap-md); flex-wrap: wrap; }
.st { margin: 0; font-size: var(--qq-text-base); color: var(--qq-text); }
.tab-row { display: flex; }
.tab-row button { padding: 4px 16px; border: none; background: var(--qq-surface-strong); color: var(--qq-text-muted); font-size: var(--qq-text-sm); font-family: var(--qq-font-base); cursor: pointer; }
.tab-row button:first-child { border-radius: var(--qq-radius-sm) 0 0 var(--qq-radius-sm); }
.tab-row button:last-child { border-radius: 0 var(--qq-radius-sm) var(--qq-radius-sm) 0; }
.tab-row button.active { background: var(--qq-primary); color: #fff; }
.num { text-align: right; font-variant-numeric: tabular-nums; }
.link { color: var(--qq-primary); text-decoration: none; font-family: var(--qq-font-mono); }
.link:hover { text-decoration: underline; }
.time { font-size: var(--qq-text-xs); color: var(--qq-text-muted); }
.pos { color: var(--qq-success); font-weight: 600; }
.neg { color: var(--qq-danger); font-weight: 600; }
.lookup { display: flex; align-items: center; gap: var(--qq-gap-md); margin-bottom: var(--qq-gap-md); }
.acct-info { display: flex; align-items: center; gap: var(--qq-gap-md); flex-wrap: wrap; padding-bottom: var(--qq-gap-md); border-bottom: 1px solid var(--qq-border); margin-bottom: var(--qq-gap-md); }
.al { color: var(--qq-text-muted); font-size: var(--qq-text-xs); }
.acct-info strong { color: var(--qq-primary); }
.adj-row { display: flex; gap: var(--qq-gap-sm); align-items: center; }
.adj-amt { width: 110px; }
.adj-reason { flex: 1; }
.adj-res { margin-top: var(--qq-gap-sm); font-size: var(--qq-text-sm); color: var(--qq-primary); }
.adj-err { color: var(--qq-danger); }
</style>
