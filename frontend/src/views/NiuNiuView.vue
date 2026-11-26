<template>
  <div>
    <UiPageHeader title="牛牛大作战" subtitle="查看全局排行、用户详情，手动修正异常数据" />
    <UiStatStrip v-if="totalUsers || textModes.length" :items="stripItems" />
    <div v-if="loadError" class="soft-note soft-note--danger nn-banner" role="alert">{{ loadError }}</div>
    <UiCard padding="md" shadow="sm" accent="primary" class="section">
      <div class="toolbar">
        <h3 class="st section-title">排行</h3>
        <UiTabs :model-value="rankType" :tabs="rankTabs" @change="switchRank" />
        <UiButton style="margin-left:auto" size="sm" icon="RefreshCw" :loading="rankLoading" @click="loadRankings" />
      </div>
      <Transition name="tab-pane" mode="out-in">
        <div :key="rankType">
          <UiLoading v-if="rankLoading && !rankings.length" />
          <UiEmpty v-else-if="!rankings.length" icon="BarChart3" :title="'暂无' + rankLabel + '数据'" />
          <div v-else class="table-scroll">
            <table>
              <thead>
                <tr>
                  <th class="num">#</th>
                  <th>QQ</th>
                  <th class="num">{{ rankColLabel }}</th>
                </tr>
              </thead>
              <tbody>
                <tr v-for="(r, i) in rankings" :key="r.uid">
                  <td class="num">{{ i + 1 }}</td>
                  <td><a href="#" class="link" @click.prevent="selectUser(r.uid)">{{ r.uid }}</a></td>
                  <td class="num">{{ r.length }}</td>
                </tr>
              </tbody>
            </table>
          </div>
        </div>
      </Transition>
    </UiCard>

    <UiCard padding="md" shadow="sm" accent="cyan" class="section">
      <h3 class="st section-title">用户查询</h3>
      <div class="lookup">
        <input v-model="searchUid" placeholder="QQ 号" style="width:160px" @keyup.enter="searchUser" />
        <UiButton icon="Search" :loading="userLoading" @click="searchUser">查询</UiButton>
      </div>
      <div v-if="userDetail" class="user-detail">
        <div class="acct-info">
          <span class="al">QQ</span><span class="mono">{{ userDetail.uid }}</span>
          <span class="al">长度</span><strong>{{ userDetail.length }} cm</strong>
          <span class="al">总排行</span><span>第 {{ userDetail.rank_natural }} 名</span>
          <span v-if="userDetail.rank_length > 0" class="al">长度排行</span>
          <span v-if="userDetail.rank_length > 0">第 {{ userDetail.rank_length }} 名</span>
          <span v-if="userDetail.rank_depth > 0" class="al">深度排行</span>
          <span v-if="userDetail.rank_depth > 0">第 {{ userDetail.rank_depth }} 名</span>
          <span class="al">绝对值<UiInfoTip text="按长度的绝对值排名：长度可为负，此榜只看大小不看正负。" /></span><span>第 {{ userDetail.rank_absolute }} 名</span>
          <span class="al">打胶运势<UiInfoTip text="每日自动重掷的运势系数，影响当日打胶的长度收益；可在此手动修正。" /></span><span class="luck-val" :style="{ color: luckColor(userDetail.luck) }">{{ luckText(userDetail.luck) }}</span>
          <span class="al">击剑运势<UiInfoTip text="每日自动重掷的运势系数，影响当日击剑对战的数值结算；可在此手动修正。" /></span><span class="luck-val" :style="{ color: luckColor(userDetail.fence_luck) }">{{ luckText(userDetail.fence_luck) }}</span>
        </div>
        <div class="adj-row">
          <input v-model.number="adjustLengthVal" type="number" step="0.01" placeholder="新长度" class="adj-amt" />
          <input v-model="adjustReason" placeholder="原因（可选）" class="adj-reason" maxlength="200" />
          <UiButton variant="primary" icon="Send" :loading="adjLoading" @click="doAdjust">修正</UiButton>
        </div>
        <div class="adj-row" style="margin-top:var(--qq-gap-sm)">
          <input v-model.number="adjustLuckVal" type="number" step="0.01" min="0.01" placeholder="打胶运势 (>0)" class="adj-amt" />
          <input v-model="adjustLuckReason" placeholder="原因（可选）" class="adj-reason" maxlength="200" />
          <UiButton variant="primary" icon="Sparkles" :loading="luckLoading" @click="doSetLuck">设打胶运</UiButton>
        </div>
        <div class="adj-row" style="margin-top:var(--qq-gap-sm)">
          <input v-model.number="adjustFenceLuckVal" type="number" step="0.01" min="0.01" placeholder="击剑运势 (>0)" class="adj-amt" />
          <input v-model="adjustFenceLuckReason" placeholder="原因（可选）" class="adj-reason" maxlength="200" />
          <UiButton variant="primary" icon="Swords" :loading="fenceLuckLoading" @click="doSetFenceLuck">设击剑运</UiButton>
        </div>
        <p v-if="adjustResult" class="adj-res" :class="{ 'adj-err': adjustError }">{{ adjustResult }}</p>
        <h4 class="st section-title" style="margin-top:var(--qq-gap-md)">操作记录（最近 30 条）</h4>
        <div v-if="userDetail.records.length" class="table-scroll">
          <table>
            <thead>
              <tr>
                <th>动作</th>
                <th class="num">前</th>
                <th class="num">后</th>
                <th class="num">差值</th>
                <th>时间</th>
              </tr>
            </thead>
            <tbody>
              <tr v-for="(r, idx) in userDetail.records" :key="`${r.created_at}-${idx}`">
                <td><UiTag size="sm" :variant="tv(r.action)">{{ al(r.action) }}</UiTag></td>
                <td class="num">{{ r.origin_length }}</td>
                <td class="num">{{ r.new_length }}</td>
                <td class="num" :class="{ pos: r.diff > 0, neg: r.diff < 0 }">{{ r.diff > 0 ? '+' : '' }}{{ r.diff }}</td>
                <td class="time">{{ formatRecordTime(r.created_at) }}</td>
              </tr>
            </tbody>
          </table>
        </div>
        <UiEmpty v-else compact icon="FileText" title="暂无操作记录" />
      </div>
      <p v-else-if="userError" class="error" style="margin-top:12px">{{ userError }}</p>
      <p v-else-if="userSearched && !userLoading" class="muted" style="margin-top:12px">未找到该用户</p>
    </UiCard>

    <UiCard padding="md" shadow="sm" accent="accent" class="section">
      <h3 class="st section-title">文案模式管理</h3>
      <p v-if="textModesLoadError" class="error">{{ textModesLoadError }}</p>
      <UiLoading v-if="textModesLoading" />
      <div v-else>
        <div class="mode-tags">
          <span class="st" style="margin-right:8px">可用模式：</span>
          <UiTag v-for="m in textModes" :key="m" :variant="m === textDefault ? 'warn' : 'info'" size="sm">{{ m }}{{ m === textDefault ? ' (默认)' : '' }}</UiTag>
        </div>
        <div class="add-group-row">
          <input v-model="newGroupId" placeholder="5–12 位群号" style="width:160px" @keyup.enter="doAddGroupMode" />
          <select v-model="newGroupMode">
            <option value="" disabled>选择模式</option>
            <option v-for="m in textModes" :key="m" :value="m">{{ m }}</option>
          </select>
          <UiButton icon="Plus" :loading="addModeLoading" @click="doAddGroupMode">设置</UiButton>
        </div>
        <div v-if="textModeGroups.length" class="table-scroll" style="margin-top:var(--qq-gap-md)">
          <table>
            <thead>
              <tr>
                <th>群号</th>
                <th class="num">当前模式</th>
                <th class="num">切换</th>
              </tr>
            </thead>
            <tbody>
              <tr v-for="g in textModeGroups" :key="g.group_id">
                <td class="mono">{{ g.group_id }}</td>
                <td class="num"><UiTag size="sm" :variant="g.text_mode === textDefault ? 'warn' : 'info'">{{ g.text_mode }}</UiTag></td>
                <td class="num">
                  <select :value="g.text_mode" @change="doSwitchMode(g.group_id, g.text_mode, $event.target as HTMLSelectElement)">
                    <option v-for="m in textModes" :key="m" :value="m">{{ m }}</option>
                  </select>
                </td>
              </tr>
            </tbody>
          </table>
        </div>
        <p v-else class="muted" style="margin-top:8px">暂无群组设置过文案模式，全部使用默认。</p>
      </div>
    </UiCard>
  </div>
