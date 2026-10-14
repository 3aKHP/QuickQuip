const assert = require('node:assert/strict')
const { readFileSync } = require('node:fs')
const path = require('node:path')
const vm = require('node:vm')
const { test } = require('node:test')
const ts = require('typescript')
const { ref, computed, watch, shallowRef } = require('vue')

function compile(source) {
  const parsed = ts.createSourceFile('component.ts', source, ts.ScriptTarget.Latest, true)
  const code = parsed.statements.filter(statement => !ts.isImportDeclaration(statement))
    .map(statement => source.slice(statement.pos, statement.end)).join('\n')
  return ts.transpileModule(code, { compilerOptions: { target: ts.ScriptTarget.ES2022, module: ts.ModuleKind.CommonJS } }).outputText
}
const library = vm.runInNewContext(`${compile(readFileSync(path.join(__dirname, '../src/lib/llmConfig.ts'), 'utf8'))};exports`, { exports: {}, TextEncoder })
function deferred() { let resolve, reject; const promise = new Promise((yes, no) => { resolve = yes; reject = no }); return { promise, resolve, reject } }

function createStore(api, bindings = {}) {
  const source = readFileSync(path.join(__dirname, '../src/composables/useLlmConfigStore.ts'), 'utf8')
  const module = vm.runInNewContext(`${compile(source)};exports`, {
    exports: {}, ref, computed, watch, shallowRef, setTimeout, clearTimeout, setInterval, clearInterval,
    configError: library.configError, formatVersionLabel: library.formatVersionLabel, isObject: library.isObject,
    isOperationFinished: library.isOperationFinished, parseConfigImport: library.parseConfigImport,
    crypto: { randomUUID: () => 'same-request-id' },
    sessionStorage: { getItem: () => null, setItem: () => {} },
    inject: () => undefined, provide: () => {},
    ...bindings,
  })
  return module.createLlmConfigStore(api)
}

const initial = { revision: 5, document: { format_version: 1, providers: [], settings: { runtime: { enabled: false } } } }
const version = { saved_at: 1760428800, note: '' }
const status = { schema_version: 3, draft_revision: 6, draft_version: version, published_revision: 4, published_version: version, bot: null }
const normalized = value => JSON.parse(JSON.stringify(value))

test('save acknowledges sent configuration while later edits remain dirty', async () => {
  const write = deferred(); let sent
  const store = createStore({ saveLlmConfiguration: (document, revision) => { sent = { document, revision }; return write.promise }, fetchLlmConfigStatus: async () => status })
  store.accept(structuredClone(initial))
  store.updateSettingsSection('runtime', { enabled: true })
  const saving = store.save()
  store.updateSettingsSection('runtime', { enabled: false, history_limit: 20 })
  write.resolve({ revision: 6, document: sent.document })
  await saving
  assert.equal(sent.revision, 5)
  assert.equal(sent.document.settings.runtime.enabled, true)
  assert.equal(store.document.value.settings.runtime.enabled, false)
  assert.equal(store.document.value.settings.runtime.history_limit, 20)
  assert.equal(store.revision.value, 6)
  assert.equal(store.dirty.value, true)
})

test('409 leaves edits and revision intact and blocks apply', async () => {
  let applyCalls = 0
  const store = createStore({
    saveLlmConfiguration: async () => { throw { status: 409, data: { detail: { message: 'Draft changed', field_path: 'expected_draft_revision' } } } },
    applyLlmConfiguration: async () => { applyCalls++ },
  })
  store.accept(structuredClone(initial))
  store.updateSettingsSection('runtime', { enabled: true })
  await store.save(); await store.apply()
  assert.equal(store.conflict.value, true)
  assert.equal(store.document.value.settings.runtime.enabled, true)
  assert.equal(store.revision.value, 5)
  assert.equal(applyCalls, 0)
  assert.match(store.error.value, /expected_draft_revision/)
})

test('apply retries a lost HTTP response with same request id and never reports success at submission', async () => {
  const calls = []
  const store = createStore({
    applyLlmConfiguration: async (...args) => { calls.push(args); if (calls.length === 1) throw new Error('connection interrupted'); return { id: 'operation-1', status: 'queued', target_revision: 5 } },
  })
  store.accept(structuredClone(initial)); await store.apply(); await store.apply()
  assert.deepEqual(normalized(calls), [[5, 'same-request-id', null], [5, 'same-request-id', null]])
  assert.equal(store.operation.value.status, 'queued')
  await store.apply()
  assert.equal(calls.length, 2)
})

