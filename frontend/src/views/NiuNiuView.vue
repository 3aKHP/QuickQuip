<template>
  <div>
    <UiPageHeader title="牛牛大作战" subtitle="查看全局排行、用户详情，手动修正异常数据" />

    <p v-if="loadError" class="error">{{ loadError }}</p>

    <!-- Rankings -->
    <UiCard padding="md" shadow="sm" class="section-card">
      <div class="toolbar-inner">
        <h3 class="section-title">🏆 排行</h3>
        <div class="tab-row">
          <button :class="{ active: rankType === 'length' }" @click="switchRank('length')">长度</button>
          <button :class="{ active: rankType === 'depth' }" @click="switchRank('depth')">深度</button>
        </div>
        <span class="muted" style="margin-left:auto">共 {{ totalUsers.toLocaleString() }} 注册用户</span>
        <UiButton size="sm" icon="RefreshCw" :loading="rankLoading" @click="loadRankings" />
      </div>

      <UiLoading v-if="rankLoading && !rankings.length" />
      <UiEmpty v-else-if="!rankings.length" icon="BarChart3"
        :title="rankType === 'length' ? '暂无长度数据' : '暂无深度数据'" />
      <table v-else class="data-table">
        <thead>
          <tr><th class="num">#</th><th>QQ</th><th class="num">{{ rankType === 'length' ? '长度 (cm)' : '深度 (cm)' }}</th></tr>
        </thead>
        <tbody>
          <tr v-for="(r, i) in rankings" :key="r.uid">
            <td class="num">{{ i + 1 }}</td>
            <td><a href="#" @click.prevent="selectUser(r.uid)"><code>{{ r.uid }}</code></a></td>
            <td class="num">{{ r.length }}</td>
          </tr>
        </tbody>
      </table>
    </UiCard>

    <!-- User lookup & detail -->
    <UiCard padding="md" shadow="sm" class="section-card">
      <h3 class="section-title">🔍 用户查询</h3>
      <div class="toolbar-inner">
        <input v-model="searchUid" placeholder="QQ 号" style="width:160px" @keyup.enter="searchUser" />
        <UiButton icon="Search" :loading="userLoading" @click="searchUser">查询</UiButton>
      </div>

      <div v-if="userDetail" class="user-detail">
        <div class="acct-info">
          <span class="acct-label">QQ</span><code>{{ userDetail.uid }}</code>
          <span class="acct-label">长度</span><strong>{{ userDetail.length }} cm</strong>
          <span v-if="userDetail.rank > 0" class="acct-label">排名</span><span>第 {{ userDetail.rank }} 名</span>
        </div>

        <!-- Length adjustment -->
        <div class="adjust-row">
          <input v-model.number="adjustLengthVal" type="number" step="0.01" placeholder="新长度" class="adjust-input" />
          <input v-model="adjustReason" placeholder="原因（可选）" class="reason-input" maxlength="200" />
          <UiButton variant="primary" icon="Send" :loading="adjLoading" @click="doAdjust">修正</UiButton>
        </div>
        <p v-if="adjustResult" class="adjust-result" :class="{ 'adjust-err': adjustError }">{{ adjustResult }}</p>

        <!-- Records -->
        <h4 class="section-title" style="margin-top:var(--qq-gap-md)">操作记录（最近 30 条）</h4>
        <table v-if="userDetail.records.length" class="data-table">
          <thead>
            <tr><th>动作</th><th class="num">变化前</th><th class="num">变化后</th><th class="num">差值</th><th>时间</th></tr>
          </thead>
          <tbody>
            <tr v-for="r in userDetail.records" :key="r.created_at">
              <td><UiTag size="sm" :variant="tagVariant(r.action)">{{ actionLabel(r.action) }}</UiTag></td>
              <td class="num">{{ r.origin_length }}</td>
              <td class="num">{{ r.new_length }}</td>
              <td class="num" :class="{ positive: r.diff > 0, negative: r.diff < 0 }">
                {{ r.diff > 0 ? '+' : '' }}{{ r.diff }}
              </td>
              <td class="time">{{ r.created_at?.slice(0, 16).replace('T', ' ') }}</td>
            </tr>
          </tbody>
        </table>
        <UiEmpty v-else icon="FileText" title="暂无记录" style="margin-top:var(--qq-gap-sm)" />
      </div>
      <p v-else-if="userSearched" class="muted" style="margin-top:12px">未找到该用户</p>
    </UiCard>
  </div>
</template>

<script setup lang="ts">
import { onMounted, ref } from 'vue'
import UiPageHeader from '../components/ui/UiPageHeader.vue'
import UiCard from '../components/ui/UiCard.vue'
import UiButton from '../components/ui/UiButton.vue'
import UiTag from '../components/ui/UiTag.vue'
import UiLoading from '../components/ui/UiLoading.vue'
import UiEmpty from '../components/ui/UiEmpty.vue'
import { getRankings, getUser, adjustLength } from '../api/niuniu'
import { toast } from '../toast'

