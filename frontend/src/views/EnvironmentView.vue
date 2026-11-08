<script setup lang="ts">
import { computed, onMounted, onUnmounted, reactive, ref } from 'vue'
import { onBeforeRouteLeave, useRoute } from 'vue-router'
import { loadEnvironment, previewEnvironment, saveEnvironment, getEnvironmentOperation } from '../api/environment'
import type { EnvironmentList, Edit, Operation } from '../api/environment'

const listing = ref<EnvironmentList | null>(null)
const edits = reactive<Record<string, Edit>>({})
const route = useRoute()
const search = ref(String(route.query.variable ?? ''))
const newName = ref('')
const password = ref('')
const error = ref('')
const busy = ref(false)
const reviewed = ref(false)
const preview = ref<Operation | null>(null)
const operation = ref<Operation | null>(null)
const requestId = ref(crypto.randomUUID())
const changes = computed(() => Object.values(edits))
const rows = computed(() => {
  const stored = listing.value?.variables ?? []
  const added = changes.value.filter(e => e.action === 'create').map(e => ({ name: e.name, assigned: false, mode: 'restart' as const, warning: '', references: [] as string[], states: {} as Record<string, string> }))
  return [...stored, ...added].filter(e => e.name.toLowerCase().includes(search.value.toLowerCase()))
})
function stateLabel(state: string) {
  return ({ loaded: '已加载', restart: '待重启', loading: '加载中', waiting: '等待启动或重新连接' } as Record<string, string>)[state] ?? state
}
async function refresh() {
  try { listing.value = await loadEnvironment() } catch (e) { error.value = String(e) }
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
  if (!/^[A-Za-z_][A-Za-z0-9_]*$/.test(name) || rows.value.some(r => r.name === name)) {
    error.value = '变量名无效或已存在'; return
  }
  edits[name] = { name, action: 'create', value: '' }; newName.value = ''; reviewed.value = false
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
      try { operation.value = await getEnvironmentOperation(operation.value.id) } catch (e) { error.value = String(e) }
    }
  }, 5000)
})
onUnmounted(() => { clearInterval(timer); window.removeEventListener('beforeunload', guard) })
</script>

<template>
  <section class="environment-panel">
    <h1>环境变量</h1>
    <p>管理根 .env。所有已有值均不回显；空白输入框表示保持原值。启动参数保存后需人工重启。</p>
    <p v-if="error" role="alert">{{ error }} <button @click="refresh">刷新状态（保留编辑）</button></p>
    <input v-model="search" aria-label="搜索变量" placeholder="搜索变量名">
    <div><datalist id="environment-suggestions"><option v-for="name in listing?.suggestions" :key="name" :value="name" /></datalist><input v-model="newName" list="environment-suggestions" aria-label="新变量名" placeholder="NEW_PROVIDER_API_KEY"><button @click="add">新增</button></div>
    <table>
      <thead><tr><th>变量</th><th>状态</th><th>新值</th><th>生效方式</th><th>操作</th></tr></thead>
      <tbody><tr v-for="row in rows" :key="row.name">
        <td>{{ row.name }}<small v-if="row.references?.length">渠道：{{ row.references.join('、') }}</small><p v-if="row.warning" class="warning">{{ row.warning }}</p></td>
        <td>{{ edits[row.name]?.action === 'delete' ? '待删除' : edits[row.name]?.action === 'create' ? '待新增' : edits[row.name] ? '已变更' : row.assigned ? '未变更（已赋值）' : '未赋值' }}</td>
        <td><textarea rows="2" class="secret-value" autocomplete="off" :aria-label="`${row.name} 新值`" :value="edits[row.name]?.value ?? ''" :disabled="edits[row.name]?.action === 'delete'" @input="edit(row.name, ($event.target as HTMLTextAreaElement).value)"></textarea></td>
        <td>{{ row.mode === 'restart' ? '启动时读取（可能有编排覆盖）' : '热更新' }}<small v-for="(state, role) in row.states" :key="role">{{ role }}：{{ stateLabel(state) }}</small></td>
        <td><button v-if="edits[row.name]?.action !== 'create'" @click="mark(row.name, 'empty')">设置空值</button> <button v-if="edits[row.name]?.action !== 'create'" @click="mark(row.name, 'delete')">删除</button> <button v-if="edits[row.name]" @click="undo(row.name)">撤销</button></td>
      </tr></tbody>
    </table>
    <div v-if="changes.length">
      <p>待提交 {{ changes.length }} 项。删除或覆写可能影响正在引用这些变量的渠道；高危设置允许保存。</p>
      <ul v-if="reviewed"><li v-for="change in preview?.changes" :key="change.name">{{ change.name }}：{{ change.mode === 'restart' ? '待重启' : '热更新' }} {{ change.warning }} <span v-if="change.references?.length">引用渠道：{{ change.references.join('、') }}</span></li></ul>
      <label v-if="reviewed">管理员当前口令 <input v-model="password" type="password" autocomplete="current-password"></label>
      <button :disabled="busy || (reviewed && !password)" @click="submit">{{ reviewed ? '确认并保存' : '预览修改' }}</button>
    </div>
    <div v-if="operation" role="status">
      <p>操作 {{ operation.id }}：{{ operation.phase === 'superseded' ? '已被后续修改替代，以下为当前加载状态' : '已保存' }}</p>
      <p v-for="(states, name) in operation.states" :key="name">{{ name }}：<span v-for="(state, role) in states" :key="role">{{ role }} {{ stateLabel(state) }} </span></p>
      <p v-for="(consumer, role) in operation.consumers" :key="role">{{ role }}：{{ consumer && Date.now() / 1000 - consumer.updated_at < 20 ? '运行中' : '等待进程确认' }}</p>
    </div>
  </section>
</template>

<style scoped>
.environment-panel { padding: 1.5rem; overflow-x: auto; }
table { width: 100%; margin-block: 1rem; border-collapse: collapse; }
th, td { text-align: left; padding: .7rem; border-bottom: 1px solid var(--border-color, #8884); }
textarea { -webkit-text-security: disc; padding: .5rem; }
input { padding: .5rem; max-width: 100%; }
button { margin: .2rem; padding: .4rem .6rem; }
.warning, [role=alert] { color: var(--color-warning, #b66b08); max-width: 30rem; }
</style>
