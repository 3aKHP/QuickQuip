<template>
  <div>
    <UiPageHeader title="金币管理" subtitle="查看各群金币排行、账户详情，手动调整余额" />

    <p v-if="loadError" class="error">{{ loadError }}</p>
    <UiLoading v-else-if="loading" />

    <!-- Group selector -->
    <UiCard padding="md" shadow="sm" class="toolbar-card">
      <div class="toolbar-inner">
        <label>群组
          <select v-model="selectedGroup" @change="selectGroup">
            <option value="">-- 选择群 --</option>
            <option v-for="g in groups" :key="g.group_id" :value="g.group_id">
              {{ g.group_id }}（{{ g.user_count }} 人 / {{ g.total_gold.toLocaleString() }} 💰）
            </option>
          </select>
        </label>
        <UiButton :loading="loading" icon="RefreshCw" @click="loadGroups">刷新</UiButton>
      </div>
    </UiCard>

    <UiEmpty v-if="!loading && selectedGroup && !loadError && !rankings.length && !acctSearched"
      icon="Coins" title="暂无数据" />

    <!-- Rankings -->
    <UiCard v-if="selectedGroup" padding="md" shadow="sm" class="section-card">
      <h3 class="section-title">🏆 金币排行 TOP 20</h3>
      <UiLoading v-if="rankLoading" />
      <UiEmpty v-else-if="!rankings.length" icon="BarChart3" title="暂无排行数据" />
      <table v-else class="data-table">
        <thead>
          <tr><th class="num">#</th><th>QQ</th><th class="num">金币</th><th class="num">好感度</th><th class="num">连击</th></tr>
        </thead>
        <tbody>
          <tr v-for="(r, i) in rankings" :key="r.user_id">
            <td class="num">{{ i + 1 }}</td>
            <td><a href="#" @click.prevent="lookupUser(r.user_id)"><code>{{ r.user_id }}</code></a></td>
            <td class="num">{{ r.gold.toLocaleString() }}</td>
            <td class="num">{{ r.affection }}</td>
            <td class="num">{{ r.sign_streak }} 天</td>
          </tr>
        </tbody>
      </table>
    </UiCard>

    <!-- Account lookup & adjust -->
    <UiCard v-if="selectedGroup" padding="md" shadow="sm" class="section-card">
      <h3 class="section-title">🔍 账户查询与调整</h3>
      <div class="toolbar-inner">
        <input v-model="searchUid" placeholder="QQ 号" style="width:160px" @keyup.enter="searchAccount" />
        <UiButton icon="Search" :loading="acctLoading" @click="searchAccount">查询</UiButton>
      </div>

      <div v-if="account" class="acct-detail">
        <div class="acct-info">
          <span class="acct-label">QQ</span><code>{{ account.user_id }}</code>
          <span class="acct-label">金币</span><strong>{{ account.gold.toLocaleString() }}</strong>
          <span class="acct-label">好感</span><span>{{ account.affection }}</span>
          <span class="acct-label">签到连击</span><span>{{ account.sign_streak }} 天</span>
          <span class="acct-label">最后签到</span><span class="muted">{{ account.last_sign_date || '从未签到' }}</span>
        </div>
        <div class="adjust-row">
          <input v-model.number="adjustAmount" type="number" placeholder="+/- 金额" class="adjust-input" />
          <input v-model="adjustReason" placeholder="原因（可选）" class="reason-input" maxlength="200" />
          <UiButton variant="primary" icon="Send" :loading="adjLoading" @click="doAdjust">调整</UiButton>
        </div>
        <p v-if="adjustResult" class="adjust-result" :class="{ 'adjust-err': adjustError }">{{ adjustResult }}</p>
      </div>
      <p v-else-if="acctSearched" class="muted" style="margin-top:12px">未找到该账户</p>
    </UiCard>
  </div>
</template>

<script setup lang="ts">
import { onMounted, ref } from 'vue'
import UiPageHeader from '../components/ui/UiPageHeader.vue'
import UiCard from '../components/ui/UiCard.vue'
import UiButton from '../components/ui/UiButton.vue'
import UiLoading from '../components/ui/UiLoading.vue'
import UiEmpty from '../components/ui/UiEmpty.vue'
import { listGroups, getRankings, getAccount, adjustGold } from '../api/game-economy'
import { toast } from '../toast'

const loading = ref(false)
const loadError = ref<string | null>(null)
const groups = ref<any[]>([])
const selectedGroup = ref('')

const rankLoading = ref(false)
const rankings = ref<any[]>([])

const searchUid = ref('')
const acctLoading = ref(false)
const acctSearched = ref(false)
const account = ref<any>(null)

const adjustAmount = ref<number | null>(null)
const adjustReason = ref('')
const adjLoading = ref(false)
const adjustResult = ref('')
const adjustError = ref(false)