</template>

<script setup lang="ts">
import { computed, onMounted, ref } from 'vue'
import UiPageHeader from '../components/ui/UiPageHeader.vue'
import UiCard from '../components/ui/UiCard.vue'
import UiButton from '../components/ui/UiButton.vue'
import UiTag from '../components/ui/UiTag.vue'
import UiLoading from '../components/ui/UiLoading.vue'
import UiEmpty from '../components/ui/UiEmpty.vue'
import UiTabs from '../components/ui/UiTabs.vue'
import UiStatStrip from '../components/ui/UiStatStrip.vue'
import UiInfoTip from '../components/ui/UiInfoTip.vue'
import { getRankings, getUser, adjustLength, setLuck, setFenceLuck, getTextModes, setGroupTextMode } from '../api/niuniu'
import { toast } from '../toast'

const loadError = ref<string | null>(null)
const rankType = ref('natural')
const rankLoading = ref(false)
const rankings = ref<any[]>([])
const totalUsers = ref(0)

const searchUid = ref('')
const userLoading = ref(false)
const userSearched = ref(false)
const userError = ref<string | null>(null)
const userDetail = ref<any>(null)

const adjustLengthVal = ref<number | string | null>(null)
const adjustReason = ref('')
const adjLoading = ref(false)
const adjustResult = ref('')
const adjustError = ref(false)