test('imports use previewed normalized content and bound revision', async () => {
  let imported
  const document = { format_version: 1, providers: [] }
  const store = createStore({
    previewLlmConfigImport: async (candidate, expected) => ({ valid: true, document, expected_draft_revision: expected, warnings: [], dependencies: [], changes: [] }),
    importLlmConfiguration: async (...args) => { imported = args; return { revision: 6, document } },
    fetchLlmConfigStatus: async () => status,
  })
  store.accept(structuredClone(initial))
  const preview = await store.previewImportText(JSON.stringify(document))
  await store.commitImport(preview)
  assert.deepEqual(normalized(imported), [document, 5])
  assert.equal(store.revision.value, 6)
  assert.equal(store.dirty.value, false)
  assert.equal(store.operation.value, null)
})

test('JSON import enforces UTF-8 byte limit and object shape', () => {
  assert.throws(() => library.parseConfigImport('[]'), /JSON/)
  assert.throws(() => library.parseConfigImport('{"prompt":"' + '中'.repeat(400000) + '"}'), /1 MiB/)
  assert.deepEqual(normalized(library.parseConfigImport('{"enabled":false,"limit":0,"params":{}}')), { enabled: false, limit: 0, params: {} })
})

test('pending apply conflict never blocks continued draft editing', async () => {
  let saved = false
  const store = createStore({
    applyLlmConfiguration: async () => { throw { status: 409, data: { code: 'operation_conflict', message: 'Apply already pending', details: { id: 'other-operation' } } } },
    saveLlmConfiguration: async document => { saved = true; return { revision: 6, document } },
    fetchLlmConfigStatus: async () => status,
  })
  store.accept(structuredClone(initial)); await store.apply()
  assert.equal(store.conflict.value, false)
  store.updateSettingsSection('runtime', { enabled: true })
  await store.save()
  assert.equal(saved, true)
})

function controlledClock(initialTime = 400000) {
  let now = initialTime, sequence = 0
  const timers = new Map()
  function schedule(callback, delay, interval) {
    const id = ++sequence
    timers.set(id, { callback, at: now + delay, interval })
    return id
  }
  return {
    bindings: {
      Date: class extends Date { static now() { return now } },
      setTimeout: (callback, delay) => schedule(callback, delay, 0),
      clearTimeout: id => timers.delete(id),
      setInterval: (callback, delay) => schedule(callback, delay, delay),
      clearInterval: id => timers.delete(id),
    },
    count: interval => [...timers.values()].filter(timer => !!timer.interval === interval).length,
    advance(milliseconds) {
      const target = now + milliseconds
      while (true) {
        const next = [...timers.entries()].filter(([, timer]) => timer.at <= target).sort((a, b) => a[1].at - b[1].at)[0]
        if (!next) break
        const [id, timer] = next
        now = timer.at
        if (timer.interval) timer.at += timer.interval
        else timers.delete(id)
        timer.callback()
      }
      now = target
    },
  }
}
const flushRequests = () => new Promise(resolve => setImmediate(resolve))

test('Bot heartbeat uses server observation and ages while the next status request hangs', async () => {
  const clock = controlledClock() // 浏览器比服务器快 300 秒。
  const hanging = deferred()
  let requests = 0
  const store = createStore({
    fetchLlmConfigStatus: () => ++requests === 1 ? Promise.resolve({ bot: { heartbeat_at: 100, observed_at: 100, stale: false } }) : hanging.promise,
    fetchLlmConfigOperations: async () => ({ operations: [] }),
  }, clock.bindings)
  store.accept(structuredClone(initial))
  store.start()
  await flushRequests()
  assert.equal(store.botStale.value, false)
  clock.advance(5000)
  assert.equal(requests, 2)
  clock.advance(15000)
  assert.equal(store.botStale.value, false)
  clock.advance(1000)
  assert.equal(store.botStale.value, true)
  store.stop()
  assert.equal(clock.count(true), 0)
  assert.equal(clock.count(false), 0)
  hanging.resolve({ bot: { heartbeat_at: 110, observed_at: 110, stale: false } })
  await flushRequests()
  assert.equal(store.status.value.bot.heartbeat_at, 100)
  assert.equal(clock.count(false), 0)
})

test('poll sessions discard previous responses and own one clock and one polling chain', async () => {
  const clock = controlledClock()
  const previous = deferred(), current = deferred()
  let requests = 0
  const store = createStore({
    fetchLlmConfigStatus: () => ++requests === 1 ? previous.promise : requests === 2 ? current.promise : Promise.resolve({ bot: null, draft_revision: 9 }),
    fetchLlmConfigOperations: async () => ({ operations: [] }),
  }, clock.bindings)
  store.accept(structuredClone(initial))
  store.start()
  store.start()
  assert.equal(requests, 1)
  assert.equal(clock.count(true), 1)
  store.stop()
  store.start()
  current.resolve({ bot: null, draft_revision: 8 })
  await flushRequests()
  assert.equal(clock.count(false), 1)
  previous.resolve({ bot: null, draft_revision: 7 })
  await flushRequests()
  assert.equal(store.status.value.draft_revision, 8)
  assert.equal(clock.count(false), 1)
  clock.advance(5000)
  await flushRequests()
  assert.equal(requests, 3)
  assert.equal(clock.count(false), 1)
  store.stop()
  assert.equal(clock.count(true), 0)
  assert.equal(clock.count(false), 0)
  clock.advance(10000)
  assert.equal(requests, 3)
})

