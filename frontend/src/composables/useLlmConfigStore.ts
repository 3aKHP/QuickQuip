import { computed, inject, provide, ref, shallowRef, watch, type InjectionKey } from 'vue'
import type * as apiModule from '../api/llmConfiguration'
import { configError, formatVersionLabel, isObject, isOperationFinished, parseConfigImport, type JsonObject, type JsonValue } from '../lib/llmConfig'

type Api = typeof apiModule

/** 轮询间隔（毫秒）：状态与进行中的任务共用一个节拍 */
const POLL_INTERVAL = 5000
/** 心跳超过该秒数视为过期（与后端 stale 口径一致） */
const HEARTBEAT_STALE_SECONDS = 20

// 客户端条目身份随对象展开保留；Symbol 属性不会进入交换 JSON。
const PROVIDER_EDIT_STATE = Symbol('llm-provider-edit-state')
interface ProviderEditState { saved: boolean }
type EditableProvider = JsonObject & { [PROVIDER_EDIT_STATE]?: ProviderEditState }

function providerEditState(provider: JsonObject): ProviderEditState {
  const entry = provider as EditableProvider
  return entry[PROVIDER_EDIT_STATE] ?? (entry[PROVIDER_EDIT_STATE] = { saved: false })
}

function providerEntries(document: JsonObject): JsonObject[] {
  return Array.isArray(document.providers) ? document.providers.filter(isObject) : []
}

function markProvidersSaved(document: JsonObject) {
  for (const provider of providerEntries(document)) providerEditState(provider).saved = true
}

/**
 * LLM 配置页状态层。视图与面板共享同一份草稿文档，
 * 保存/应用/冲突/轮询的编排逻辑集中在这里，组件只做展示与采集。
 */