const adjustLuckVal = ref<number | string | null>(null)
const adjustLuckReason = ref('')
const luckLoading = ref(false)

const adjustFenceLuckVal = ref<number | string | null>(null)
const adjustFenceLuckReason = ref('')
const fenceLuckLoading = ref(false)

// Text mode management
const textModes = ref<string[]>([])
const textDefault = ref('default')
const textModeGroups = ref<any[]>([])
const textModesLoading = ref(false)
const textModesLoadError = ref<string | null>(null)
const newGroupId = ref('')
const newGroupMode = ref('')
const addModeLoading = ref(false)

let rankReqSeq = 0
let userReqSeq = 0

const RANK_LABELS: Record<string, string> = { natural: '自然数值', absolute: '绝对值', length: '长度', depth: '深度' }
const RANK_COL_LABELS: Record<string, string> = { natural: '长度 (cm)', absolute: '长度 (cm)', length: '长度 (cm)', depth: '深度 (cm)' }
const stripItems = computed(() => [
  { label: '注册用户', value: totalUsers.value, icon: 'Swords' },
  { label: '文案模式', value: textModes.value.length, icon: 'FileText' },
])

const rankTabs = [
  { key: 'natural', label: '自然' },
  { key: 'absolute', label: '绝对值' },
  { key: 'length', label: '长度' },
  { key: 'depth', label: '深度' },
]
const rankLabel = computed(() => RANK_LABELS[rankType.value] || rankType.value)
const rankColLabel = computed(() => RANK_COL_LABELS[rankType.value] || '长度 (cm)')

const AL: Record<string, string> = {
  register: '注册',
  reset_length: '数值重置',
  unsubscribe: '注销',
  gluing: '打胶',
  fencing: '击剑',
  fenced: '被击',
  fencing_draw: '平局',
  fencing_self_hurt: '自伤',
  admin_adjust: '修正',
}
function al(a: string) { return AL[a] || a }

const TAG_VARIANTS: Record<string, 'info' | 'success' | 'warn' | 'danger'> = {
  register: 'success',
  unsubscribe: 'danger',
  fencing: 'success',
  fenced: 'danger',
  gluing: 'info',
  fencing_draw: 'warn',
  fencing_self_hurt: 'danger',
  admin_adjust: 'warn',
  reset_length: 'info',
}
function tv(a: string): 'info' | 'success' | 'warn' | 'danger' {
  return TAG_VARIANTS[a] || 'info'
}

function formatRecordTime(raw: string | null | undefined): string {
  if (!raw) return ''
  const hasTz = /(?:Z|[+-]\d{2}:?\d{2})$/i.test(raw)
  const normalized = hasTz ? raw : raw.replace(' ', 'T') + 'Z'
  const d = new Date(normalized)
  if (Number.isNaN(d.getTime())) return raw.slice(0, 16).replace('T', ' ')
  const pad = (n: number) => String(n).padStart(2, '0')
  return `${d.getFullYear()}-${pad(d.getMonth() + 1)}-${pad(d.getDate())} ${pad(d.getHours())}:${pad(d.getMinutes())}`
}

function isValidFiniteNumber(v: unknown): v is number {
  return typeof v === 'number' && Number.isFinite(v)
}

onMounted(() => {
  loadRankings()
  loadTextModes()
})

async function loadRankings() {
  const type = rankType.value
  const seq = ++rankReqSeq
  rankLoading.value = true
  loadError.value = null
  try {
    const data = await getRankings(type)
    if (seq !== rankReqSeq || rankType.value !== type) return
    rankings.value = data.rankings || []
    totalUsers.value = data.total_users || 0
  } catch (e: unknown) {
    if (seq !== rankReqSeq || rankType.value !== type) return
    loadError.value = (e as Error).message || String(e)
  } finally {
    if (seq === rankReqSeq) rankLoading.value = false
  }
}