test('restart with existing draft keeps local edits (section switch remount must not reload)', async () => {
  let loads = 0
  const store = createStore({
    fetchLlmConfiguration: async () => { loads++; return structuredClone(initial) },
    fetchLlmConfigMetadata: async () => ({}),
    fetchLlmConfigHistory: async () => ({ snapshots: [] }),
    fetchLlmConfigStatus: async () => status,
    fetchLlmConfigOperations: async () => ({ operations: [] }),
  })
  store.accept(structuredClone(initial))
  store.updateSettingsSection('runtime', { enabled: true })
  store.stop()
  store.start()
  await new Promise(resolve => setTimeout(resolve, 10))
  assert.equal(loads, 0)
  assert.equal(store.dirty.value, true)
  assert.equal(store.document.value.settings.runtime.enabled, true)
  store.stop()
})

test('operations list recovers an unfinished apply in a fresh session', async () => {
  const store = createStore({
    fetchLlmConfigOperations: async () => ({ operations: [{ id: 'op-remote', kind: 'apply', status: 'queued', target_revision: 9 }] }),
  })
  await store.recoverActiveOperation()
  assert.equal(store.operation.value.id, 'op-remote')
  assert.equal(store.activeOperation.value, true)
})

test('finished operations do not resurrect as active', async () => {
  const store = createStore({
    fetchLlmConfigOperations: async () => ({ operations: [{ id: 'op-old', kind: 'apply', status: 'succeeded', target_revision: 9 }] }),
  })
  await store.recoverActiveOperation()
  assert.equal(store.operation.value, null)
})

/* ── 组件脚本级测试：与 editor-races.test.cjs 同款 vm 编译 ── */

function componentScript(filename, bindings, exportsList) {
  const source = readFileSync(path.join(__dirname, '../src', filename), 'utf8')
  const script = source.match(/<script setup lang="ts">([\s\S]*?)<\/script>/)[1]
  return vm.runInNewContext(`${compile(script)};({${exportsList}})`, bindings)
}

function providersPanel(store) {
  return componentScript('components/llm-config/ProvidersPanel.vue', {
    computed, ref, watch, onMounted() {}, structuredClone, toast() {}, confirm: () => true,
    injectLlmConfigStore: () => store,
    PARAM_LABELS: library.PARAM_LABELS, PARAM_SOURCE_LABELS: library.PARAM_SOURCE_LABELS,
    PROTOCOL_LABELS: library.PROTOCOL_LABELS, fieldTemplate: library.fieldTemplate,
    isObject: library.isObject, providerEnvVars: library.providerEnvVars,
  }, 'selected,addProvider,removeProvider,onIdInput,current,patch,fingerprintOptions')
}

test('new provider identity survives panel remount and index shifts, then locks after save', async () => {
  const saving = deferred()
  let sent
  const store = createStore({
    saveLlmConfiguration: document => { sent = document; return saving.promise },
    fetchLlmConfigStatus: async () => status,
  })
  store.accept({ revision: 5, document: { providers: [{ id: 'existing-a' }, { id: 'existing-b' }] } })
  const panel = providersPanel(store)
  panel.addProvider()
  panel.onIdInput('new-draft')
  panel.selected.value = 0
  panel.removeProvider()
  const remounted = providersPanel(store)
  remounted.selected.value = 1
  remounted.onIdInput('new-complete')
  assert.equal(store.document.value.providers[1].id, 'new-complete')
  remounted.selected.value = 0
  remounted.onIdInput('existing-renamed')
  assert.equal(store.document.value.providers[0].id, 'existing-b')
  remounted.selected.value = 1
  const pending = store.save()
  saving.resolve({ revision: 6, document: sent })
  await pending
  remounted.onIdInput('saved-renamed')
  assert.equal(store.document.value.providers[1].id, 'new-complete')
  const afterSave = providersPanel(store)
  afterSave.selected.value = 1
  afterSave.onIdInput('saved-renamed-again')
  assert.equal(store.document.value.providers[1].id, 'new-complete')
})

