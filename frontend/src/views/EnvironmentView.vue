<script setup lang="ts">
import { computed, nextTick, onMounted, onUnmounted, reactive, ref, watch } from 'vue'
import { onBeforeRouteLeave, useRoute } from 'vue-router'
import { loadEnvironment, previewEnvironment, saveEnvironment, getEnvironmentOperation } from '../api/environment'
import type { DirectoryEntry, Edit, EnvironmentList, Operation, Variable } from '../api/environment'
import UiPageHeader from '../components/ui/UiPageHeader.vue'
import UiCard from '../components/ui/UiCard.vue'
import UiButton from '../components/ui/UiButton.vue'
import UiTag from '../components/ui/UiTag.vue'
import UiIcon from '../components/ui/UiIcon.vue'
import UiLoading from '../components/ui/UiLoading.vue'
import UiEmpty from '../components/ui/UiEmpty.vue'

type Row = DirectoryEntry & { local?: boolean }
type EditAction = Edit['action']

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
const domainFilter = ref('all')
const groupFilter = ref('all')
const scopeFilter = ref<'defined' | 'full'>('defined')
const expanded = ref<string | null>(null)
const changes = computed(() => Object.values(edits))
const hasDirectory = computed(() => Array.isArray(listing.value?.directory))
const taxonomy = computed(() => listing.value?.taxonomy ?? [])

const baseRows = computed<Row[]>(() => {
  if (hasDirectory.value) return listing.value?.directory ?? []
  return (listing.value?.variables ?? []).map(variable => ({
    ...variable, states: variable.states ?? {}, references: variable.references ?? [],
    groups: [], relations: [], sources: [], evidence_flags: {},
    allowed_actions: (variable.assigned ? ['replace', 'empty', 'delete'] : ['create']) as EditAction[],
  }))
})

const localRows = computed<Row[]>(() => changes.value
  .filter(e => e.action === 'create' && !baseRows.value.some(row => row.name === e.name))
  .map(e => {
    const description = reviewed.value ? preview.value?.changes.find(row => row.name === e.name) : undefined
    return { name: e.name, assigned: false, mode: description?.mode ?? 'unknown' as const,
      warning: description?.warning ?? '', references: description?.references ?? [],
      states: {} as Record<string, string>, groups: [], relations: [], sources: [],
      evidence_flags: {}, local: true,
      allowed_actions: ['create'] as EditAction[] }
  }))

const domainOptions = computed(() => [
  { id: 'all', label: '全部领域' },
  ...taxonomy.value.map(domain => ({ id: domain.id, label: domain.label })),
])
const groupOptions = computed(() => {
  const domain = taxonomy.value.find(item => item.id === domainFilter.value)
  const groups = domain ? domain.groups : taxonomy.value.flatMap(item => item.groups)
  return [{ id: 'all', label: '全部小组' }, ...groups.map(group => ({ id: group.id, label: group.label }))]
})

const rows = computed(() => {
  const needle = search.value.trim().toLowerCase()
  return [...baseRows.value, ...localRows.value].filter(row => {
    if (domainFilter.value !== 'all' && !row.groups.some(group => group.startsWith(`${domainFilter.value}.`))
      && !(domainFilter.value === 'unknown' && row.groups.includes('unknown.unidentified'))) return false
    if (groupFilter.value !== 'all' && !row.groups.includes(groupFilter.value)) return false
    if (hasDirectory.value && scopeFilter.value === 'defined' && !row.local) {
      const engaged = row.definition?.present || row.definition?.deletion_marker || row.relations.length > 0
      if (!engaged) return false
    }
    if (!needle) return true
    const haystack = [row.name, row.description ?? '', ...(row.references ?? []),
      ...row.relations.map(relation => `${relation.component} ${relation.object_id ?? ''}`)].join(' ').toLowerCase()
    return haystack.includes(needle)
  })
})