async function loadTextModes() {
  textModesLoading.value = true
  textModesLoadError.value = null
  try {
    const data = await getTextModes()
    textModes.value = data.modes || []
    textDefault.value = data.default || 'default'
    textModeGroups.value = data.groups || []
  } catch (e: unknown) {
    textModesLoadError.value = (e as Error).message || String(e)
  } finally {
    textModesLoading.value = false
  }
}

async function doAddGroupMode() {
  const gid = newGroupId.value.trim()
  if (!/^\d{5,12}$/.test(gid)) {
    toast('群号必须为 5–12 位纯数字', 'error')
    return
  }
  if (!newGroupMode.value) {
    toast('请先选择文案模式', 'error')
    return
  }
  addModeLoading.value = true
  try {
    await setGroupTextMode(gid, newGroupMode.value)
    toast('已设置')
    newGroupId.value = ''
    await loadTextModes()
  } catch (e: unknown) {
    toast((e as Error).message || String(e), 'error')
  } finally {
    addModeLoading.value = false
  }
}

async function doSwitchMode(groupId: string, prevMode: string, selectEl: HTMLSelectElement) {
  const mode = selectEl.value
  if (!mode || mode === prevMode) return
  try {
    await setGroupTextMode(groupId, mode)
    toast(`群 ${groupId} 切换至 ${mode}`)
    await loadTextModes()
  } catch (e: unknown) {
    selectEl.value = prevMode
    toast((e as Error).message || String(e), 'error')
  }
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
  const uid = searchUid.value.trim()
  if (!uid) return
  const seq = ++userReqSeq
  userLoading.value = true
  userSearched.value = true
  userError.value = null
  userDetail.value = null
  adjustResult.value = ''
  adjustError.value = false
  try {
    const data = await getUser(uid)
    if (seq !== userReqSeq) return
    userDetail.value = data
  } catch (e: any) {
    if (seq !== userReqSeq) return
    userDetail.value = null
    if (e?.status !== 404) {
      userError.value = e?.message || String(e)
    }
  } finally {
    if (seq === userReqSeq) userLoading.value = false
  }
}

async function refreshUserQuiet(uid: string) {
  const seq = ++userReqSeq
  try {
    const data = await getUser(uid)
    if (seq !== userReqSeq) return
    if (userDetail.value?.uid === uid) userDetail.value = data
  } catch {
    // Keep existing detail on background refresh failure
  }
}

async function doAdjust() {
  const detail = userDetail.value
  if (!detail) return
  if (!isValidFiniteNumber(adjustLengthVal.value)) {
    adjustResult.value = '请输入有效的数字长度'
    adjustError.value = true
    toast(adjustResult.value, 'error')
    return
  }
  const uid = detail.uid
  const nextVal = adjustLengthVal.value
  adjLoading.value = true
  adjustResult.value = ''
  adjustError.value = false
  try {
    const data = await adjustLength(uid, nextVal, adjustReason.value)
    adjustResult.value = `修正成功：${data.old_length} → ${data.new_length}`
    if (userDetail.value?.uid === uid) userDetail.value.length = data.new_length
    adjustLengthVal.value = null
    adjustReason.value = ''
    toast('修正成功')
    Promise.all([refreshUserQuiet(uid), loadRankings()])
  } catch (e: any) {
    adjustResult.value = `修正失败：${e?.message || e}`
    adjustError.value = true
    toast(adjustResult.value, 'error')
  } finally {
    adjLoading.value = false
  }
}

function luckColor(v: number): string {
  const n = Number(v)
  if (n >= 3.0) return 'var(--qq-success)'
  if (n >= 1.0) return 'var(--qq-primary)'
  if (n >= 0.3) return 'var(--qq-warn)'
  return 'var(--qq-danger)'
}

function luckText(v: number): string {
  const n = Number(v)
  const formatted = Number.isFinite(n) ? n.toFixed(2) : String(v)
  if (n >= 3.0) return `🍀 ${formatted}`
  if (n >= 1.0) return `✨ ${formatted}`
  if (n >= 0.3) return `😐 ${formatted}`
  return `💀 ${formatted}`
}