test('typing an existing provider ID prefix keeps the new entry editable across remount and saving', async () => {
  const saving = deferred()
  let sent
  const store = createStore({
    saveLlmConfiguration: document => { sent = document; return saving.promise },
    fetchLlmConfigStatus: async () => status,
  })
  store.accept({ revision: 5, document: { providers: [{ id: 'openai' }] } })
  const panel = providersPanel(store)
  panel.addProvider()
  for (const value of ['o', 'op', 'ope', 'open', 'opena', 'openai']) panel.onIdInput(value)
  const remounted = providersPanel(store)
  remounted.selected.value = 1
  for (const value of ['openai-', 'openai-2']) remounted.onIdInput(value)
  assert.equal(store.document.value.providers[1].id, 'openai-2')
  const pending = store.save()
  remounted.patch({ proxy: 'http://later-edit.example.test' })
  saving.resolve({ revision: 6, document: structuredClone(sent) })
  await pending
  assert.equal(store.document.value.providers[1].proxy, 'http://later-edit.example.test')
  assert.equal(store.dirty.value, true)
  remounted.onIdInput('openai-3')
  assert.equal(store.document.value.providers[1].id, 'openai-2')
  assert.equal(store.document.value.providers[0].id, 'openai')
  assert.equal(Object.getOwnPropertySymbols(sent.providers[1]).length, 0)
  assert.deepEqual(normalized(sent.providers[1]), { ...normalized(library.fieldTemplate('providers')), id: 'openai-2' })
})

for (const [scenario, proxy] of [
  ['identical bytes', ''],
  ['later proxy edit', 'http://replacement.example.test'],
]) {
  test(`save preserves a new replacement entry with ${scenario}`, async () => {
    const saving = deferred()
    let sent
    const store = createStore({
      saveLlmConfiguration: document => { sent = document; return saving.promise },
      fetchLlmConfigStatus: async () => status,
    })
    store.accept({ revision: 5, document: { providers: [] } })
    const panel = providersPanel(store)
    panel.addProvider()
    panel.onIdInput('submitted')
    const pending = store.save()
    panel.removeProvider()
    panel.addProvider()
    panel.onIdInput('submitted')
    panel.patch({ proxy })
    saving.resolve({ revision: 6, document: sent })
    await pending
    panel.onIdInput('replacement')
    assert.equal(store.document.value.providers[0].id, 'replacement')
    assert.equal(store.document.value.providers[0].proxy, proxy)
    assert.equal(store.dirty.value, true)
  })
}

function paramsEditor(modelValue, metadata = {}) {
  const props = { modelValue, metadata, styleProfiles: [] }
  const script = componentScript('components/llm-config/ParamsEditor.vue', {
    computed, ref, structuredClone, toast() {},
    defineProps: () => props, withDefaults: value => value,
    defineEmits: () => (event, value) => { props.modelValue = value },
    PARAM_GROUPS: library.PARAM_GROUPS, PARAM_GROUP_LABELS: library.PARAM_GROUP_LABELS, PARAM_LABELS: library.PARAM_LABELS,
  }, 'isOverridden,valueFor,initialValue,setParam,clearParam,overrideParam,groups')
  return { ...script, props }
}

test('parameter override distinguishes explicit zero false empty object and inherited null', () => {
  const editor = paramsEditor(
    { temperature: 1, stream_enabled: true, extra_body: { nested: 1 } },
    { temperature: { type: 'number', inherit: true, nullable: true, minimum: 0, default: 0.8 } },
  )
  editor.setParam('temperature', 0); editor.setParam('stream_enabled', false); editor.setParam('extra_body', {})
  assert.deepEqual(normalized(editor.props.modelValue), { temperature: 0, stream_enabled: false, extra_body: {} })
  assert.equal(editor.isOverridden('temperature'), true)
  editor.clearParam('temperature')
  assert.equal(editor.props.modelValue.temperature, null)
  assert.equal(editor.isOverridden('temperature'), false)
  assert.equal(editor.initialValue('temperature'), 0.8)
})

test('parameter groups follow metadata availability and count overrides', () => {
  const editor = paramsEditor({ temperature: 0.5 }, { temperature: { type: 'number', default: 0.8 }, stream_enabled: { type: 'boolean', default: true } })
  const groups = editor.groups.value
  const names = groups.flatMap(group => group.names)
  assert.deepEqual(normalized(names.sort()), ['stream_enabled', 'temperature'])
  assert.equal(groups.find(group => group.names.includes('temperature')).overridden, 1)
})

function cascadeEditor(modelValue, providers) {
  const props = { modelValue, providers }
  const script = componentScript('components/llm-config/CascadeEditor.vue', {
    computed, defineProps: () => props, withDefaults: value => value,
    defineEmits: () => (event, value) => { props.modelValue = value },
    isObject: library.isObject,
  }, 'move,addDefault,addExplicit,modelsOf')
  return { ...script, props }
}

test('route candidate reorder preserves slash model identities and dynamic default', () => {
  const providers = [{ id: 'p', models: [{ model: 'org/model' }] }]
  const editor = cascadeEditor([{ provider_id: 'p', model: 'org/model' }, '@default'], providers)
  editor.move(1, -1)
  assert.deepEqual(normalized(editor.props.modelValue), ['@default', { provider_id: 'p', model: 'org/model' }])
  editor.addDefault()
  assert.equal(editor.props.modelValue[2], '@default')
  assert.deepEqual(editor.modelsOf('p'), ['org/model'])
})

