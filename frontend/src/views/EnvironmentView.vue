<script setup lang="ts">
import { computed, nextTick, onMounted, onUnmounted, reactive, ref } from 'vue'
import { onBeforeRouteLeave, useRoute } from 'vue-router'
import { loadEnvironment, previewEnvironment, saveEnvironment, getEnvironmentOperation } from '../api/environment'
import type { EnvironmentList, Edit, Operation, Variable } from '../api/environment'
import UiPageHeader from '../components/ui/UiPageHeader.vue'
import UiCard from '../components/ui/UiCard.vue'
import UiButton from '../components/ui/UiButton.vue'
import UiTag from '../components/ui/UiTag.vue'
import UiIcon from '../components/ui/UiIcon.vue'
import UiLoading from '../components/ui/UiLoading.vue'
import UiEmpty from '../components/ui/UiEmpty.vue'

const listing = ref<EnvironmentList | null>(null)
const edits = reactive<Record<string, Edit>>({})
const route = useRoute()
const search = ref(String(route.query.variable ?? ''))
const newName = ref('')
const password = ref('')
const error = ref('')
const busy = ref(false)
const refreshing = ref(true)
const reviewed = ref(false)
const preview = ref<Operation | null>(null)
const operation = ref<Operation | null>(null)
const requestId = ref(crypto.randomUUID())
const changes = computed(() => Object.values(edits))
const rows = computed(() => {
  const stored = listing.value?.variables ?? []
  const added = changes.value.filter(e => e.action === 'create').map(e => {
    const description = reviewed.value ? preview.value?.changes.find(row => row.name === e.name) : undefined
    return { name: e.name, assigned: false, mode: description?.mode ?? 'unknown' as const,
      warning: description?.warning ?? '', references: description?.references ?? [], states: {} as Record<string, string> }
  })
  return [...stored, ...added].filter(e => [e.name, ...(e.references ?? [])].join(' ').toLowerCase().includes(search.value.trim().toLowerCase()))
})
function stateLabel(state: string) {
  return ({ loaded: '已加载', synced: '快照已同步', restart: '待重启', loading: '加载中', waiting: '等待启动或重新连接' } as Record<string, string>)[state] ?? state
}
const modeLabel = (mode: Variable['mode']) => ({ hot: '热更新', credential: '热更新', restart: '重启生效', unknown: '按用途生效' })[mode]
const usageHint = '用于 Provider 密钥时，绑定渠道后可热更新。'
function valueState(row: Variable) {
  const action = edits[row.name]?.action
  return action === 'delete' ? '待删除' : action === 'create' ? '待新增' : action === 'empty' ? '待清空' : action ? '已变更' : row.assigned ? '已赋值' : '未赋值'
}
const actionLabel = (action: Edit['action']) => ({ create: '新增', replace: '覆写', empty: '设置空值', delete: '删除' })[action]
async function refresh() {
  refreshing.value = true
  try {
    listing.value = await loadEnvironment()
    error.value = ''
    if (changes.value.length) reviewed.value = false
  } catch (e) { error.value = String(e) }
  finally { refreshing.value = false }
}
function edit(name: string, value: string) {
  const create = edits[name]?.action === 'create'
  if (!value && !create) { delete edits[name] } else { edits[name] = { name, action: create ? 'create' : 'replace', value } }
  reviewed.value = false
}
function mark(name: string, action: Edit['action']) {
  edits[name] = { name, action }; reviewed.value = false
}
function add() {
  const name = newName.value.trim()
  if (!/^[A-Za-z_][A-Za-z0-9_]*$/.test(name) || listing.value?.variables.some(r => r.name === name) || Boolean(edits[name])) {
    error.value = '变量名无效或已存在'; return
  }
  edits[name] = { name, action: 'create', value: '' }; newName.value = ''; reviewed.value = false
  search.value = name
  void nextTick(() => document.getElementById(`environment-value-${name}`)?.focus())
}
function undo(name: string) { delete edits[name]; reviewed.value = false }
async function submit() {
  if (!listing.value) return
  busy.value = true; error.value = ''
  try {
    if (!reviewed.value) {
      preview.value = await previewEnvironment(listing.value.version, changes.value)
      reviewed.value = true; return
    }
    operation.value = await saveEnvironment(listing.value.version, changes.value, password.value, requestId.value)
    for (const name of Object.keys(edits)) delete edits[name]
    password.value = ''; reviewed.value = false; requestId.value = crypto.randomUUID()
    await refresh()
  } catch (e) { error.value = String(e) } finally { busy.value = false }
}
function guard(event: BeforeUnloadEvent) {
  if (changes.value.length) { event.preventDefault(); event.returnValue = '' }
}
onBeforeRouteLeave(() => !changes.value.length || window.confirm('存在未提交的环境变量修改，离开页面？'))
let timer: ReturnType<typeof setInterval> | undefined
onMounted(() => {
  void refresh().then(() => {
    const name = String(route.query.variable ?? '')
    if (name && !listing.value?.variables.some(row => row.name === name)) newName.value = name
  }); window.addEventListener('beforeunload', guard)
  timer = setInterval(async () => {
    if (operation.value) {
      try {
        operation.value = await getEnvironmentOperation(operation.value.id)
        if (!changes.value.length) await refresh()
      } catch (e) { error.value = String(e) }
    }
  }, 5000)
})
onUnmounted(() => { clearInterval(timer); window.removeEventListener('beforeunload', guard) })
</script>