async function doSetLuck() {
  const detail = userDetail.value
  if (!detail) return
  if (!isValidFiniteNumber(adjustLuckVal.value) || adjustLuckVal.value <= 0) {
    adjustResult.value = '请输入大于 0 的打胶运势值'
    adjustError.value = true
    toast(adjustResult.value, 'error')
    return
  }
  const uid = detail.uid
  const nextVal = adjustLuckVal.value
  luckLoading.value = true
  adjustResult.value = ''
  adjustError.value = false
  try {
    const data = await setLuck(uid, nextVal, adjustLuckReason.value)
    adjustResult.value = `打胶运势修正：${Number(data.old_luck).toFixed(2)} → ${Number(data.new_luck).toFixed(2)}`
    if (userDetail.value?.uid === uid) userDetail.value.luck = data.new_luck
    adjustLuckVal.value = null
    adjustLuckReason.value = ''
    toast('修正成功')
  } catch (e: any) {
    adjustResult.value = `修正失败：${e?.message || e}`
    adjustError.value = true
    toast(adjustResult.value, 'error')
  } finally {
    luckLoading.value = false
  }
}

async function doSetFenceLuck() {
  const detail = userDetail.value
  if (!detail) return
  if (!isValidFiniteNumber(adjustFenceLuckVal.value) || adjustFenceLuckVal.value <= 0) {
    adjustResult.value = '请输入大于 0 的击剑运势值'
    adjustError.value = true
    toast(adjustResult.value, 'error')
    return
  }
  const uid = detail.uid
  const nextVal = adjustFenceLuckVal.value
  fenceLuckLoading.value = true
  adjustResult.value = ''
  adjustError.value = false
  try {
    const data = await setFenceLuck(uid, nextVal, adjustFenceLuckReason.value)
    adjustResult.value = `击剑运势修正：${Number(data.old_fence_luck).toFixed(2)} → ${Number(data.new_fence_luck).toFixed(2)}`
    if (userDetail.value?.uid === uid) userDetail.value.fence_luck = data.new_fence_luck
    adjustFenceLuckVal.value = null
    adjustFenceLuckReason.value = ''
    toast('修正成功')
  } catch (e: any) {
    adjustResult.value = `修正失败：${e?.message || e}`
    adjustError.value = true
    toast(adjustResult.value, 'error')
  } finally {
    fenceLuckLoading.value = false
  }
}
</script>

<style scoped>
.nn-banner { margin-bottom: var(--qq-gap-md); }
.error { color: var(--qq-danger); font-size: var(--qq-text-sm); }
.muted { color: var(--qq-text-muted); font-size: var(--qq-text-sm); }
.mono { font-family: var(--qq-font-mono); }
.section { margin-bottom: var(--qq-gap-md); }
.toolbar { display: flex; align-items: center; gap: var(--qq-gap-md); flex-wrap: wrap; }
.st { margin: 0; }
.num { text-align: right; font-variant-numeric: tabular-nums; }
.link { color: var(--qq-primary); text-decoration: none; font-family: var(--qq-font-mono); }
.link:hover { text-decoration: underline; }
.time { font-size: var(--qq-text-xs); color: var(--qq-text-muted); white-space: nowrap; }
.pos { color: var(--qq-success); font-weight: 600; }
.neg { color: var(--qq-danger); font-weight: 600; }
.lookup { display: flex; align-items: center; gap: var(--qq-gap-md); flex-wrap: wrap; margin-bottom: var(--qq-gap-md); }
.acct-info { display: flex; align-items: center; gap: var(--qq-gap-md); flex-wrap: wrap; padding-bottom: var(--qq-gap-md); border-bottom: 1px solid var(--qq-border); margin-bottom: var(--qq-gap-md); }
.al { color: var(--qq-text-muted); font-size: var(--qq-text-xs); }
.acct-info strong { color: var(--qq-primary); }
.adj-row { display: flex; gap: var(--qq-gap-sm); align-items: center; flex-wrap: wrap; }
.adj-amt { width: 130px; }
.adj-reason { flex: 1; min-width: 160px; }
.adj-res { margin-top: var(--qq-gap-sm); font-size: var(--qq-text-sm); color: var(--qq-primary); }
.adj-err { color: var(--qq-danger); }
.mode-tags { display: flex; align-items: center; gap: 4px; margin-bottom: var(--qq-gap-md); flex-wrap: wrap; }
.add-group-row { display: flex; gap: var(--qq-gap-sm); align-items: center; flex-wrap: wrap; margin-top: var(--qq-gap-md); }
.add-group-row select { border: 1px solid var(--qq-border); border-radius: var(--qq-radius-sm); padding: 4px 8px; font-size: var(--qq-text-sm); background: var(--qq-surface); color: var(--qq-text); }
table select { border: 1px solid var(--qq-border); border-radius: var(--qq-radius-sm); padding: 2px 6px; font-size: var(--qq-text-xs); background: var(--qq-surface); color: var(--qq-text); }
</style>
