<template>
  <div>
    <UiPageHeader title="金币管理" subtitle="查看各群金币排行、账户详情，手动调整余额" />
    <UiStatStrip v-if="groups.length" :items="stripItems" />
    <div v-if="loadError" class="soft-note soft-note--danger ge-banner" role="alert">{{ loadError }}</div>
    <UiLoading v-if="loading && !groups.length" />
    <div class="toolbar">
      <label>
        群组
        <select v-model="selectedGroup" @change="selectGroup">
          <option value="">-- 选择群 --</option>
          <option v-for="g in groups" :key="g.group_id" :value="g.group_id">
            {{ g.group_id }}（{{ g.user_count }} 人 / {{ g.total_gold.toLocaleString() }} 💰）
          </option>
        </select>
      </label>
      <UiButton :loading="loading" icon="RefreshCw" @click="loadGroups">刷新</UiButton>
    </div>
    <UiEmpty v-if="!loading && !selectedGroup" icon="Coins" title="选择一个群组查看金币经济" description="上方下拉框列出所有开启金币系统的群组，含用户数与总金币。" />

    <UiCard v-if="selectedGroup" padding="md" shadow="sm" class="section">
      <h3 class="st section-title">金币排行 TOP 20</h3>
      <UiLoading v-if="rankLoading" />
      <UiEmpty v-else-if="!rankings.length" icon="BarChart3" title="暂无排行数据" />
      <div v-else class="table-scroll">
        <table>
          <thead>
            <tr>
              <th class="num">#</th>
              <th>QQ</th>
              <th class="num">金币<UiInfoTip text="群游戏经济的虚拟货币：每日签到获得（基础值 + 连击加成，见 config/games.toml [economy]），也会随群内游戏输赢变动；排行按金币降序取前 20。" /></th>
              <th class="num">好感度<UiInfoTip text="签到累积的好感成长值。" /></th>
              <th class="num">连击<UiInfoTip text="连续签到天数，中断后重新计数。" /></th>
            </tr>
          </thead>
          <tbody>
            <tr v-for="(r, i) in rankings" :key="r.user_id">
              <td class="num">{{ i + 1 }}</td>
              <td><a href="#" class="acct-link" @click.prevent="lookupUser(r.user_id)">{{ r.user_id }}</a></td>
              <td class="num">{{ r.gold.toLocaleString() }}</td>
              <td class="num">{{ r.affection }}</td>
              <td class="num">{{ r.sign_streak }} 天</td>
            </tr>
          </tbody>
        </table>
      </div>
    </UiCard>

    <UiCard v-if="selectedGroup" padding="md" shadow="sm" class="section">
      <h3 class="st section-title">账户查询与调整<UiInfoTip text="正数加金币、负数扣减（余额不足会失败），单次限 ±1,000,000；每次调整连同填写的「原因」都会记入审计日志。" /></h3>
      <div class="lookup">
        <input v-model="searchUid" placeholder="QQ 号" style="width:160px" @keyup.enter="searchAccount" />
        <UiButton icon="Search" :loading="acctLoading" @click="searchAccount">查询</UiButton>
      </div>
      <div v-if="account && account.group_id === selectedGroup" class="acct">
        <div class="acct-info">
          <span class="al">QQ</span><span class="mono">{{ account.user_id }}</span>
          <span class="al">金币</span><strong>{{ account.gold.toLocaleString() }}</strong>
          <span class="al">好感</span><span>{{ account.affection }}</span>
          <span class="al">签到</span><span>{{ account.sign_streak }} 天</span>
          <span class="al">最后签到</span><span class="muted">{{ account.last_sign_date || '从未签到' }}</span>
        </div>
        <div class="adj-row">
          <input v-model.number="adjustAmount" type="number" step="1" placeholder="+/- 整数金额" class="adj-amt" />
          <input v-model="adjustReason" placeholder="原因（可选）" class="adj-reason" maxlength="200" />
          <UiButton variant="primary" icon="Send" :loading="adjLoading" @click="doAdjust">调整</UiButton>
        </div>
        <p v-if="adjustResult" class="adj-res" :class="{ 'adj-err': adjustError }">{{ adjustResult }}</p>
      </div>
      <p v-else-if="acctError" class="error" style="margin-top:12px">{{ acctError }}</p>
      <p v-else-if="acctSearched && !acctLoading" class="muted" style="margin-top:12px">未找到该账户</p>
    </UiCard>
  </div>