<template>
  <section class="environment-panel">
    <UiPageHeader title="环境变量" subtitle="管理根 .env 中的密钥与运行参数">
      <template #actions>
        <UiTag v-if="listing?.enabled && listing.backend_available">{{ listing.variables.length }} 项变量</UiTag>
        <UiButton icon="RefreshCw" :loading="refreshing" :disabled="busy" @click="refresh">刷新状态</UiButton>
      </template>
    </UiPageHeader>

    <div v-if="error" class="soft-note soft-note--danger error-note" role="alert">
      <UiIcon name="AlertTriangle" :size="16" /><span>{{ error }}</span>
      <span v-if="changes.length">未提交的输入已保留。</span>
    </div>
    <UiLoading v-if="!listing && refreshing" text="正在加载环境变量…" />
    <UiCard v-else-if="listing && !listing.enabled">
      <UiEmpty icon="Lock" title="环境变量管理尚未启用" description="在根 .env 设置 QUICKQUIP_ENV_MANAGEMENT_ENABLED=true，并重启 Bot 和 Web Admin。Docker 部署还需接入 env-agent 模板。" />
    </UiCard>
    <UiCard v-else-if="listing && !listing.backend_available">
      <UiEmpty icon="Server" title="环境变量服务不可用" description="检查 env-agent 与通信卷后，点击右上角刷新状态。" />
    </UiCard>

    <fieldset v-if="listing?.enabled && listing.backend_available" :disabled="busy" :aria-busy="busy" class="environment-editor">
      <UiCard padding="none">
        <div class="variable-toolbar">
          <div class="search-field">
            <UiIcon name="Search" :size="16" />
            <input v-model="search" type="search" aria-label="搜索变量" placeholder="搜索变量名或引用渠道">
          </div>
          <div class="create-field">
            <datalist id="environment-suggestions"><option v-for="name in listing.suggestions" :key="name" :value="name" /></datalist>
            <input v-model="newName" list="environment-suggestions" aria-label="新变量名" placeholder="NEW_PROVIDER_API_KEY" spellcheck="false" @keyup.enter="add">
            <UiButton icon="Plus" variant="primary" @click="add">新增</UiButton>
          </div>
        </div>
        <div class="privacy-note"><UiIcon name="Lock" :size="14" /><span>已有值不回显，留空保持原值。启动参数保存后需重启。</span></div>
        <div v-if="rows.length" class="variable-scroll">
          <table class="variable-table">
            <colgroup><col class="col-variable"><col class="col-value"><col class="col-status"><col class="col-actions"></colgroup>
            <thead><tr><th scope="col">变量</th><th scope="col">新值</th><th scope="col">生效与加载</th><th scope="col">操作</th></tr></thead>
            <tbody>
              <tr v-for="row in rows" :key="row.name" :class="{ 'row-edited': edits[row.name], 'row-deleted': edits[row.name]?.action === 'delete' }">
                <td>
                  <div class="variable-identity"><span class="variable-name">{{ row.name }}</span>
                    <UiTag size="sm" :variant="edits[row.name]?.action === 'delete' ? 'danger' : edits[row.name] ? 'warn' : row.assigned ? 'success' : 'info'">{{ valueState(row) }}</UiTag>
                  </div>
                  <p v-if="row.references?.length" class="row-reference">渠道：{{ row.references.join('、') }}</p>
                  <p v-if="row.warning" class="row-warning"><UiIcon name="AlertTriangle" :size="13" />{{ row.warning }}</p>
                </td>
                <td class="value-cell">
                  <textarea :id="`environment-value-${row.name}`" class="secret-value" :rows="Math.min(4, (edits[row.name]?.value ?? '').split('\n').length)" autocomplete="off" spellcheck="false" :aria-label="`${row.name} 新值`" :placeholder="edits[row.name]?.action === 'delete' ? '已标记删除' : edits[row.name]?.action === 'empty' ? '将保存为空值' : '输入新值以覆写'" :value="edits[row.name]?.value ?? ''" :disabled="edits[row.name]?.action === 'delete'" @input="edit(row.name, ($event.target as HTMLTextAreaElement).value)"></textarea>
                </td>
                <td>
                  <UiTag size="sm" class="mode-tag" :variant="row.mode === 'restart' ? 'warn' : 'info'"><UiIcon :name="row.mode === 'restart' ? 'RotateCw' : row.mode === 'unknown' ? 'Info' : 'Zap'" :size="12" />{{ modeLabel(row.mode) }}</UiTag>
                  <p v-if="row.mode === 'unknown'" class="row-reference">{{ usageHint }}</p>
                  <div v-if="!edits[row.name]" class="consumer-states"><span v-for="(state, role) in row.states" :key="role"><i :class="['state-dot', { 'state-dot--loaded': state === 'loaded' || state === 'synced' }]" />{{ role === 'bot' ? 'Bot' : role === 'web' ? 'Web' : role }} {{ stateLabel(state) }}</span></div>
                  <p v-else class="row-reference">保存后确认加载状态</p>
                </td>
                <td><div class="row-actions">
                  <UiButton v-if="edits[row.name]?.action !== 'create'" size="sm" variant="ghost" @click="mark(row.name, 'empty')">设置空值</UiButton>
                  <UiButton v-if="edits[row.name]?.action !== 'create'" size="sm" variant="ghost" class="delete-action" icon="Trash2" @click="mark(row.name, 'delete')">删除</UiButton>
                  <UiButton v-if="edits[row.name]" size="sm" variant="ghost" icon="RotateCcw" @click="undo(row.name)">撤销</UiButton>
                </div></td>
              </tr>
            </tbody>
          </table>
        </div>
        <UiEmpty v-else icon="Search" title="没有匹配的变量" description="调整搜索条件，或在上方新增变量。" />
        <div class="list-footer">显示 {{ rows.length }} 项<span v-if="search.trim()"> · 共 {{ listing.variables.length }} 项已有变量</span></div>
      </UiCard>

      <UiCard v-if="changes.length" class="submission" accent="primary">
        <div class="submission-summary"><div><h2 class="section-title">待提交 {{ changes.length }} 项修改</h2><p class="row-reference">先预览修改，再输入管理员口令确认保存。</p></div>
          <UiButton v-if="!reviewed" variant="primary" icon="ArrowRight" :loading="busy" @click="submit">预览修改</UiButton>
        </div>
        <template v-if="reviewed">
          <ul class="change-preview"><li v-for="change in preview?.changes" :key="change.name"><span class="variable-name">{{ change.name }}</span><UiTag size="sm">{{ actionLabel(edits[change.name]!.action) }}</UiTag><span>{{ modeLabel(change.mode) }}</span><span v-if="change.references?.length">渠道：{{ change.references.join('、') }}</span><p v-if="change.mode === 'unknown'" class="row-reference">{{ usageHint }}</p><p v-if="change.warning" class="row-warning">{{ change.warning }}</p></li></ul>
          <div class="confirmation"><label>管理员当前口令<input v-model="password" type="password" autocomplete="current-password" placeholder="输入当前管理口令"></label><UiButton variant="primary" icon="Check" :loading="busy" :disabled="!password" @click="submit">确认并保存</UiButton></div>
        </template>
      </UiCard>
    </fieldset>

    <UiCard v-if="operation" class="operation-card" accent="success" role="status">
      <h2 class="section-title">{{ operation.phase === 'superseded' ? '已被后续修改替代' : '修改已保存' }}</h2>
      <p class="row-reference">以下为当前加载状态。操作 <span class="operation-id">{{ operation.id }}</span></p>
      <div v-for="(states, name) in operation.states" :key="name" class="operation-row"><span class="variable-name">{{ name }}</span><span v-for="(state, role) in states" :key="role">{{ role === 'bot' ? 'Bot' : 'Web' }}：{{ stateLabel(state) }}</span></div>
      <div class="consumer-states"><span v-for="(consumer, role) in operation.consumers" :key="role">{{ role === 'bot' ? 'Bot' : 'Web' }}：{{ consumer && Date.now() / 1000 - consumer.updated_at < 20 ? '运行中' : '等待进程确认' }}</span></div>
    </UiCard>
  </section>
