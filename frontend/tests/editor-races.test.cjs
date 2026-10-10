const assert = require('node:assert/strict')
const { readFileSync } = require('node:fs')
const path = require('node:path')
const vm = require('node:vm')
const { test } = require('node:test')
const ts = require('typescript')
const { ref, computed, watch, reactive, nextTick } = require('vue')

// Exercise the components' actual script setup through the normal TS transform.
// Only API/browser boundaries are replaced; request ordering remains production code.
function componentScript(filename, bindings, exports) {
  const source = readFileSync(path.join(__dirname, '../src', filename), 'utf8')
  const script = source.match(/<script setup lang="ts">([\s\S]*?)<\/script>/)[1]
  const parsed = ts.createSourceFile(filename, script, ts.ScriptTarget.Latest, true)
  const withoutImports = parsed.statements
    .filter(statement => !ts.isImportDeclaration(statement))
    .map(statement => script.slice(statement.pos, statement.end))
    .join('\n')
  const compiled = ts.transpileModule(withoutImports, {
    compilerOptions: { target: ts.ScriptTarget.ES2022 },
  }).outputText
  return vm.runInNewContext(`${compiled}\n;({${exports}})`, {
    ref, computed, watch, onMounted() {}, defineExpose() {},
    defineEmits: () => () => {}, confirm: () => true, toast() {}, ...bindings,
  })
}

function deferred() {
  let resolve, reject
  const promise = new Promise((yes, no) => { resolve = yes; reject = no })
  return { promise, resolve, reject }
}

function skillEditor(fetchSkillFile, saveSkillFile = async () => {}) {
  const props = reactive({ skillName: 'demo', resources: [] })
  const state = componentScript('components/skills/SkillFileEditor.vue', {
    defineProps: () => props, fetchSkillFile, saveSkillFile,
  }, 'openPath, onSave, reset, filePath, content, original, loading, saving, dirty')
  return { ...state, props }
}

test('late file reads never change the selected file or its save payload', async () => {
  const reads = { 'a.md': deferred(), 'b.py': deferred() }
  let saved
  const editor = skillEditor((name, file) => reads[file].promise, async (...args) => { saved = args })
  const a = editor.openPath('a.md')
  const b = editor.openPath('b.py')
  reads['b.py'].resolve({ content: 'B source' })
  await b
  reads['a.md'].resolve({ content: 'A source' })
  await a
  assert.equal(editor.content.value, 'B source')
  editor.content.value = 'B edited'
  await editor.onSave()
  assert.equal(JSON.stringify(saved), JSON.stringify(['demo', 'b.py', 'B edited']))
})

test('late errors and reads from a previous Skill cannot reset the current editor', async () => {
  const oldRead = deferred()
  const editor = skillEditor((name) => name === 'demo' ? oldRead.promise : Promise.resolve({ content: 'new Skill' }))
  const old = editor.openPath('a.md')
  editor.props.skillName = 'other'
  await nextTick()
  await editor.openPath('b.md')
  oldRead.reject(new Error('old file unavailable'))
  await old
  assert.equal(editor.filePath.value, 'b.md')
  assert.equal(editor.content.value, 'new Skill')
  assert.equal(editor.loading.value, false)
})

test('edits made during save remain dirty until those bytes are saved', async () => {
  const write = deferred()
  const editor = skillEditor(async () => ({ content: 'original' }), () => write.promise)
  await editor.openPath('a.md')
  editor.content.value = 'sent bytes'
  const saving = editor.onSave()
  editor.content.value = 'new unsaved bytes'
  write.resolve({ ok: true })
  await saving
  assert.equal(editor.original.value, 'sent bytes')
  assert.equal(editor.content.value, 'new unsaved bytes')
  assert.equal(editor.dirty.value, true)
})

function configEditor(api) {
  return componentScript('views/ConfigView.vue', {
    fetchLlmEffort: async () => ({ providers: [] }), ...api,
  }, 'load, onEffortChange, save, currentKey, content, originalContent, dirty')
}