</template>

<script setup lang="ts">
import { computed, onMounted, ref } from 'vue'
import UiPageHeader from '../components/ui/UiPageHeader.vue'
import UiCard from '../components/ui/UiCard.vue'
import UiButton from '../components/ui/UiButton.vue'
import UiLoading from '../components/ui/UiLoading.vue'
import UiEmpty from '../components/ui/UiEmpty.vue'
import UiStatStrip from '../components/ui/UiStatStrip.vue'
import UiInfoTip from '../components/ui/UiInfoTip.vue'
import { listGroups, getRankings, getAccount, adjustGold } from '../api/game-economy'
import { toast } from '../toast'

const loading = ref(false)
const loadError = ref<string | null>(null)
const groups = ref<any[]>([])
const selectedGroup = ref('')
const rankLoading = ref(false)
const rankings = ref<any[]>([])

const stripItems = computed(() => [
  { label: '群组数', value: groups.value.length, icon: 'Users' },
  { label: '金币用户', value: groups.value.reduce((n, g) => n + (g.user_count || 0), 0), icon: 'Coins' },
  { label: '总金币', value: groups.value.reduce((n, g) => n + (g.total_gold || 0), 0), icon: 'Gauge' },
])

const searchUid = ref('')
const acctLoading = ref(false)
const acctSearched = ref(false)
const acctError = ref<string | null>(null)
const account = ref<any>(null)
const adjustAmount = ref<number | string | null>(null)
const adjustReason = ref('')
const adjLoading = ref(false)
const adjustResult = ref('')
const adjustError = ref(false)

let groupReqSeq = 0
let acctReqSeq = 0

onMounted(() => { loadGroups() })

async function loadGroups() {
  loading.value = true
  loadError.value = null
  try {
    groups.value = (await listGroups()).groups || []
    if (selectedGroup.value) {
      await fetchRankingsFor(selectedGroup.value)
    }
  } catch (e: unknown) {
    loadError.value = (e as Error).message || String(e)
  } finally {
    loading.value = false
  }
}

async function fetchRankingsFor(gid: string) {
  const seq = ++groupReqSeq
  rankLoading.value = true
  try {
    const res = await getRankings(gid)
    if (seq !== groupReqSeq || selectedGroup.value !== gid) return
    rankings.value = res.rankings || []
  } catch (e: unknown) {
    if (seq !== groupReqSeq || selectedGroup.value !== gid) return
    loadError.value = (e as Error).message || String(e)
  } finally {
    if (seq === groupReqSeq) rankLoading.value = false
  }
}

async function selectGroup() {
  const gid = selectedGroup.value
  ++acctReqSeq
  loadError.value = null
  account.value = null
  acctSearched.value = false
  acctError.value = null
  adjustResult.value = ''
  adjustError.value = false
  rankings.value = []
  if (!gid) {
    ++groupReqSeq
    rankLoading.value = false
    return
  }
  await fetchRankingsFor(gid)
}

function lookupUser(uid: string) {
  searchUid.value = uid
  searchAccount()
}