onMounted(() => { loadGroups() })

async function loadGroups() {
  loading.value = true; loadError.value = null
  try { groups.value = (await listGroups()).groups || [] }
  catch (e: any) { loadError.value = e.message || String(e); toast(loadError.value!, 'error') }
  finally { loading.value = false }
}

async function selectGroup() {
  if (!selectedGroup.value) return
  rankLoading.value = true
  account.value = null; acctSearched.value = false; adjustResult.value = ''
  try { rankings.value = (await getRankings(selectedGroup.value)).rankings || [] }
  catch (e: any) { loadError.value = e.message || String(e) }
  finally { rankLoading.value = false }
}

function lookupUser(uid: string) {
  searchUid.value = uid
  searchAccount()
}

async function searchAccount() {
  if (!searchUid.value.trim() || !selectedGroup.value) return
  acctLoading.value = true; acctSearched.value = true; account.value = null
  try { account.value = await getAccount(selectedGroup.value, searchUid.value.trim()) }
  catch { account.value = null }
  finally { acctLoading.value = false }
}

async function doAdjust() {
  if (adjustAmount.value == null || adjustAmount.value === 0 || !account.value) return
  adjLoading.value = true; adjustResult.value = ''; adjustError.value = false
  try {
    const data = await adjustGold(selectedGroup.value, account.value.user_id, adjustAmount.value, adjustReason.value)
    adjustResult.value = `调整成功，新余额 ${data.new_balance.toLocaleString()}`
    account.value.gold = data.new_balance
    adjustAmount.value = null; adjustReason.value = ''
    toast('金币调整成功')
  } catch (e: any) {
    adjustResult.value = `调整失败：${e.message || e}`
    adjustError.value = true
    toast(adjustResult.value, 'error')
  } finally { adjLoading.value = false }
}
</script>

<style scoped>
.error { color: var(--qq-danger); }
.muted { color: var(--qq-text-muted); font-size: var(--qq-text-sm); }

.toolbar-card { margin-bottom: var(--qq-gap-md); }
.section-card { margin-bottom: var(--qq-gap-md); }

.toolbar-inner {
  display: flex; align-items: center; gap: var(--qq-gap-md); flex-wrap: wrap;
}
.toolbar-inner label {
  display: flex; align-items: center; gap: var(--qq-gap-xs);
  color: var(--qq-text-muted); font-size: var(--qq-text-sm);
}
.toolbar-inner select,
.toolbar-inner input {
  background: var(--qq-surface-strong);
  border: 1px solid var(--qq-border);
  border-radius: var(--qq-radius-sm);
  color: var(--qq-text);
  padding: 5px 10px;
  font-size: var(--qq-text-base);
  outline: none;
}
.toolbar-inner select:focus,
.toolbar-inner input:focus {
  border-color: var(--qq-accent);
  box-shadow: 0 0 0 3px var(--qq-accent-soft);
}

.section-title { margin: 0 0 var(--qq-gap-md) 0; font-size: var(--qq-text-base); color: var(--qq-text); }

.data-table { width: 100%; border-collapse: collapse; font-size: var(--qq-text-sm); }
.data-table th { text-align: left; padding: 6px 10px; border-bottom: 2px solid var(--qq-border); color: var(--qq-text-muted); font-weight: 600; }
.data-table td { padding: 6px 10px; border-bottom: 1px solid var(--qq-border); }
.data-table .num { text-align: right; font-variant-numeric: tabular-nums; }
.data-table code { font-family: var(--qq-font-mono); color: var(--qq-accent); }

.acct-detail { margin-top: var(--qq-gap-md); }
.acct-info {
  display: flex; align-items: center; gap: var(--qq-gap-md); flex-wrap: wrap;
  padding-bottom: var(--qq-gap-md); border-bottom: 1px solid var(--qq-border);
  margin-bottom: var(--qq-gap-md);
}
.acct-label { color: var(--qq-text-muted); font-size: var(--qq-text-xs); text-transform: uppercase; }
.acct-info strong { color: var(--qq-accent); }

.adjust-row { display: flex; gap: var(--qq-gap-sm); align-items: center; }
.adjust-input { width: 110px; }
.reason-input { flex: 1; }
.adjust-row input {
  background: var(--qq-surface-strong);
  border: 1px solid var(--qq-border);
  border-radius: var(--qq-radius-sm);
  color: var(--qq-text);
  padding: 5px 10px;
  font-size: var(--qq-text-sm);
  outline: none;
}
.adjust-row input:focus {
  border-color: var(--qq-accent);
  box-shadow: 0 0 0 3px var(--qq-accent-soft);
}
.adjust-result { margin-top: var(--qq-gap-sm); font-size: var(--qq-text-sm); color: var(--qq-accent); }
.adjust-err { color: var(--qq-danger); }
</style>
