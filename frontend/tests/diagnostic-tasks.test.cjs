const assert = require('node:assert/strict')
const { readFileSync } = require('node:fs')
const path = require('node:path')
const vm = require('node:vm')
const { test } = require('node:test')
const ts = require('typescript')
const { ref, shallowRef, computed } = require('vue')

function compile(source) {
  const parsed = ts.createSourceFile('diagnostics.ts', source, ts.ScriptTarget.Latest, true)
  const code = parsed.statements.filter(statement => !ts.isImportDeclaration(statement))
    .map(statement => source.slice(statement.pos, statement.end)).join('\n')
  return ts.transpileModule(code, {
    compilerOptions: { target: ts.ScriptTarget.ES2022, module: ts.ModuleKind.CommonJS },
  }).outputText
}
function load(filename, bindings = {}, exported) {
  let requestSequence = 0
  let source = readFileSync(path.join(__dirname, '../src', filename), 'utf8')
  if (filename.endsWith('.vue')) source = source.match(/<script setup lang="ts">([\s\S]*?)<\/script>/)[1]
  return vm.runInNewContext(`${compile(source)};${exported ? `({${exported}})` : 'exports'}`, {
    exports: {}, ref, shallowRef, computed, setTimeout, Date, AbortSignal,
    crypto: { randomUUID: () => `diagnostic-id-${++requestSequence}` }, onMounted() {}, onUnmounted() {}, ...bindings,
  })
}
function operation(status, result = null, error = null, id = 'operation-1') {
  return { id, kind: 'probe', target_revision: 8, status, stage: status, result, error }
}
function task(read, observation = { intervalMs: 0, timeoutMs: 1000 }) {
  return load('composables/useDiagnosticTask.ts', { fetchDiagnosticOperation: read })
    .useDiagnosticTask(read, observation)
}
const normalize = value => JSON.parse(JSON.stringify(value))

test('diagnostics API submits explicit targets and returns 202 operations for later reads', async () => {
  const calls = []
  const api = load('api/diagnostics.ts', { request: async (url, options) => {
    calls.push([url, options])
    return operation('queued')
  } })
  const body = { source: 8, provider_id: 'p', model: 'owner/default', request_id: 'once' }
  assert.equal((await api.probeProviders(body)).status, 'queued')
  assert.equal((await api.runSampleRequest({ ...body, user_prompt: 'test' })).status, 'queued')
  await api.fetchDiagnosticOperation('operation-1')
  assert.deepEqual(JSON.parse(calls[0][1].body), body)
  assert.deepEqual(JSON.parse(calls[1][1].body), { ...body, user_prompt: 'test' })
  assert.equal(calls[2][0], '/api/llm-configuration/operations/operation-1')
  assert.equal(calls[2][1].method, undefined)
  assert.ok(calls.every(([, options]) => options.signal))
})

test('queued and running tasks never expose final output before succeeded', async () => {
  let release, submitted = 0
  const read = new Promise(resolve => { release = resolve })
  const state = task(async () => read)
  const running = state.start(async () => { submitted++; return operation('queued') })
  await new Promise(resolve => setTimeout(resolve, 1))
  assert.equal(state.operation.value.status, 'queued')
  assert.equal(state.result.value, null)
  release(operation('succeeded', { text: 'final', duration_ms: 42 }))
  await running
  assert.equal(state.result.value.text, 'final')
  assert.equal(state.loading.value, false)
  assert.equal(state.pending.value, false)
  assert.equal(submitted, 1)
})

test('only status reads retry automatically, including a running intermediate state', async () => {
  let submitted = 0, reads = 0
  const state = task(async () => {
    reads++
    if (reads === 1) throw new Error('temporary read failure')
    return reads === 2 ? operation('running') : operation('succeeded', { text: 'done' })
  })
  await state.start(async () => { submitted++; return operation('queued') })
  assert.equal(reads, 3)
  assert.equal(submitted, 1)
  assert.equal(state.result.value.text, 'done')
})