export function createLlmConfigStore(api: Api) {
  const document = shallowRef<JsonObject | null>(null)
  const original = ref('')
  const revision = ref(0)
  const metadata = shallowRef<apiModule.ConfigMetadata>({})
  const status = shallowRef<apiModule.ConfigStatus | null>(null)
  const observedTime = ref(Date.now() / 1000)
  const statusReceivedAt = ref(observedTime.value)
  const history = ref<apiModule.ConfigSnapshot[]>([])
  const environment = shallowRef<Awaited<ReturnType<Api['fetchLlmConfigEnvironment']>> | null>(null)
  const validation = shallowRef<apiModule.ConfigValidation | null>(null)
  const diff = shallowRef<Awaited<ReturnType<Api['diffLlmConfiguration']>> | null>(null)
  const operation = shallowRef<apiModule.ConfigOperation | null>(null)
  const recentOperations = shallowRef<apiModule.ConfigOperation[]>([])
  const loading = ref(false)
  const saving = ref(false)
  const applying = ref(false)
  const mutating = ref(false)
  const error = ref('')
  const errorDetails = ref<unknown>(null)
  const pollError = ref('')
  const conflict = ref(false)

  let requestVersion = 0
  let pollTimer: ReturnType<typeof setTimeout> | undefined
  let clockTimer: ReturnType<typeof setInterval> | undefined
  let pollEpoch = 0
  let stopped = true
  let pendingProbe: { source: string; provider: string; model: string; requestId: string } | null = null
  let pendingApply: { revision: number; requestId: string } | null = null

  const busy = computed(() => loading.value || saving.value || applying.value || mutating.value)
  const dirty = computed(() => document.value !== null && JSON.stringify(document.value) !== original.value)
  const activeOperation = computed(() => !!operation.value && !isOperationFinished(operation.value.status))
  const bot = computed(() => status.value?.bot ?? null)
  const botStale = computed(() => {
    const current = bot.value
    if (!current) return true
    const heartbeat = typeof current.heartbeat_at === 'number' ? current.heartbeat_at : Date.parse(current.heartbeat_at) / 1000
    const observed = typeof current.observed_at === 'number' ? current.observed_at : Date.parse(current.observed_at) / 1000
    const elapsed = Math.max(0, observedTime.value - statusReceivedAt.value)
    return current.stale || !Number.isFinite(heartbeat) || !Number.isFinite(observed) || observed - heartbeat + elapsed > HEARTBEAT_STALE_SECONDS
  })
  /** 草稿与已发布版本是否一致（都不存在时视为一致） */
  const inSync = computed(() => status.value !== null && status.value.draft_revision === status.value.published_revision)

  /** 修订的版本标记；未知修订（无快照、非当前草稿）回退为提示文本 */
  function versionLabel(target: 'draft' | 'published' | number): string {
    const current = status.value
    if (target === 'draft') return formatVersionLabel(current?.draft_version.saved_at, current?.draft_version.note, '未记录时间')
    if (target === 'published') return formatVersionLabel(current?.published_version.saved_at, current?.published_version.note, '未发布')
    const snapshot = history.value.find(item => item.revision === target)
    if (snapshot) return formatVersionLabel(snapshot.saved_at ?? snapshot.created_at, snapshot.note, '历史版本')
    if (current?.draft_revision === target) return versionLabel('draft')
    return '历史版本'
  }

  const draftLabel = computed(() => versionLabel('draft'))
  const publishedLabel = computed(() => versionLabel('published'))
  const botLoadedLabel = computed(() => {
    const loaded = bot.value?.loaded_version
    return loaded ? formatVersionLabel(loaded.saved_at, loaded.note, '已加载') : '未报告'
  })

  function showError(cause: unknown) {
    const parsed = configError(cause)
    error.value = parsed.message
    errorDetails.value = parsed.details
    if (parsed.conflict) conflict.value = true
  }
  function clearError() { error.value = ''; errorDetails.value = null }

  /** 接受一份服务器草稿（初次载入/导入/恢复快照后调用） */
  function accept(data: apiModule.ConfigEnvelope) {
    markProvidersSaved(data.document)
    document.value = data.document
    revision.value = data.revision
    original.value = JSON.stringify(data.document)
    conflict.value = false
    validation.value = null
    diff.value = null
  }

  /** 面板局部编辑入口：替换文档的某个顶层 key */
  function updateSection(key: string, value: JsonValue) {
    if (key === 'providers' && Array.isArray(value)) value.filter(isObject).forEach(providerEditState)
    if (document.value) document.value = { ...document.value, [key]: value }
    validation.value = null
    diff.value = null
  }

  /** settings 子段编辑入口：只动 settings 下的一个 section */
  function updateSettingsSection(name: string, value: JsonValue) {
    if (!document.value) return
    const settings = isObject(document.value.settings) ? document.value.settings : {}
    updateSection('settings', { ...settings, [name]: value })
  }

  async function reload() {
    const token = ++requestVersion
    loading.value = true
    clearError()
    try {
      const [data, meta, snapshots] = await Promise.all([api.fetchLlmConfiguration(), api.fetchLlmConfigMetadata(), api.fetchLlmConfigHistory()])
      // 请求生命期与 store（模块级单例）对齐，不随视图重建取消；仅被更新的 reload 取代
      if (token !== requestVersion) return
      accept(data)
      metadata.value = meta
      history.value = snapshots.snapshots
    } catch (cause) {
      if (token === requestVersion) showError(cause)
    } finally {
      if (token === requestVersion) loading.value = false
    }
  }

  function acceptStatus(value: apiModule.ConfigStatus) {
    status.value = value
    statusReceivedAt.value = Date.now() / 1000
    observedTime.value = statusReceivedAt.value
  }

  async function refreshStatus() { acceptStatus(await api.fetchLlmConfigStatus()) }

  /** 历史列表只用于版本标记，刷新失败不打断主流程 */
  async function refreshHistory() {
    try { history.value = (await api.fetchLlmConfigHistory()).snapshots } catch { /* 保留旧列表 */ }
  }

  async function saveNote(source: 'draft' | 'published' | number, note: string) {
    mutating.value = true
    clearError()
    try {
      acceptStatus(await api.saveLlmConfigNote(String(source), note))
      await refreshHistory()
      return true
    } catch (cause) {
      showError(cause)
      return false
    } finally {
      mutating.value = false
    }
  }

  function canEditProviderId(provider: JsonObject): boolean {
    return (provider as EditableProvider)[PROVIDER_EDIT_STATE]?.saved !== true
  }

  async function save(note?: string) {
    if (!document.value || busy.value || !dirty.value || conflict.value) return false
    const token = requestVersion
    const sentProviderStates = providerEntries(document.value).map(providerEditState)
    const payload = JSON.parse(JSON.stringify(document.value)) as JsonObject
    const sent = JSON.stringify(payload)
    saving.value = true
    clearError()
    try {
      const result = await api.saveLlmConfiguration(payload, revision.value, note)
      if (token !== requestVersion) return false
      sentProviderStates.forEach(state => { state.saved = true })
      markProvidersSaved(result.document)
      revision.value = result.revision
      original.value = JSON.stringify(result.document)
      // 服务器规范化结果只替换本次提交的条目，后续新建条目保留编辑身份。
      const sameEntries = document.value !== null && providerEntries(document.value)
        .every((provider, index) => providerEditState(provider) === sentProviderStates[index])
      if (JSON.stringify(document.value) === sent && sameEntries) document.value = result.document
      await refreshStatus()
      return true
    } catch (cause) {
      showError(cause)
      return false
    } finally {
      saving.value = false
    }
  }

  async function apply(note?: string) {
    if (!document.value || busy.value || dirty.value || conflict.value || activeOperation.value) return false
    if (!pendingApply || pendingApply.revision !== revision.value) pendingApply = { revision: revision.value, requestId: crypto.randomUUID() }
    applying.value = true
    clearError()
    try {
      operation.value = await api.applyLlmConfiguration(pendingApply.revision, pendingApply.requestId, note)
      pendingApply = null
    } catch (cause) {
      showError(cause)
      return false
    } finally {
      applying.value = false
    }
    // 任务已入队；标记刷新失败交给轮询补齐，不把提交误报为失败
    await Promise.all([refreshStatus().catch(() => {}), refreshHistory()])
    return true
  }

  async function poll(epoch: number) {
    if (stopped || epoch !== pollEpoch) return
    try {
      const results = await Promise.all([
        api.fetchLlmConfigStatus(),
        operation.value && !isOperationFinished(operation.value.status) ? api.fetchLlmConfigOperation(operation.value.id) : Promise.resolve(null),
      ])
      if (stopped || epoch !== pollEpoch) return
      acceptStatus(results[0])
      if (results[1]) operation.value = results[1]
      pollError.value = ''
    } catch (cause) {
      if (!stopped && epoch === pollEpoch) pollError.value = configError(cause).message
    } finally {
      if (!stopped && epoch === pollEpoch) {
        pollTimer = setTimeout(() => poll(epoch), POLL_INTERVAL)
      }
    }
  }

  async function validate() {
    if (!document.value) return
    clearError()
    try { validation.value = await api.validateLlmConfiguration(document.value) } catch (cause) { showError(cause) }
  }

  /** 预览导入：错误统一由 store 的错误态展示，返回 null 表示失败 */
  async function previewImportText(text: string): Promise<apiModule.ImportPreview | null> {
    clearError()
    try {
      const candidate = parseConfigImport(text)
      return await api.previewLlmConfigImport(candidate, revision.value)
    } catch (cause) {
      showError(cause)
      return null
    }
  }

  async function commitImport(preview: apiModule.ImportPreview) {
    if (!preview.valid || busy.value) return false
    mutating.value = true
    clearError()
    try {
      accept(await api.importLlmConfiguration(preview.document, preview.expected_draft_revision))
      await refreshStatus()
      return true
    } catch (cause) {
      showError(cause)
      return false
    } finally {
      mutating.value = false
    }
  }

  async function restore(target: number) {
    mutating.value = true
    clearError()
    try {
      accept(await api.restoreLlmConfigSnapshot(target, revision.value))
      await refreshStatus()
      return true
    } catch (cause) {
      showError(cause)
      return false
    } finally {
      mutating.value = false
    }
  }

  async function cancelOperation() {
    if (!operation.value || operation.value.status !== 'queued') return
    mutating.value = true
    clearError()
    try { operation.value = await api.cancelLlmConfigOperation(operation.value.id) } catch (cause) { showError(cause) } finally { mutating.value = false }
  }

  async function loadDiff() {
    clearError()
    try { diff.value = await api.diffLlmConfiguration() } catch (cause) { showError(cause) }
  }

  async function loadOperations() {
    clearError()
    try { recentOperations.value = (await api.fetchLlmConfigOperations()).operations } catch (cause) { showError(cause) }
  }

  async function loadEnvironment() {
    clearError()
    try { environment.value = await api.fetchLlmConfigEnvironment() } catch (cause) { showError(cause) }
  }

  async function probe(source: string, provider: string, model: string) {
    if (busy.value || dirty.value || activeOperation.value || !provider || !model) return false
    if (!pendingProbe || pendingProbe.source !== source || pendingProbe.provider !== provider || pendingProbe.model !== model) {
      pendingProbe = { source, provider, model, requestId: crypto.randomUUID() }
    }
    mutating.value = true
    clearError()
    try {
      operation.value = await api.probeLlmConfiguration(pendingProbe.source, pendingProbe.provider, pendingProbe.model, pendingProbe.requestId)
      pendingProbe = null
      return true
    } catch (cause) {
      showError(cause)
      return false
    } finally {
      mutating.value = false
    }
  }

  /** 页面刷新后找回进行中任务（仅当前标签页会话内） */
  async function recoverOperation(storage: Pick<Storage, 'getItem'> = sessionStorage) {
    try {
      const id = storage.getItem('llm-config-operation')
      if (id) operation.value = await api.fetchLlmConfigOperation(id)
    } catch (cause) {
      pollError.value = configError(cause).message
    }
  }

  watch(operation, value => {
    try { if (value) sessionStorage.setItem('llm-config-operation', value.id) } catch { /* 浏览器可能禁用存储 */ }
  })

  /** 从任务列表找回未结束的任务（新标签页没有 sessionStorage 时兜底） */
  async function recoverActiveOperation() {
    try {
      const list = (await api.fetchLlmConfigOperations()).operations
      recentOperations.value = list
      if (operation.value && !isOperationFinished(operation.value.status)) return
      const pending = list.find(item => !isOperationFinished(item.status))
      if (pending) operation.value = pending
    } catch { /* 恢复失败不影响编辑 */ }
  }

  /**
   * 挂载入口。store 是模块级单例（视图随路由 query 重建时编辑态不丢），
   * 已有草稿时只刷新状态与任务，不覆盖本地编辑。
   */
  function start() {
    if (!stopped) return
    stopped = false
    const epoch = ++pollEpoch
    observedTime.value = Date.now() / 1000
    clockTimer = setInterval(() => { observedTime.value = Date.now() / 1000 }, 1000)
    if (document.value === null) void reload()
    void recoverOperation()
    void recoverActiveOperation()
    void poll(epoch)
  }
  /** 停止轮询；不进行作废——进行中的读取/保存属于 store，应继续完成 */
  function stop() {
    stopped = true
    ++pollEpoch
    clearTimeout(pollTimer)
    clearInterval(clockTimer)
  }

  return {
    document, original, revision, metadata, status, history, environment, validation, diff,
    operation, recentOperations, loading, saving, applying, mutating, error, errorDetails, pollError, conflict,
    observedTime, canEditProviderId, busy, dirty, activeOperation, bot, botStale, inSync,
    versionLabel, draftLabel, publishedLabel, botLoadedLabel, saveNote, refreshHistory,
    accept, updateSection, updateSettingsSection, reload, save, apply, validate, previewImportText, commitImport, restore,
    cancelOperation, loadDiff, loadOperations, loadEnvironment, probe, refreshStatus, recoverActiveOperation, start, stop,
    isOperationFinished,
  }
}

export type LlmConfigStore = ReturnType<typeof createLlmConfigStore>

let sharedStore: LlmConfigStore | null = null

/**
 * 页面级单例：App 以 route.fullPath 为组件 key，分区切换改 query 会重建视图；
 * store 持有未保存编辑，必须跨视图重建存活。
 */
export function getLlmConfigStore(api: Api): LlmConfigStore {
  if (!sharedStore) sharedStore = createLlmConfigStore(api)
  return sharedStore
}

export const LLM_CONFIG_STORE: InjectionKey<LlmConfigStore> = Symbol('llm-config-store')

export function provideLlmConfigStore(store: LlmConfigStore) {
  provide(LLM_CONFIG_STORE, store)
}

export function injectLlmConfigStore(): LlmConfigStore {
  const store = inject(LLM_CONFIG_STORE)
  if (!store) throw new Error('LLM 配置状态未注入：面板必须挂在 LlmConfigView 内')
  return store
}