const loadError = ref<string | null>(null)
const rankType = ref('length')
const rankLoading = ref(false)
const rankings = ref<any[]>([])
const totalUsers = ref(0)
const searchUid = ref('')
const userLoading = ref(false)
const userSearched = ref(false)
const userDetail = ref<any>(null)
const adjustLengthVal = ref<number | null>(null)
const adjustReason = ref('')
const adjLoading = ref(false)
const adjustResult = ref('')
const adjustError = ref(false)

const ACTION_LABELS: Record<string, string> = {
  register: '注册', unsubscribe: '注销', gluing: '打胶',
  fencing: '击剑', fenced: '被击', admin_adjust: '修正',
}
function actionLabel(a: string) { return ACTION_LABELS[a] || a }

function tagVariant(a: string): string {
  const m: Record<string, string> = { fencing: 'success', fenced: 'danger', gluing: 'info', admin_adjust: 'warn' }
  return m[a] || ''
}

onMounted(() => { loadRankings() })

async function loadRankings() {
  rankLoading.value = true
  try {
    const data = await getRankings(rankType.value)
    rankings.value = data.rankings || []
    totalUsers.value = data.total_users || 0
  } catch (e: any) { loadError.value = e.message || String(e) }
  finally { rankLoading.value = false }
}

async function switchRank(type: string) {
  rankType.value = type
  await loadRankings()
}

async function selectUser(uid: string) {
  searchUid.value = uid
  await searchUser()
}

async function searchUser() {
  if (!searchUid.value.trim()) return
  userLoading.value = true; userSearched.value = true; userDetail.value = null
  try { userDetail.value = await getUser(searchUid.value.trim()) }
  catch { userDetail.value = null }
  finally { userLoading.value = false }
}

async function doAdjust() {
  if (adjustLengthVal.value == null || !userDetail.value) return
  adjLoading.value = true; adjustResult.value = ''; adjustError.value = false
  try {
    const data = await adjustLength(userDetail.value.uid, adjustLengthVal.value, adjustReason.value)
    adjustResult.value = `修正成功：${data.old_length} → ${data.new_length}`
    userDetail.value.length = data.new_length
    adjustLengthVal.value = null; adjustReason.value = ''
    toast('长度修正成功')
  } catch (e: any) {
    adjustResult.value = `修正失败：${e.message || e}`
    adjustError.value = true
    toast(adjustResult.value, 'error')
  } finally { adjLoading.value = false }
}
</script>

<style scoped>
.error { color: var(--qq-danger); }
.muted { color: var(--qq-text-muted); font-size: var(--qq-text-sm); }

.section-card { margin-bottom: var(--qq-gap-md); }

.toolbar-inner {
  display: flex; align-items: center; gap: var(--qq-gap-md); flex-wrap: wrap;
}
.toolbar-inner input {
  background: var(--qq-surface-strong);
  border: 1px solid var(--qq-border);
  border-radius: var(--qq-radius-sm);
  color: var(--qq-text);
  padding: 5px 10px;
  font-size: var(--qq-text-base);
  outline: none;
}
.toolbar-inner input:focus {
  border-color: var(--qq-accent);
  box-shadow: 0 0 0 3px var(--qq-accent-soft);
}

.section-title { margin: 0; font-size: var(--qq-text-base); color: var(--qq-text); }

.tab-row { display: flex; }
.tab-row button {
  padding: 4px 16px;
  border: 1px solid var(--qq-border);
  background: var(--qq-surface-strong);
  color: var(--qq-text-muted);
  font-size: var(--qq-text-sm);
  cursor: pointer;
}
.tab-row button:first-child { border-radius: var(--qq-radius-sm) 0 0 var(--qq-radius-sm); }
.tab-row button:last-child { border-radius: 0 var(--qq-radius-sm) var(--qq-radius-sm) 0; margin-left: -1px; }
.tab-row button.active { background: var(--qq-accent); color: #fff; border-color: var(--qq-accent); }

.data-table { width: 100%; border-collapse: collapse; font-size: var(--qq-text-sm); margin-top: var(--qq-gap-sm); }
.data-table th { text-align: left; padding: 6px 10px; border-bottom: 2px solid var(--qq-border); color: var(--qq-text-muted); font-weight: 600; }
.data-table td { padding: 6px 10px; border-bottom: 1px solid var(--qq-border); }
.data-table .num { text-align: right; font-variant-numeric: tabular-nums; }
.data-table code { font-family: var(--qq-font-mono); color: var(--qq-accent); }
.data-table .time { font-size: var(--qq-text-xs); color: var(--qq-text-muted); }
.positive { color: var(--qq-success); font-weight: 600; }
.negative { color: var(--qq-danger); font-weight: 600; }

.user-detail { margin-top: var(--qq-gap-md); }
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