test('a lost submission response recovers the same bound request only on explicit resume', async () => {
  const sent = []
  const body = { source: 8, provider_id: 'p', model: 'default', request_id: 'same-id', user_prompt: 'original' }
  const state = task(async () => operation('succeeded', { text: 'once' }))
  await state.start(async () => {
    sent.push(normalize(body))
    if (sent.length === 1) throw new Error('response lost')
    return operation('queued')
  })
  assert.equal(sent.length, 1)
  assert.equal(state.pending.value, true)
  assert.equal(state.result.value, null)
  await state.resume()
  assert.deepEqual(sent, [body, body])
  assert.equal(state.result.value.text, 'once')
})

test('unconfirmed failure remains failed and never automatically submits another probe', async () => {
  let submitted = 0
  const state = task(async () => operation('failed', null, {
    code: 'probe_result_unconfirmed', message: 'Probe interrupted',
  }))
  await state.start(async () => { submitted++; return operation('queued') })
  assert.equal(state.result.value, null)
  assert.equal(state.operation.value.status, 'failed')
  assert.match(state.error.value, /interrupted/)
  assert.equal(submitted, 1)
})

test('an offline bot leaves queued work observable after a bounded wait without resubmission', async () => {
  let submitted = 0
  const state = task(async () => operation('queued'), { intervalMs: 1, timeoutMs: 5 })
  await state.start(async () => { submitted++; return operation('queued') })
  assert.equal(state.loading.value, false)
  assert.equal(state.pending.value, true)
  assert.equal(state.result.value, null)
  assert.match(state.error.value, /Bot/)
  assert.equal(submitted, 1)
})

test('sample component binds published revision, default model and user text across lost responses', async () => {
  const sent = []
  const result = { text: 'parsed', thinking_blocks: [{ text: 'thought' }], trace_calls: [{ id: 'trace' }], duration_ms: 42 }
  const state = load('components/diagnostics/DiagSampleCard.vue', {
    useDiagnosticTask: () => task(async () => operation('succeeded', result)),
    fetchProviders: async () => ({ revision: 8, providers: [{ id: 'p', default_model: 'second-model', models: ['first-model', 'second-model'] }] }),
    runSampleRequest: async body => {
      sent.push(normalize(body))
      if (sent.length === 1) throw new Error('response lost')
      return operation('queued')
    },
  }, 'loadProviders, sendSample, sample, sampleTask, sampleResult')
  await state.loadProviders()
  state.sample.value.user_prompt = 'original'
  await state.sendSample()
  state.sample.value.user_prompt = 'later edit'
  await state.sampleTask.resume()
  assert.deepEqual(sent[0], sent[1])
  assert.equal(sent[0].source, 8)
  assert.equal(sent[0].model, 'second-model')
  assert.equal(sent[0].request_id, 'diagnostic-id-1')
  assert.equal(sent[0].user_prompt, 'original')
  assert.deepEqual(normalize(state.sampleResult.value), result)
})

test('all-provider probe component queues each default model sequentially and displays final failures', async () => {
  const submitted = [], finished = []
  const state = load('components/diagnostics/DiagRuntimeOpsCard.vue', {
    useDiagnosticTask: () => task(async id => {
      finished.push(id)
      return operation('succeeded', { probe: { status: id === 'a' ? 'ok' : 'error', latency_ms: 5, error: id === 'b' ? 'timeout' : '' } }, null, id)
    }),
    fetchProviders: async () => ({ revision: 8, providers: [
      { id: 'a', default_model: 'a-default', models: ['a-first', 'a-default'] },
      { id: 'b', default_model: 'b-default', models: ['b-default'] },
    ] }),
    probeProviders: async body => {
      if (body.provider_id === 'b') assert.deepEqual(finished, ['a'])
      submitted.push(normalize(body))
      return operation('queued', null, null, body.provider_id)
    },
  }, 'runProbe, probeText, probeLoading')
  await state.runProbe()
  assert.deepEqual(submitted.map(body => [body.source, body.provider_id, body.model]), [
    [8, 'a', 'a-default'], [8, 'b', 'b-default'],
  ])
  assert.notEqual(submitted[0].request_id, submitted[1].request_id)
  assert.match(state.probeText.value, /a-default：正常/)
  assert.match(state.probeText.value, /b-default：失败.*timeout/)
  assert.equal(state.probeLoading.value, false)
})
