<template>
  <div>
    <UiPageHeader title="金币管理" subtitle="查看各群金币排行、账户详情，手动调整余额" />
    <p v-if="loadError" class="error">{{ loadError }}</p>
    <UiLoading v-else-if="loading" />
    <div class="toolbar"><label>群组<select v-model="selectedGroup" @change="selectGroup"><option value="">-- 选择群 --</option><option v-for="g in groups" :key="g.group_id" :value="g.group_id">{{ g.group_id }}（{{ g.user_count }} 人 / {{ g.total_gold.toLocaleString() }} 💰）</option></select></label><UiButton :loading="loading" icon="RefreshCw" @click="loadGroups">刷新</UiButton></div>
    <UiEmpty v-if="!loading && selectedGroup && !loadError && !rankings.length && !acctSearched" icon="Coins" title="暂无数据" />

    <UiCard v-if="selectedGroup" padding="md" shadow="sm" class="section">
      <h3 class="st">金币排行 TOP 20</h3>
      <UiLoading v-if="rankLoading" />
      <UiEmpty v-else-if="!rankings.length" icon="BarChart3" title="暂无排行数据" />
      <table v-else><thead><tr><th class="num">#</th><th>QQ</th><th class="num">金币</th><th class="num">好感度</th><th class="num">连击</th></tr></thead><tbody><tr v-for="(r, i) in rankings" :key="r.user_id"><td class="num">{{ i + 1 }}</td><td><a href="#" @click.prevent="lookupUser(r.user_id)" class="acct-link">{{ r.user_id }}</a></td><td class="num">{{ r.gold.toLocaleString() }}</td><td class="num">{{ r.affection }}</td><td class="num">{{ r.sign_streak }} 天</td></tr></tbody></table>
    </UiCard>

    <UiCard v-if="selectedGroup" padding="md" shadow="sm" class="section">
      <h3 class="st">账户查询与调整</h3>
      <div class="lookup"><input v-model="searchUid" placeholder="QQ 号" style="width:160px" @keyup.enter="searchAccount" /><UiButton icon="Search" :loading="acctLoading" @click="searchAccount">查询</UiButton></div>
      <div v-if="account" class="acct">
        <div class="acct-info"><span class="al">QQ</span><span class="mono">{{ account.user_id }}</span><span class="al">金币</span><strong>{{ account.gold.toLocaleString() }}</strong><span class="al">好感</span><span>{{ account.affection }}</span><span class="al">签到</span><span>{{ account.sign_streak }} 天</span><span class="al">最后签到</span><span class="muted">{{ account.last_sign_date || '从未签到' }}</span></div>
        <div class="adj-row"><input v-model.number="adjustAmount" type="number" placeholder="+/- 金额" class="adj-amt" /><input v-model="adjustReason" placeholder="原因（可选）" class="adj-reason" maxlength="200" /><UiButton variant="primary" icon="Send" :loading="adjLoading" @click="doAdjust">调整</UiButton></div>
        <p v-if="adjustResult" class="adj-res" :class="{ 'adj-err': adjustError }">{{ adjustResult }}</p>
      </div>
      <p v-else-if="acctSearched" class="muted" style="margin-top:12px">未找到该账户</p>
    </UiCard>
  </div>
</template>

<script setup lang="ts">
import { onMounted, ref } from 'vue'
import UiPageHeader from '../components/ui/UiPageHeader.vue'; import UiCard from '../components/ui/UiCard.vue'; import UiButton from '../components/ui/UiButton.vue'; import UiLoading from '../components/ui/UiLoading.vue'; import UiEmpty from '../components/ui/UiEmpty.vue'
import { listGroups, getRankings, getAccount, adjustGold } from '../api/game-economy'; import { toast } from '../toast'

const loading = ref(false); const loadError = ref<string | null>(null); const groups = ref<any[]>([]); const selectedGroup = ref(''); const rankLoading = ref(false); const rankings = ref<any[]>([])
const searchUid = ref(''); const acctLoading = ref(false); const acctSearched = ref(false); const account = ref<any>(null)
const adjustAmount = ref<number | null>(null); const adjustReason = ref(''); const adjLoading = ref(false); const adjustResult = ref(''); const adjustError = ref(false)

onMounted(() => loadGroups())
async function loadGroups() { loading.value = true; loadError.value = null; try { groups.value = (await listGroups()).groups || [] } catch (e: any) { loadError.value = e.message || String(e) } finally { loading.value = false } }
async function selectGroup() { if (!selectedGroup.value) return; rankLoading.value = true; account.value = null; acctSearched.value = false; adjustResult.value = ''; try { rankings.value = (await getRankings(selectedGroup.value)).rankings || [] } catch (e: any) { loadError.value = e.message || String(e) } finally { rankLoading.value = false } }
function lookupUser(uid: string) { searchUid.value = uid; searchAccount() }
async function searchAccount() { if (!searchUid.value.trim() || !selectedGroup.value) return; acctLoading.value = true; acctSearched.value = true; account.value = null; try { account.value = await getAccount(selectedGroup.value, searchUid.value.trim()) } catch { account.value = null } finally { acctLoading.value = false } }
async function doAdjust() { if (adjustAmount.value == null || adjustAmount.value === 0 || !account.value) return; adjLoading.value = true; adjustResult.value = ''; adjustError.value = false; try { const data = await adjustGold(selectedGroup.value, account.value.user_id, adjustAmount.value, adjustReason.value); adjustResult.value = `调整成功，新余额 ${data.new_balance.toLocaleString()}`; account.value.gold = data.new_balance; adjustAmount.value = null; adjustReason.value = ''; toast('调整成功') } catch (e: any) { adjustResult.value = `调整失败：${e.message || e}`; adjustError.value = true; toast(adjustResult.value, 'error') } finally { adjLoading.value = false } }
</script>

<style scoped>
.error { color: var(--qq-danger); }
.muted { color: var(--qq-text-muted); font-size: var(--qq-text-sm); }
.mono { font-family: var(--qq-font-mono); }
.toolbar { display: flex; align-items: center; gap: var(--qq-gap-md); flex-wrap: wrap; margin-bottom: var(--qq-gap-lg); padding: var(--qq-gap-sm) var(--qq-gap-md); background: var(--qq-surface); border-radius: var(--qq-radius-card); box-shadow: var(--qq-shadow-card); }
.toolbar label { display: flex; align-items: center; gap: var(--qq-gap-xs); color: var(--qq-text-muted); font-size: var(--qq-text-sm); }
.section { margin-bottom: var(--qq-gap-md); }
.st { margin: 0 0 var(--qq-gap-md) 0; font-size: var(--qq-text-base); color: var(--qq-text); }
.num { text-align: right; font-variant-numeric: tabular-nums; }
.acct-link { color: var(--qq-primary); text-decoration: none; font-family: var(--qq-font-mono); }
.acct-link:hover { text-decoration: underline; }
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