test('cascade addExplicit seeds first provider and its first model', () => {
  const providers = [{ id: 'p1', models: [{ model: 'a' }, { model: 'b' }] }]
  const editor = cascadeEditor([], providers)
  editor.addExplicit()
  assert.deepEqual(normalized(editor.props.modelValue), [{ provider_id: 'p1', model: 'a' }])
})

test('epoch chain constraint reports first violation in plain language', () => {
  const base = { epoch_context_tokens: 8000, epoch_cold_target_tokens: 4000, epoch_cold_trigger_tokens: 5000, epoch_hot_target_tokens: 32000, epoch_cap_tokens: 64000 }
  assert.equal(library.epochChainError(base), '')
  assert.match(library.epochChainError({ ...base, epoch_cold_target_tokens: 5000 }), /冷态压缩目标/)
  assert.match(library.epochChainError({ ...base, epoch_hot_target_tokens: 64000 }), /热态压缩目标/)
})

test('provider environment variable collection covers key name and inline references', () => {
  const vars = library.providerEnvVars({ api_key_env: 'MAIN_KEY', base_url: 'https://x.test/${TOKEN}', headers: { Authorization: 'bearer ${AUTH}' }, proxy: '', fallback_urls: ['https://y.test/${FALLBACK_KEY}'] })
  assert.deepEqual(normalized(vars.sort()), ['AUTH', 'FALLBACK_KEY', 'MAIN_KEY', 'TOKEN'])
})

/* ── F2/F6 回归：导入预览的迟到响应与错误展示 ── */

function exchangePanel(fakeStore) {
  return componentScript('components/llm-config/ExchangePanel.vue', {
    ref, computed, watch, shallowRef, confirm: () => true,
    toast: fakeStore.toast || (() => {}),
    injectLlmConfigStore: () => fakeStore,
    describeChange: library.describeChange, isObject: library.isObject,
    URL: { createObjectURL: () => '', revokeObjectURL: () => {} },
  }, 'importText,preview,previewing,doPreview,doCommit,readFile')
}

function fakeStore(overrides = {}) {
  return {
    revision: ref(5), dirty: ref(false), conflict: ref(false), busy: ref(false),
    document: ref({ providers: [] }),
    previewImportText: async () => null,
    commitImport: async () => true,
    ...overrides,
  }
}

test('late preview response for replaced input never becomes confirmable', async () => {
  const slow = deferred()
  const store = fakeStore({ previewImportText: () => slow.promise })
  const panel = exchangePanel(store)
  panel.importText.value = '{"format_version":1,"triggers":{"default_prefix":"/ai"}}'
  const pending = panel.doPreview()
  // 用户在响应返回前改为另一份配置：旧请求必须作废
  panel.importText.value = '{"format_version":1,"triggers":{"default_prefix":"/newer-input"}}'
  slow.resolve({ valid: true, document: {}, changes: [], warnings: [], expected_draft_revision: 5 })
  await pending
  assert.equal(panel.preview.value, null)
  assert.equal(panel.previewing.value, false)
})

test('preview failure surfaces through the store error path and clears previewing', async () => {
  const store = fakeStore({ previewImportText: async () => null })
  const panel = exchangePanel(store)
  panel.importText.value = 'not json'
  await panel.doPreview()
  assert.equal(panel.preview.value, null)
  assert.equal(panel.previewing.value, false)
})

test('commit refuses a preview whose draft base revision went stale', async () => {
  const toasts = []
  let commitCalls = 0
  const store = fakeStore({
    commitImport: async () => { commitCalls++; return true },
    toast: (message) => toasts.push(message),
  })
  const panel = exchangePanel(store)
  panel.preview.value = { valid: true, document: {}, changes: [], warnings: [], expected_draft_revision: 5 }
  store.revision.value = 6
  await panel.doCommit()
  assert.equal(commitCalls, 0)
  assert.match(toasts[0] || '', /重新校验/)
  assert.equal(panel.preview.value, null)
})

/* ── F4 回归：枚举下拉选项 ── */

function settingField(props) {
  return componentScript('components/llm-config/SettingField.vue', {
    computed, controlSequence: 0, defineProps: () => props, withDefaults: value => value, defineEmits: () => () => {},
    ENUM_OPTION_LABELS: library.ENUM_OPTION_LABELS,
  }, 'kind,selectOptions')
}

test('enum fields render options from metadata with Chinese labels', () => {
  const field = settingField({
    label: '启用方式', modelValue: 'append', enumKey: 'tools.enabled_mode',
    meta: { type: 'string', enum: ['append', 'replace'] },
  })
  assert.equal(field.kind.value, 'select')
  const options = field.selectOptions.value
  assert.equal(options.length, 2)
  assert.equal(options[0].value, 'append')
  assert.match(options[0].label, /追加/)
  assert.equal(options[1].label.includes('replace'), false)
})