async function searchAccount() {
  const uid = searchUid.value.trim()
  const gid = selectedGroup.value
  if (!uid || !gid) return
  const seq = ++acctReqSeq
  acctLoading.value = true
  acctSearched.value = true
  acctError.value = null
  account.value = null
  adjustResult.value = ''
  adjustError.value = false
  try {
    const res = await getAccount(gid, uid)
    if (seq !== acctReqSeq || selectedGroup.value !== gid) return
    account.value = { ...res, group_id: res.group_id || gid }
  } catch (e: any) {
    if (seq !== acctReqSeq || selectedGroup.value !== gid) return
    account.value = null
    if (e?.status !== 404) {
      acctError.value = e?.message || String(e)
    }
  } finally {
    if (seq === acctReqSeq) acctLoading.value = false
  }
}

async function doAdjust() {
  const acct = account.value
  if (!acct || acct.group_id !== selectedGroup.value) return
  const amount = adjustAmount.value
  if (typeof amount !== 'number' || !Number.isInteger(amount) || amount === 0) {
    adjustResult.value = '请输入非零整数金额'
    adjustError.value = true
    toast(adjustResult.value, 'error')
    return
  }
  const gid = acct.group_id
  const uid = acct.user_id
  adjLoading.value = true
  adjustResult.value = ''
  adjustError.value = false
  try {
    const data = await adjustGold(gid, uid, amount, adjustReason.value)
    if (account.value && account.value.group_id === gid && account.value.user_id === uid) {
      account.value.gold = data.new_balance
    }
    adjustResult.value = `调整成功，新余额 ${data.new_balance.toLocaleString()}`
    adjustAmount.value = null
    adjustReason.value = ''
    toast('调整成功')
    // Refresh rankings and group totals in background
    Promise.all([
      fetchRankingsFor(gid),
      listGroups().then((r) => { groups.value = r.groups || [] }).catch(() => {}),
    ])
  } catch (e: any) {
    adjustResult.value = `调整失败：${e?.message || e}`
    adjustError.value = true
    toast(adjustResult.value, 'error')
  } finally {
    adjLoading.value = false
  }
}
</script>

<style scoped>
.ge-banner { margin-bottom: var(--qq-gap-md); }
.error { color: var(--qq-danger); font-size: var(--qq-text-sm); }
.muted { color: var(--qq-text-muted); font-size: var(--qq-text-sm); }
.mono { font-family: var(--qq-font-mono); }
.toolbar { display: flex; align-items: center; gap: var(--qq-gap-md); flex-wrap: wrap; margin-bottom: var(--qq-gap-lg); padding: var(--qq-gap-sm) var(--qq-gap-md); background: var(--qq-surface); border: 1px solid var(--qq-border); border-radius: var(--qq-radius-card); box-shadow: var(--qq-shadow-card); }
.toolbar label { display: flex; align-items: center; gap: var(--qq-gap-xs); color: var(--qq-text-muted); font-size: var(--qq-text-sm); }
.section { margin-bottom: var(--qq-gap-md); }
.st { margin: 0 0 var(--qq-gap-md) 0; }
.num { text-align: right; font-variant-numeric: tabular-nums; }
.acct-link { color: var(--qq-primary); text-decoration: none; font-family: var(--qq-font-mono); }
.acct-link:hover { text-decoration: underline; }
.lookup { display: flex; align-items: center; gap: var(--qq-gap-md); flex-wrap: wrap; margin-bottom: var(--qq-gap-md); }
.acct-info { display: flex; align-items: center; gap: var(--qq-gap-md); flex-wrap: wrap; padding-bottom: var(--qq-gap-md); border-bottom: 1px solid var(--qq-border); margin-bottom: var(--qq-gap-md); }
.al { color: var(--qq-text-muted); font-size: var(--qq-text-xs); }
.acct-info strong { color: var(--qq-primary); }
.adj-row { display: flex; gap: var(--qq-gap-sm); align-items: center; flex-wrap: wrap; }
.adj-amt { width: 130px; }
.adj-reason { flex: 1; min-width: 160px; }
.adj-res { margin-top: var(--qq-gap-sm); font-size: var(--qq-text-sm); color: var(--qq-primary); }
.adj-err { color: var(--qq-danger); }
</style>