test('effort completion never fills or saves the new config with LLM text', async () => {
  const write = deferred()
  let saved
  const editor = configEditor({
    saveLlmEffort: () => write.promise,
    fetchConfig: async key => ({ content: `${key} source` }),
    saveConfig: async (...args) => { saved = args; return {} },
  })
  await editor.load('llm')
  const operation = editor.onEffortChange({ id: 'demo' }, { target: { value: 'high' } })
  await editor.load('games')
  write.resolve({ ok: true })
  await operation
  assert.equal(editor.content.value, 'games source')
  editor.content.value = 'games edited'
  await editor.save()
  assert.equal(JSON.stringify(saved), JSON.stringify(['games', 'games edited']))
})

test('effort refresh preserves text typed while its save is pending', async () => {
  const write = deferred()
  const editor = configEditor({
    saveLlmEffort: () => write.promise,
    fetchConfig: async () => ({ content: 'server text' }),
  })
  await editor.load('llm')
  const operation = editor.onEffortChange({ id: 'demo' }, { target: { value: 'high' } })
  editor.content.value = 'new unsaved text'
  write.resolve({ ok: true })
  await operation
  assert.equal(editor.content.value, 'new unsaved text')
  assert.equal(editor.dirty.value, true)
})

test('ordinary config save acknowledges only the text actually sent', async () => {
  const write = deferred()
  const editor = configEditor({
    fetchConfig: async () => ({ content: 'original' }), saveConfig: () => write.promise,
  })
  await editor.load('games')
  editor.content.value = 'sent bytes'
  const operation = editor.save()
  editor.content.value = 'new unsaved bytes'
  write.resolve({})
  await operation
  assert.equal(editor.originalContent.value, 'sent bytes')
  assert.equal(editor.dirty.value, true)
})

test('late Skill details never supply resources for another selected Skill', async () => {
  const reads = { alpha: deferred(), beta: deferred() }
  const view = componentScript('views/SkillsView.vue', {
    fetchSkill: name => reads[name].promise,
  }, 'selectSkill, selectedName, detail, loadingDetail')
  const alpha = view.selectSkill('alpha')
  const beta = view.selectSkill('beta')
  reads.beta.resolve({ name: 'beta', resources: ['beta-only.md'] })
  await beta
  reads.alpha.resolve({ name: 'alpha', resources: ['alpha-only.md'] })
  await alpha
  assert.equal(view.selectedName.value, 'beta')
  assert.equal(view.detail.value.name, 'beta')
  assert.equal(view.detail.value.resources[0], 'beta-only.md')
  assert.equal(view.loadingDetail.value, false)
})

test('old save list refresh cannot strand the new Skill in its loading state', async () => {
  const list = deferred()
  const beta = deferred()
  const requests = []
  const view = componentScript('views/SkillsView.vue', {
    listSkills: () => list.promise,
    fetchSkill: name => {
      requests.push(name)
      return name === 'beta' ? beta.promise : Promise.resolve({ name })
    },
  }, 'selectSkill, onFileSaved, selectedName, detail, loadingDetail')
  await view.selectSkill('alpha')
  const saved = view.onFileSaved()
  const selected = view.selectSkill('beta')
  list.resolve({ skills: [] })
  await saved
  beta.resolve({ name: 'beta' })
  await selected
  assert.equal(view.detail.value.name, 'beta')
  assert.equal(view.loadingDetail.value, false)
  assert.equal(JSON.stringify(requests), JSON.stringify(['alpha', 'beta']))
})

test('failed refresh during initial detail load exposes an error and can be retried', async () => {
  const initial = deferred()
  let calls = 0
  const view = componentScript('views/SkillsView.vue', {
    listSkills: async () => ({ skills: [] }),
    fetchSkill: () => {
      calls++
      if (calls === 1) return initial.promise
      if (calls === 2) return Promise.reject(new Error('network unavailable'))
      return Promise.resolve({ name: 'beta' })
    },
  }, 'selectSkill, refreshDetail, onRefresh, detail, detailError, loadingDetail')
  const selected = view.selectSkill('beta')
  await view.refreshDetail()
  assert.equal(view.loadingDetail.value, false)
  assert.equal(view.detailError.value, 'network unavailable')
  initial.resolve({ name: 'beta' })
  await selected
  view.onRefresh()
  await new Promise(resolve => setImmediate(resolve))
  assert.equal(view.detail.value.name, 'beta')
  assert.equal(view.detailError.value, null)
})