test('enum options fall back to raw values when no dictionary entry exists', () => {
  const field = settingField({ label: '档位', modelValue: 'low', meta: { type: 'string', enum: ['', 'low', 'high'] } })
  assert.deepEqual(normalized(field.selectOptions.value.map(o => o.value)), ['', 'low', 'high'])
  assert.equal(field.selectOptions.value[0].label, '（空）')
})

/* ── F9 回归：数组差异人话化 ── */

test('providers array diff summarizes add remove and model level changes', () => {
  const before = [
    { id: 'a', protocol: 'openai', models: [{ model: 'm1', vision: true }], parameters: {} },
    { id: 'b', protocol: 'gemini', models: [], parameters: {} },
  ]
  const after = [
    { id: 'a', protocol: 'openai', models: [{ model: 'm1', vision: false }, { model: 'm2' }], parameters: { temperature: 0.5 } },
    { id: 'c', protocol: 'claude', models: [{ model: 'x' }] },
  ]
  const { title, lines } = library.describeChange('providers', before, after)
  assert.equal(title, '渠道')
  const text = lines.join('\n')
  assert.match(text, /新增渠道 c/)
  assert.match(text, /删除渠道 b/)
  assert.match(text, /渠道 a：新增模型 m2/)
  assert.match(text, /渠道 a · 模型 m1：支持图片 true → false/)
  assert.match(text, /渠道 a：温度 跟随上层 → 0\.5/)
})

test('pricing and route diffs use identity and chain wording', () => {
  const pricing = library.describeChange('pricing',
    [{ provider_id: 'q', model: 'm', input_per_mtok: 1, output_per_mtok: 2 }],
    [{ provider_id: 'q', model: 'm', input_per_mtok: 3, output_per_mtok: 2 }, { provider_id: 'p', model: 'n', input_per_mtok: 0, output_per_mtok: 0 }])
  assert.match(pricing.lines.join('\n'), /新增价格 p · n/)
  assert.match(pricing.lines.join('\n'), /价格 q · m：输入价 1 → 3/)
  const routes = library.describeChange('routes.weekly_report', ['@default'], [{ provider_id: 'p', model: 'm' }])
  assert.match(routes.lines[0], /每周报告：默认渠道 ⇒ p\/m/)
})

test('scalar diff without structure keeps the field path as title and no lines', () => {
  const summary = library.describeChange('settings.runtime.reply_split_threshold_chars', 800, 1000)
  assert.equal(summary.title, 'settings.runtime.reply_split_threshold_chars')
  assert.deepEqual(normalized(summary.lines), [])
})

/* ── R1 回归：请求过程中视图卸载（分区切换）不作废进行中的读取/保存 ── */

test('in-flight reload survives view teardown: loading clears and document lands', async () => {
  const slow = deferred()
  const store = createStore({
    fetchLlmConfiguration: () => slow.promise,
    fetchLlmConfigMetadata: async () => ({}),
    fetchLlmConfigHistory: async () => ({ snapshots: [] }),
    fetchLlmConfigStatus: async () => status,
    fetchLlmConfigOperations: async () => ({ operations: [] }),
  })
  store.start()
  await new Promise(resolve => setTimeout(resolve, 0))
  assert.equal(store.loading.value, true)
  store.stop()
  slow.resolve(structuredClone(initial))
  await new Promise(resolve => setTimeout(resolve, 0))
  assert.equal(store.loading.value, false)
  assert.equal(store.revision.value, 5)
  assert.equal(store.document.value.settings.runtime.enabled, false)
})

test('in-flight save acknowledged after teardown: revision accepted, no phantom conflict', async () => {
  const write = deferred(); let sent
  const store = createStore({
    saveLlmConfiguration: (document, revision) => { sent = { document, revision }; return write.promise },
    fetchLlmConfigStatus: async () => status,
  })
  store.accept(structuredClone(initial))
  store.updateSettingsSection('runtime', { enabled: true })
  const saving = store.save()
  store.stop()
  write.resolve({ revision: 6, document: sent.document })
  await saving
  assert.equal(store.revision.value, 6)
  assert.equal(store.dirty.value, false)
  assert.equal(store.conflict.value, false)
})

/* ── R2 回归：参数与价格差异展示新旧值 ── */

test('model parameter diff shows Chinese label with old and new values', () => {
  const before = [{ id: 'p', models: [{ model: 'm', parameters: { temperature: 0.123451 } }], parameters: {} }]
  const after = [{ id: 'p', models: [{ model: 'm', parameters: { temperature: 0.987659 } }], parameters: {} }]
  const { lines } = library.describeChange('providers', before, after)
  assert.ok(lines.some(line => line.includes('温度') && line.includes('0.123451') && line.includes('0.987659')))
})