</template>

<style scoped>
.environment-panel { display: flex; flex-direction: column; gap: var(--qq-gap-md); min-width: 0; }
.environment-panel :deep(.ui-page-header) { margin-bottom: 0; }
.environment-editor { border: 0; min-width: 0; display: flex; flex-direction: column; gap: var(--qq-gap-md); }
.variable-toolbar { display: flex; flex-wrap: wrap; align-items: center; gap: var(--qq-gap-md); padding: var(--qq-gap-md); }
.search-field { display: flex; align-items: center; position: relative; flex: 1; min-width: 200px; }
.search-field > .qq-ico, .search-field > svg { position: absolute; left: 11px; color: var(--qq-text-muted); pointer-events: none; }
.search-field input { width: 100%; padding-left: 34px; font-size: var(--qq-text-base); }
.create-field { display: flex; gap: var(--qq-gap-sm); flex: 0 1 370px; min-width: 0; }
.create-field input { min-width: 0; flex: 1; font-family: var(--qq-font-mono); font-size: var(--qq-text-base); }
.privacy-note { display: flex; gap: 6px; align-items: center; padding: 0 var(--qq-gap-md) var(--qq-gap-md); font-size: var(--qq-text-sm); color: var(--qq-text-muted); }
.privacy-note > svg { flex-shrink: 0; }
.variable-scroll { max-height: 64vh; overflow: auto; }
.variable-table { table-layout: fixed; }
.col-variable { width: 31%; } .col-value { width: 29%; } .col-status { width: 23%; } .col-actions { width: 17%; }
.variable-table thead { position: sticky; top: 0; z-index: 1; }
.variable-table th { font-size: var(--qq-text-xs); text-transform: none; border-bottom-width: 1px; }
.variable-table td { padding: 13px 16px; }
.variable-identity { display: flex; flex-wrap: wrap; align-items: center; gap: 6px; }
.variable-name { font-family: var(--qq-font-mono); font-size: var(--qq-text-sm); font-weight: 600; overflow-wrap: anywhere; }
.row-reference { margin-top: 4px; color: var(--qq-text-muted); font-size: var(--qq-text-sm); line-height: 1.6; overflow-wrap: anywhere; }
.row-warning { display: flex; align-items: flex-start; gap: 4px; margin-top: 6px; color: var(--qq-warn); font-size: var(--qq-text-sm); overflow-wrap: anywhere; }
.row-warning svg { flex-shrink: 0; margin-top: 3px; }
.secret-value { width: 100%; min-height: 36px; height: auto; resize: vertical; max-height: 160px; font-family: var(--qq-font-mono); font-size: var(--qq-text-base); -webkit-text-security: disc; }
.secret-value::placeholder { -webkit-text-security: none; font-family: var(--qq-font-base); color: var(--qq-text-quiet); }
.row-edited .secret-value { border-color: var(--qq-primary-border); }
.row-deleted .variable-name { text-decoration: line-through; color: var(--qq-text-muted); }
.row-actions { display: flex; flex-wrap: wrap; align-items: center; gap: 2px; }
.row-actions :deep(.ui-btn--sm) { padding-inline: 7px; }
.row-actions .delete-action { color: var(--qq-danger); }
.mode-tag { gap: 4px; }
.consumer-states { display: flex; flex-wrap: wrap; gap: 3px 12px; margin-top: 7px; font-size: var(--qq-text-xs); color: var(--qq-text-muted); }
.consumer-states > span { display: inline-flex; align-items: center; gap: 4px; }
.state-dot { width: 5px; height: 5px; flex-shrink: 0; border-radius: var(--qq-radius-full); background: var(--qq-warn); }
.state-dot--loaded { background: var(--qq-success); }
.list-footer { padding: 10px var(--qq-gap-md); border-top: 1px solid var(--qq-border); color: var(--qq-text-muted); font-size: var(--qq-text-sm); }
.submission { position: sticky; bottom: 0; z-index: 2; box-shadow: var(--qq-shadow-md); }
.submission-summary, .confirmation { display: flex; align-items: center; justify-content: space-between; gap: var(--qq-gap-md); flex-wrap: wrap; }
.change-preview { display: flex; flex-direction: column; gap: 8px; list-style: none; margin-block: var(--qq-gap-md); }
.change-preview li { display: flex; align-items: center; flex-wrap: wrap; gap: 6px 12px; padding: 8px 12px; background: var(--qq-surface-strong); border-radius: var(--qq-radius-sm); font-size: var(--qq-text-sm); color: var(--qq-text-muted); }
.change-preview .row-warning { flex-basis: 100%; margin-top: 0; }
.confirmation { padding-top: var(--qq-gap-md); border-top: 1px solid var(--qq-border); }
.confirmation label { display: flex; align-items: center; flex-wrap: wrap; gap: var(--qq-gap-sm); font-size: var(--qq-text-sm); color: var(--qq-text-muted); }
.confirmation input { min-width: 0; font-size: var(--qq-text-base); }
.operation-id { font-family: var(--qq-font-mono); overflow-wrap: anywhere; }
.operation-row { display: flex; flex-wrap: wrap; gap: 6px 16px; margin-top: var(--qq-gap-sm); font-size: var(--qq-text-sm); }
.error-note { display: flex; align-items: center; flex-wrap: wrap; gap: var(--qq-gap-sm); }
@media (max-width: 767px) {
  .variable-toolbar { gap: var(--qq-gap-sm); }
  .search-field, .create-field { flex-basis: 100%; }
  .variable-scroll { max-height: 62vh; }
  .variable-table colgroup, .variable-table thead { display: none; }
  .variable-table, .variable-table tbody { display: block; }
  .variable-table tr { display: flex; flex-direction: column; gap: var(--qq-gap-sm); padding: var(--qq-gap-md); border-bottom: 1px solid var(--qq-border); }
  .variable-table td { display: block; padding: 0; border: 0; background: transparent; }
  .variable-table tbody tr:nth-child(even) { background: var(--qq-table-stripe); }
  .variable-table tbody tr:hover td { background: transparent; }
  .variable-identity { justify-content: space-between; }
  .variable-name { min-width: 0; }
  .consumer-states { display: inline-flex; margin-left: 12px; margin-top: 0; }
  .row-actions { justify-content: flex-end; }
  .confirmation label, .confirmation input { width: 100%; }
}
</style>