function stateLabel(state: string) {
  return ({ loaded: '已加载', synced: '快照已同步', restart: '待重启', loading: '加载中', waiting: '等待启动或重新连接' } as Record<string, string>)[state] ?? state
}
const modeLabel = (mode: Variable['mode']) => ({ hot: '热更新', credential: '热更新', restart: '重启生效', unknown: '按用途生效' })[mode]
const usageHint = '用于 Provider 密钥时，绑定渠道后可热更新。'
const actionLabels: Record<EditAction, string> = { create: '新增', replace: '覆写', empty: '设置空值', delete: '删除' }
const requiredActionLabels: Record<string, string> = {
  publish: '需发布草稿', next_task: '新任务生效', next_tieba_task: '下轮任务生效',
  apply: '需应用配置', restart_or_recreate: '需重启或重建', rebuild_image: '需重新构建镜像',
  redeploy: '需重新部署', edit_compose_then_recreate: '需修改编排模板',
  next_deployment: '下次部署生效', unknown: '待确认',
}
const scopeLabels: Record<string, string> = {
  draft: '草稿', published: '已发布', file: '配置文件', code: '代码', template: '打包模板',
}
const HOT_ACTIONS = new Set(['next_task', 'next_tieba_task'])
const BLOCKING_ACTIONS = new Set(['restart_or_recreate', 'apply', 'publish'])
const SLOW_ACTIONS = new Set(['rebuild_image', 'redeploy', 'edit_compose_then_recreate', 'next_deployment'])