test('provider parameter clear and price change carry values', () => {
  const cleared = library.describeChange('providers',
    [{ id: 'p', models: [], parameters: { temperature: 0.7 } }],
    [{ id: 'p', models: [], parameters: { temperature: null } }])
  assert.match(cleared.lines[0], /温度 0\.7 → 跟随上层/)
  const pricing = library.describeChange('pricing',
    [{ provider_id: null, model: 'm', input_per_mtok: 2 }],
    [{ provider_id: null, model: 'm', input_per_mtok: 3 }])
  assert.match(pricing.lines[0], /输入价 2 → 3/)
})

test('order-only changes remain reviewable', () => {
  const { lines } = library.describeChange('providers',
    [{ id: 'a', models: [] }, { id: 'b', models: [] }],
    [{ id: 'b', models: [] }, { id: 'a', models: [] }])
  assert.match(lines.join('\n'), /渠道顺序：a、b → b、a/)
})

/* ── R3 回归：导入预览的 before 标签是「当前草稿」而非「已发布」 ── */

test('import preview labels draft source while publish diff labels published', () => {
  const exchange = readFileSync(path.join(__dirname, '../src/components/llm-config/ExchangePanel.vue'), 'utf8')
  const publish = readFileSync(path.join(__dirname, '../src/components/llm-config/PublishPanel.vue'), 'utf8')
  assert.ok(exchange.includes('当前草稿：'))
  assert.ok(!exchange.includes('已发布：'))
  assert.ok(publish.includes('已发布'))
})


test('provider Profile options follow protocol and selection persists through draft save', async () => {
  let sent
  const store = createStore({
    saveLlmConfiguration: async document => { sent = structuredClone(document); return { revision: 6, document } },
    fetchLlmConfigStatus: async () => status,
  })
  const document = structuredClone(initial.document)
  document.providers = [{ id: 'test', protocol: 'openai', client_fingerprint: 'default', models: [] }]
  store.accept({ revision: 5, document })
  store.metadata.value = { client_fingerprints: [
    { id: 'default', label: 'Default', protocols: ['openai', 'claude'] },
    { id: 'quickquip', label: 'QuickQuip', protocols: ['openai', 'claude'] },
    { id: 'custom', label: 'Custom', protocols: ['claude'] },
  ] }
  const panel = providersPanel(store)
  assert.deepEqual(normalized(panel.fingerprintOptions.value.map(entry => entry.value)), ['default', 'quickquip'])
  panel.patch({ client_fingerprint: 'quickquip' })
  store.updateSettingsSection('runtime', { enabled: false, client_cluster: 'synthetic-cluster' })
  await store.save()
  assert.equal(sent.providers[0].client_fingerprint, 'quickquip')
  assert.equal(sent.settings.runtime.client_cluster, 'synthetic-cluster')
  panel.patch({ protocol: 'claude' })
  assert.deepEqual(normalized(panel.fingerprintOptions.value.map(entry => entry.value)), ['default', 'quickquip', 'custom'])
})

test('version labels render saved time and note instead of numeric revisions', async () => {
  const ts = 1760428800
  const formatted = library.formatVersionLabel(ts, '切换主模型', '未发布')
  assert.match(formatted, /^\d{4}-\d{2}-\d{2} \d{2}:\d{2} \(切换主模型\)$/)
  assert.equal(library.formatVersionLabel(null, '', '未发布'), '未发布')
  assert.equal(library.formatVersionLabel(null, '仅备注', '未记录时间'), '未记录时间 (仅备注)')

  let savedNoteArgs = null
  const live = { saved_at: ts - 3600, note: '线上稳定版' }
  const store = createStore({
    fetchLlmConfigStatus: async () => ({
      ...status, draft_revision: 5, draft_version: { saved_at: ts, note: '草稿备注' },
      published_revision: 4, published_version: live,
      bot: { boot_id: 'b', loaded_revision: 4, loaded_version: live, heartbeat_at: ts, observed_at: ts, stale: false, components: {} },
    }),
    fetchLlmConfigHistory: async () => ({ snapshots: [{ revision: 4, created_at: ts, saved_at: ts - 3600, note: '线上稳定版' }] }),
    saveLlmConfigNote: async (source, note) => {
      savedNoteArgs = { source, note }
      return { ...status, draft_revision: 5, draft_version: { saved_at: ts, note }, published_revision: 4, published_version: live, bot: null }
    },
  })
  await store.refreshStatus()
  await store.refreshHistory()
  assert.match(store.draftLabel.value, /\(草稿备注\)$/)
  assert.match(store.publishedLabel.value, /\(线上稳定版\)$/)
  assert.match(store.botLoadedLabel.value, /\(线上稳定版\)$/)
  assert.equal(store.versionLabel(4), store.publishedLabel.value)
  assert.equal(store.versionLabel(5), store.draftLabel.value)
  assert.equal(store.versionLabel(2), '历史版本')

  assert.equal(await store.saveNote(4, '新备注'), true)
  assert.deepEqual(savedNoteArgs, { source: '4', note: '新备注' })
})

test('LlmConfigView consolidates sidebar into 6 core modules and preserves legacy query aliases', () => {
  const viewSource = readFileSync(path.join(__dirname, '../src/views/LlmConfigView.vue'), 'utf8')
  for (const key of ['providers', 'conversation', 'tools', 'reports', 'pricing', 'publish']) {
    assert.ok(viewSource.includes(`key: '${key}'`), `expected module key ${key}`)
  }
  for (const legacy of ['general', 'retry', 'epoch', 'context', 'styles', 'mcp', 'skills', 'routes', 'exchange']) {
    assert.ok(viewSource.includes(`${legacy}:`), `expected alias for ${legacy}`)
  }
  assert.ok(viewSource.includes("context: { section: 'conversation', subTab: 'memory' }"))
})


function pricingPanel(store) {
  return componentScript('components/llm-config/PricingPanel.vue', {
    computed, ref, structuredClone, injectLlmConfigStore: () => store,
    fieldTemplate: library.fieldTemplate, isObject: library.isObject,
  }, 'groups,missing,incomplete,orphans,dupes,addMissing,copyTargets,copyTo,patchNumber,modelOptions')
}

test('pricing panel bills per provider model and never defaults new rows to free', () => {
  const store = createStore({})
  store.accept({ revision: 1, document: {
    providers: [
      { id: 'a', models: [{ model: 'm' }, { model: 'n' }] },
      { id: 'b', models: [{ model: 'm' }] },
    ],
    pricing: [
      { provider_id: 'a', model: 'm', input_per_mtok: 1, output_per_mtok: 2, cache_read_per_mtok: null, cache_write_per_mtok: null },
      { provider_id: 'a', model: 'gone', input_per_mtok: 1, output_per_mtok: 2 },
    ],
  } })
  const panel = pricingPanel(store)
  assert.deepEqual(normalized(panel.missing.value), [{ provider: 'a', model: 'n' }, { provider: 'b', model: 'm' }])
  assert.equal(panel.orphans.value.length, 1)
  assert.deepEqual(normalized(panel.modelOptions(panel.groups.value[0], store.document.value.pricing[0])), ['m', 'n'])
  assert.deepEqual(normalized(panel.copyTargets(store.document.value.pricing[0])), ['b'])

  panel.copyTo(store.document.value.pricing[0], { target: { value: 'b' } })
  assert.deepEqual(normalized(store.document.value.pricing[2]), { ...normalized(store.document.value.pricing[0]), provider_id: 'b' })
  assert.deepEqual(normalized(panel.copyTargets(store.document.value.pricing[0])), [])

  panel.addMissing(panel.missing.value)
  const added = store.document.value.pricing[3]
  assert.equal(added.provider_id, 'a')
  assert.equal(added.model, 'n')
  assert.equal(added.input_per_mtok, null)
  assert.equal(panel.incomplete.value.length, 1)

  panel.patchNumber(3, 'input_per_mtok', { target: { value: '0.50' } })
  panel.patchNumber(3, 'output_per_mtok', { target: { value: '0' } })
  assert.equal(store.document.value.pricing[3].input_per_mtok, 0.5)
  assert.equal(panel.incomplete.value.length, 0)
  const input = { value: '-1' }
  panel.patchNumber(3, 'output_per_mtok', { target: input })
  assert.equal(store.document.value.pricing[3].output_per_mtok, 0)
  assert.equal(input.value, '0')
  panel.patchNumber(3, 'cache_read_per_mtok', { target: { value: '' } })
  assert.equal(store.document.value.pricing[3].cache_read_per_mtok, null)
})

test('deleting a provider also drops its prices', () => {
  const store = createStore({})
  store.accept({ revision: 1, document: {
    providers: [{ id: 'a', models: [] }, { id: 'b', models: [] }],
    pricing: [{ provider_id: 'a', model: 'm' }, { provider_id: 'b', model: 'm' }],
  } })
  const panel = providersPanel(store)
  panel.selected.value = 0
  panel.removeProvider()
  assert.deepEqual(normalized(store.document.value.pricing), [{ provider_id: 'b', model: 'm' }])
  assert.deepEqual(store.document.value.providers.map(p => p.id), ['b'])
})

test('renaming an unsaved provider carries its prices', () => {
  const store = createStore({})
  store.accept({ revision: 1, document: { providers: [], pricing: [] } })
  const panel = providersPanel(store)
  panel.addProvider()
  panel.onIdInput('draft-id')
  store.updateSection('pricing', [{ provider_id: 'draft-id', model: 'm' }])
  panel.onIdInput('final-id')
  assert.deepEqual(normalized(store.document.value.pricing), [{ provider_id: 'final-id', model: 'm' }])
  assert.equal(store.document.value.providers[0].id, 'final-id')
})