function usageSummary(row: Row): string | null {
  const actions = new Set(row.relations.map(relation => relation.required_action))
  if (!actions.size) return null
  const hot = [...actions].some(action => HOT_ACTIONS.has(action))
  const blocking = [...actions].some(action => BLOCKING_ACTIONS.has(action))
  const slow = [...actions].some(action => SLOW_ACTIONS.has(action))
  const kinds = [hot, blocking, slow].filter(Boolean).length
  if (kinds > 1) return '部分用途需重启或重建'
  if (slow) return requiredActionLabels[[...actions][0]!] ?? null
  return null
}
function summaryChips(row: Row): string[] {
  return [...new Set(row.relations.map(relation => relation.required_action))]
    .map(action => requiredActionLabels[action] ?? action)
}
function definitionLabel(row: Row): string {
  const action = edits[row.name]?.action
  if (action === 'delete') return '待删除'
  if (action === 'create') return '待新增'
  if (action === 'empty') return '待清空'
  if (action) return '已变更'
  const definition = row.definition
  if (!definition) return row.assigned ? '已赋值' : '未赋值'
  if (definition.conflict) return '定义与删除冲突'
  if (definition.deletion_marker) return definition.present ? '定义与删除冲突' : '已删除标记'
  if (!definition.present) return '未定义'
  return ({ bare: '裸键', empty: '空值', nonempty: '已赋值' } as Record<string, string>)[definition.value_state] ?? definition.value_state
}
const actionLabel = (action: EditAction) => actionLabels[action]
function allowedActions(row: Row): EditAction[] {
  return row.allowed_actions ?? []
}
function editable(row: Row): boolean {
  return allowedActions(row).length > 0
}
function detailId(name: string) { return `environment-details-${name}` }
function toggleDetail(name: string) {
  expanded.value = expanded.value === name ? null : name
}
async function refresh() {
  refreshing.value = true
  try {
    listing.value = await loadEnvironment(true)
    error.value = ''
    if (changes.value.length) reviewed.value = false
  } catch (e) { error.value = String(e) }
  finally { refreshing.value = false }
}
function edit(row: Row, value: string) {
  const existing = edits[row.name]?.action
  const action: EditAction = existing === 'create' ? 'create'
    : allowedActions(row).includes('create') && !allowedActions(row).includes('replace') ? 'create' : 'replace'
  if (!value && action !== 'create') { delete edits[row.name] } else { edits[row.name] = { name: row.name, action, value } }
  reviewed.value = false
}
function mark(name: string, action: EditAction) {
  edits[name] = { name, action }; reviewed.value = false
}
async function focusRow(name: string) {
  await nextTick()
  document.getElementById(`environment-value-${name}`)?.focus()
}
function add() {
  const name = newName.value.trim()
  if (!/^[A-Za-z_][A-Za-z0-9_]*$/.test(name) || Boolean(edits[name])) {
    error.value = '变量名无效或已存在'; return
  }
  const existing = baseRows.value.find(row => row.name === name)
  if (existing) {
    if (!allowedActions(existing).includes('create')) { error.value = '变量已存在且不可从此处修改'; return }
    search.value = name; domainFilter.value = 'all'; groupFilter.value = 'all'; scopeFilter.value = 'full'
    newName.value = ''
    void focusRow(name); return
  }
  edits[name] = { name, action: 'create', value: '' }; newName.value = ''; reviewed.value = false
  search.value = name; domainFilter.value = 'all'; groupFilter.value = 'all'
  void focusRow(name)
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
watch(() => route.query.variable, value => {
  const name = String(value ?? '').trim()
  if (name) {
    search.value = name
    const target = baseRows.value.find(row => row.name === name)
    if (target) expanded.value = name
  }
})
let timer: ReturnType<typeof setInterval> | undefined
onMounted(() => {
  void refresh().then(() => {
    const name = String(route.query.variable ?? '')
    if (name) {
      const target = baseRows.value.find(row => row.name === name)
      if (target) expanded.value = name
      else if (!listing.value?.variables.some(row => row.name === name)) newName.value = name
    }
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
            <input v-model="search" type="search" aria-label="搜索变量" placeholder="搜索变量名、用途或消费者">
          </div>
          <select v-if="hasDirectory" v-model="domainFilter" aria-label="变量领域" class="filter-select">
            <option v-for="option in domainOptions" :key="option.id" :value="option.id">{{ option.label }}</option>
          </select>
          <select v-if="hasDirectory" v-model="groupFilter" aria-label="使用小组" class="filter-select">
            <option v-for="option in groupOptions" :key="option.id" :value="option.id">{{ option.label }}</option>
          </select>
          <select v-if="hasDirectory" v-model="scopeFilter" aria-label="目录范围" class="filter-select">
            <option value="defined">已定义与引用</option>
            <option value="full">完整目录</option>
          </select>
          <div class="create-field">
            <datalist id="environment-suggestions"><option v-for="name in listing.suggestions" :key="name" :value="name" /></datalist>
            <input v-model="newName" list="environment-suggestions" aria-label="新变量名" placeholder="NEW_PROVIDER_API_KEY" spellcheck="false" @keyup.enter="add">
            <UiButton icon="Plus" variant="primary" @click="add">新增</UiButton>
          </div>
        </div>
        <div v-if="listing.directory_errors?.length" class="privacy-note directory-errors" role="status">
          <UiIcon name="AlertTriangle" :size="14" />
          <span>部分目录来源暂不可用（{{ listing.directory_errors.map(item => item.component).join('、') }}），相关详情可能不完整。</span>
        </div>
        <div class="privacy-note"><UiIcon name="Lock" :size="14" /><span>已有值不回显，留空保持原值。启动参数保存后需重启。</span></div>
        <div v-if="rows.length" class="variable-scroll">
          <table class="variable-table">
            <colgroup><col class="col-variable"><col class="col-value"><col class="col-status"><col class="col-actions"></colgroup>
            <thead><tr><th scope="col">变量</th><th scope="col">新值</th><th scope="col">生效与加载</th><th scope="col">操作</th></tr></thead>
            <tbody>
              <template v-for="row in rows" :key="row.name">
                <tr :class="{ 'row-edited': edits[row.name], 'row-deleted': edits[row.name]?.action === 'delete' }">
                  <td>
                    <div class="variable-identity">
                      <UiButton size="sm" variant="ghost" class="detail-toggle"
                        :aria-expanded="expanded === row.name" :aria-controls="detailId(row.name)"
                        :aria-label="`${expanded === row.name ? '收起' : '展开'} ${row.name} 详情`"
                        @click="toggleDetail(row.name)">{{ expanded === row.name ? '收起' : '详情' }}</UiButton>
                      <span class="variable-name">{{ row.name }}</span>
                      <UiTag size="sm" :variant="edits[row.name]?.action === 'delete' ? 'danger' : edits[row.name] ? 'warn' : row.definition?.present || row.assigned ? 'success' : 'info'">{{ definitionLabel(row) }}</UiTag>
                    </div>
                    <p v-if="row.description" class="row-reference">{{ row.description }}</p>
                    <p v-if="row.groups.length && hasDirectory" class="row-reference row-groups">{{ row.groups.map(group => taxonomy.flatMap(domain => domain.groups).find(item => item.id === group)?.label ?? group).join(' · ') }}</p>
                    <p v-if="row.references?.length" class="row-reference">渠道：{{ row.references.join('、') }}</p>
                    <p v-if="row.warning" class="row-warning"><UiIcon name="AlertTriangle" :size="13" />{{ row.warning }}</p>
                  </td>
                  <td class="value-cell">
                    <textarea v-if="editable(row)" :id="`environment-value-${row.name}`" class="secret-value" :rows="Math.min(4, (edits[row.name]?.value ?? '').split('\n').length)" autocomplete="off" spellcheck="false" :aria-label="`${row.name} 新值`" :placeholder="edits[row.name]?.action === 'delete' ? '已标记删除' : edits[row.name]?.action === 'empty' ? '将保存为空值' : allowedActions(row).includes('create') && !allowedActions(row).includes('replace') ? '输入值以创建定义' : '输入新值以覆写'" :value="edits[row.name]?.value ?? ''" :disabled="edits[row.name]?.action === 'delete'" @input="edit(row, ($event.target as HTMLTextAreaElement).value)"></textarea>
                    <p v-else class="row-reference">由编排或进程内部提供，不在此创建或修改。</p>
                  </td>
                  <td>
                    <UiTag size="sm" class="mode-tag" :variant="row.mode === 'restart' ? 'warn' : 'info'"><UiIcon :name="row.mode === 'restart' ? 'RotateCw' : row.mode === 'unknown' ? 'Info' : 'Zap'" :size="12" />{{ modeLabel(row.mode) }}</UiTag>
                    <UiTag v-if="usageSummary(row)" size="sm" variant="warn">{{ usageSummary(row) }}</UiTag>
                    <p v-else-if="row.relations.length" class="row-reference">{{ summaryChips(row).join('、') }}</p>
                    <p v-if="row.mode === 'unknown' && !row.relations.length" class="row-reference">{{ usageHint }}</p>
                    <div v-if="!edits[row.name] && Object.keys(row.states).length" class="consumer-states"><span v-for="(state, role) in row.states" :key="role"><i :class="['state-dot', { 'state-dot--loaded': state === 'loaded' || state === 'synced' }]" />{{ role === 'bot' ? 'Bot' : role === 'web' ? 'Web' : role }} {{ stateLabel(state) }}</span></div>
                    <p v-else-if="edits[row.name]" class="row-reference">保存后确认加载状态</p>
                  </td>
                  <td><div class="row-actions">
                    <UiButton v-if="edits[row.name]?.action !== 'create' && allowedActions(row).includes('empty')" size="sm" variant="ghost" @click="mark(row.name, 'empty')">设置空值</UiButton>
                    <UiButton v-if="edits[row.name]?.action !== 'create' && allowedActions(row).includes('delete')" size="sm" variant="ghost" class="delete-action" icon="Trash2" @click="mark(row.name, 'delete')">删除</UiButton>
                    <UiButton v-if="edits[row.name]" size="sm" variant="ghost" icon="RotateCcw" @click="undo(row.name)">撤销</UiButton>
                  </div></td>
                </tr>
                <tr v-if="expanded === row.name" class="detail-row">
                  <td colspan="4">
                    <div :id="detailId(row.name)" class="detail-region" role="region" :aria-label="`${row.name} 详情`">
                      <section class="detail-section">
                        <h3>消费关系</h3>
                        <p v-if="!row.relations.length" class="row-reference">未发现已确认的消费者；这不代表没有任何使用。</p>
                        <dl v-for="(relation, index) in row.relations" :key="index" class="detail-dl">
                          <dt>消费者</dt><dd>{{ relation.component }}{{ relation.object_id ? `（${relation.object_id}）` : '' }}</dd>
                          <dt>配置阶段</dt><dd>{{ scopeLabels[relation.config_scope] ?? relation.config_scope }}{{ relation.enabled === false ? ' · 已停用' : relation.enabled === true ? '' : '' }}</dd>
                          <dt>字段</dt><dd class="mono">{{ relation.field_path }}</dd>
                          <dt>引用</dt><dd class="mono">{{ relation.raw_expression }}<span v-if="relation.name_kind === 'computed_name'">（名称经配置计算，未确认）</span></dd>
                          <dt>目标</dt><dd>{{ relation.target_service }} · {{ relation.target_kind }}<span v-if="relation.target_name && relation.target_name !== row.name" class="mono"> → {{ relation.target_name }}</span></dd>
                          <dt>生效</dt><dd>{{ requiredActionLabels[relation.required_action] ?? relation.required_action }} · 确认状态：未观测</dd>
                        </dl>
                      </section>
                      <section class="detail-section">
                        <h3>来源与传递</h3>
                        <p v-if="!row.sources.length" class="row-reference">暂无来源记录。</p>
                        <dl v-for="(source, index) in row.sources" :key="index" class="detail-dl">
                          <dt>来源</dt><dd>{{ source.kind }}<span v-if="source.context"> · {{ source.context }}</span><span v-if="source.evidence_scope === 'compose_template'"> · 公开模板声明，实际部署未观测</span></dd>
                          <dt>位置</dt><dd class="mono">{{ source.path }}</dd>
                          <dt v-if="source.override_kind">覆盖方式</dt><dd v-if="source.override_kind">{{ source.override_kind }}</dd>
                        </dl>
                      </section>
                      <section class="detail-section">
                        <h3>加载与后续动作</h3>
                        <div v-if="Object.keys(row.states).length" class="consumer-states"><span v-for="(state, role) in row.states" :key="role"><i :class="['state-dot', { 'state-dot--loaded': state === 'loaded' || state === 'synced' }]" />{{ role === 'bot' ? 'Bot' : role === 'web' ? 'Web' : role }} {{ stateLabel(state) }}（进程快照）</span></div>
                        <p v-else class="row-reference">无进程快照记录。</p>
                        <p v-if="summaryChips(row).length" class="row-reference">后续动作：{{ summaryChips(row).join('、') }}。</p>
                        <p class="row-reference">快照同步、配置装载与上游可用是不同事实；此处不宣称远端已生效。</p>
                      </section>
                    </div>
                  </td>
                </tr>
              </template>
            </tbody>
          </table>
        </div>
        <UiEmpty v-else icon="Search" title="没有匹配的变量" description="调整筛选或搜索条件，或在上方新增变量。" />
        <div class="list-footer">显示 {{ rows.length }} 项<span v-if="hasDirectory"> · 完整目录 {{ (listing.directory ?? []).length }} 项</span><span v-else-if="search.trim()"> · 共 {{ listing.variables.length }} 项已有变量</span></div>
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
      <h2 class="section-title">{{ operation.phase === 'superseded' ? '已被后续修改替代' : '根 .env 修改已保存' }}</h2>
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
.filter-select { flex: 0 1 auto; min-width: 120px; max-width: 180px; }
.create-field { display: flex; gap: var(--qq-gap-sm); flex: 0 1 370px; min-width: 0; }
.create-field input { min-width: 0; flex: 1; font-family: var(--qq-font-mono); font-size: var(--qq-text-base); }
.privacy-note { display: flex; gap: 6px; align-items: center; padding: 0 var(--qq-gap-md) var(--qq-gap-md); font-size: var(--qq-text-sm); color: var(--qq-text-muted); }
.privacy-note > svg { flex-shrink: 0; }
.directory-errors { color: var(--qq-warn); padding-top: var(--qq-gap-sm); }
.variable-scroll { max-height: 64vh; overflow: auto; }
.variable-table { table-layout: fixed; }
.col-variable { width: 31%; } .col-value { width: 29%; } .col-status { width: 23%; } .col-actions { width: 17%; }
.variable-table thead { position: sticky; top: 0; z-index: 1; }
.variable-table th { font-size: var(--qq-text-xs); text-transform: none; border-bottom-width: 1px; }
.variable-table td { padding: 13px 16px; }
.variable-identity { display: flex; flex-wrap: wrap; align-items: center; gap: 6px; }
.variable-name { font-family: var(--qq-font-mono); font-size: var(--qq-text-sm); font-weight: 600; overflow-wrap: anywhere; }
.detail-toggle { padding-inline: 7px; }
.row-reference { margin-top: 4px; color: var(--qq-text-muted); font-size: var(--qq-text-sm); line-height: 1.6; overflow-wrap: anywhere; }
.row-groups { margin-top: 2px; font-size: var(--qq-text-xs); }
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
.detail-row > td { padding: 0 16px 16px; }
.detail-region { display: grid; gap: var(--qq-gap-md); padding: var(--qq-gap-sm) var(--qq-gap-md); background: var(--qq-surface-strong); border: 1px solid var(--qq-border); border-radius: var(--qq-radius-sm); }
.detail-section h3 { margin: 0 0 6px; font-size: var(--qq-text-sm); font-weight: 600; }
.detail-dl { display: grid; grid-template-columns: 5.5em minmax(0, 1fr); gap: 2px 10px; margin: 0 0 8px; font-size: var(--qq-text-xs); }
.detail-dl dt { color: var(--qq-text-muted); }
.detail-dl dd { margin: 0; min-width: 0; overflow-wrap: anywhere; }
.detail-dl .mono, .mono { font-family: var(--qq-font-mono); }
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
  .search-field, .create-field, .filter-select { flex-basis: 100%; max-width: none; }
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
  .detail-dl { grid-template-columns: 1fr; }
}
</style>
