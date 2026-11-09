import { afterEach, beforeEach, expect, it, vi } from 'vitest'
import { mount, flushPromises } from '@vue/test-utils'
import EnvironmentView from '@/views/EnvironmentView.vue'
import * as api from '@/api/environment'
const routeQuery = { variable: '' }
vi.mock('vue-router', () => ({ onBeforeRouteLeave: vi.fn(), useRoute: () => ({ query: routeQuery }) }))
vi.mock('@/api/environment', () => ({
  loadEnvironment: vi.fn(), previewEnvironment: vi.fn(), saveEnvironment: vi.fn(),
  getEnvironmentOperation: vi.fn(),
}))
beforeEach(() => {
  routeQuery.variable = ''
  vi.mocked(api.loadEnvironment).mockResolvedValue({ enabled: true, restart_required: false, backend_available: true, reason: null, version: 'v1', consumers: {}, variables: [
    { name: 'TEST_API_KEY', assigned: true, mode: 'credential', warning: '', references: ['test-channel'] },
  ] })
  vi.mocked(api.previewEnvironment).mockResolvedValue({ id: '', phase: 'preview', version: 'v1', changes: [], consumers: {} })
})
afterEach(() => vi.clearAllMocks())
it('keeps unchanged inputs empty and distinguishes empty from delete', async () => {
  const view = mount(EnvironmentView)
  await flushPromises()
  const input = view.find('textarea[aria-label="TEST_API_KEY 新值"]')
  expect((input.element as HTMLInputElement).value).toBe('')
  await input.setValue('new-secret')
  expect(view.text()).toContain('已变更')
  await view.findAll('button').find(b => b.text() === '设置空值')!.trigger('click')
  await view.findAll('button').find(b => b.text() === '预览修改')!.trigger('click')
  await flushPromises()
  expect(api.previewEnvironment).toHaveBeenLastCalledWith('v1', [{ name: 'TEST_API_KEY', action: 'empty' }])
  await view.findAll('button').find(b => b.text() === '删除')!.trigger('click')
  await view.findAll('button').find(b => b.text() === '预览修改')!.trigger('click')
  await flushPromises()
  expect(api.previewEnvironment).toHaveBeenLastCalledWith('v1', [{ name: 'TEST_API_KEY', action: 'delete' }])
  expect(view.text()).toContain('待删除')
  view.unmount()
})
it('retains entered values after a conflict and clears them only after confirmed save', async () => {
  const view = mount(EnvironmentView)
  await flushPromises()
  await view.find('textarea[aria-label="TEST_API_KEY 新值"]').setValue('new-secret')
  await view.findAll('button').find(b => b.text() === '预览修改')!.trigger('click')
  await flushPromises()
  await view.find('input[autocomplete="current-password"]').setValue('password')
  vi.mocked(api.saveEnvironment).mockRejectedValueOnce(new Error('conflict'))
  await view.findAll('button').find(b => b.text() === '确认并保存')!.trigger('click')
  await flushPromises()
  expect((view.find('textarea[aria-label="TEST_API_KEY 新值"]').element as HTMLInputElement).value).toBe('new-secret')
  view.unmount()
})

it('locks edits while the submitted snapshot is being saved', async () => {
  const view = mount(EnvironmentView)
  await flushPromises()
  await view.find('textarea[aria-label="TEST_API_KEY 新值"]').setValue('new\nsecret')
  await view.findAll('button').find(b => b.text() === '预览修改')!.trigger('click')
  await flushPromises()
  expect(api.previewEnvironment).toHaveBeenLastCalledWith('v1', [
    { name: 'TEST_API_KEY', action: 'replace', value: 'new\nsecret' },
  ])
  await view.find('input[autocomplete="current-password"]').setValue('password')
  let finish!: (value: api.Operation) => void
  vi.mocked(api.saveEnvironment).mockReturnValueOnce(new Promise(resolve => { finish = resolve }))
  await view.findAll('button').find(b => b.text() === '确认并保存')!.trigger('click')
  expect(view.find('fieldset').attributes('disabled')).toBeDefined()
  finish({ id: 'saved', phase: 'saved', version: 'v2', changes: [], consumers: {} })
  await flushPromises()
  expect((view.find('textarea[aria-label="TEST_API_KEY 新值"]').element as HTMLTextAreaElement).value).toBe('')
  view.unmount()
})

it('explains disabled management without showing editing controls', async () => {
  vi.mocked(api.loadEnvironment).mockResolvedValue({ enabled: false, restart_required: true,
    backend_available: false, reason: 'environment_management_disabled', version: '',
    variables: [], consumers: {} })
  const view = mount(EnvironmentView)
  await flushPromises()
  expect(view.text()).toContain('QUICKQUIP_ENV_MANAGEMENT_ENABLED=true')
  expect(view.find('fieldset').exists()).toBe(false)
  expect(api.previewEnvironment).not.toHaveBeenCalled()
  expect(api.saveEnvironment).not.toHaveBeenCalled()
  view.unmount()
})

it('searches channel references and keeps multiline edits intact', async () => {
  const view = mount(EnvironmentView)
  await flushPromises()
  await view.find('input[aria-label="搜索变量"]').setValue('missing-channel')
  expect(view.find('textarea').exists()).toBe(false)
  await view.find('input[aria-label="搜索变量"]').setValue('TEST-CHANNEL')
  const input = view.find('textarea[aria-label="TEST_API_KEY 新值"]')
  await input.setValue('line-one\nline-two')
  expect(input.attributes('rows')).toBe('2')
  await view.findAll('button').find(b => b.text() === '预览修改')!.trigger('click')
  await flushPromises()
  expect(api.previewEnvironment).toHaveBeenLastCalledWith('v1', [
    { name: 'TEST_API_KEY', action: 'replace', value: 'line-one\nline-two' },
  ])
  view.unmount()
})

it('refreshes metadata without losing edits and requires a new preview', async () => {
  const view = mount(EnvironmentView)
  await flushPromises()
  await view.find('textarea[aria-label="TEST_API_KEY 新值"]').setValue('typed-secret')
  await view.findAll('button').find(b => b.text() === '预览修改')!.trigger('click')
  await flushPromises()
  expect(view.find('input[autocomplete="current-password"]').exists()).toBe(true)
  vi.mocked(api.loadEnvironment).mockResolvedValueOnce({ enabled: true, restart_required: false,
    backend_available: true, reason: null, version: 'v2', consumers: {}, variables: [
      {name: 'TEST_API_KEY', assigned: true, mode: 'credential', warning: ''},
    ] })
  await view.findAll('button').find(b => b.text() === '刷新状态')!.trigger('click')
  await flushPromises()
  expect((view.find('textarea').element as HTMLTextAreaElement).value).toBe('typed-secret')
  expect(view.find('input[autocomplete="current-password"]').exists()).toBe(false)
  await view.findAll('button').find(b => b.text() === '预览修改')!.trigger('click')
  await flushPromises()
  expect(api.previewEnvironment).toHaveBeenLastCalledWith('v2', [
    {name: 'TEST_API_KEY', action: 'replace', value: 'typed-secret'},
  ])
  view.unmount()
})

it('keeps the editing area hidden when the backend is unavailable', async () => {
  vi.mocked(api.loadEnvironment).mockResolvedValueOnce({enabled: true, restart_required: false,
    backend_available: false, reason: 'environment_backend_unavailable', version: '',
    variables: [], consumers: {}})
  const view = mount(EnvironmentView)
  await flushPromises()
  expect(view.text()).toContain('环境变量服务不可用')
  expect(view.find('fieldset').exists()).toBe(false)
  expect(view.findAll('button').some(b => b.text() === '刷新状态')).toBe(true)
  view.unmount()
})

it('reveals a newly added variable when the list was filtered', async () => {
  const view = mount(EnvironmentView)
  await flushPromises()
  await view.find('input[aria-label="搜索变量"]').setValue('test-channel')
  await view.find('input[aria-label="新变量名"]').setValue('NEW_API_KEY')
  await view.find('input[aria-label="新变量名"]').trigger('keyup', {key: 'Enter'})
  await flushPromises()
  expect(view.find('textarea[aria-label="NEW_API_KEY 新值"]').exists()).toBe(true)
  expect((view.find('input[aria-label="搜索变量"]').element as HTMLInputElement).value).toBe('NEW_API_KEY')
  expect(view.find('tbody tr').text()).toContain('按用途生效')
  expect(view.find('tbody tr').text()).toContain('绑定渠道后可热更新')
  expect(view.find('tbody tr').text()).not.toContain('重启')
  await view.find('textarea[aria-label="NEW_API_KEY 新值"]').setValue('initial-secret')
  vi.mocked(api.previewEnvironment).mockResolvedValueOnce({id: '', phase: 'preview', version: 'v1',
    consumers: {}, changes: [{name: 'NEW_API_KEY', assigned: false, mode: 'unknown', warning: ''}]})
  await view.findAll('button').find(b => b.text() === '预览修改')!.trigger('click')
  await flushPromises()
  expect(api.previewEnvironment).toHaveBeenLastCalledWith('v1', [
    {name: 'NEW_API_KEY', action: 'create', value: 'initial-secret'},
  ])
  expect(view.find('.change-preview').text()).toContain('按用途生效')
  expect(view.find('.change-preview').text()).not.toContain('重启')
  view.unmount()
})

it('uses server classification for a new startup parameter after preview', async () => {
  const view = mount(EnvironmentView)
  await flushPromises()
  await view.find('input[aria-label="新变量名"]').setValue('WEB_ADMIN_PORT')
  await view.find('input[aria-label="新变量名"]').trigger('keyup', {key: 'Enter'})
  await view.find('textarea[aria-label="WEB_ADMIN_PORT 新值"]').setValue('5105')
  vi.mocked(api.previewEnvironment).mockResolvedValueOnce({id: '', phase: 'preview', version: 'v1',
    consumers: {}, changes: [{name: 'WEB_ADMIN_PORT', assigned: false, mode: 'restart', warning: ''}]})
  await view.findAll('button').find(b => b.text() === '预览修改')!.trigger('click')
  await flushPromises()
  expect(view.find('tbody tr').text()).toContain('重启生效')
  expect(view.find('.change-preview').text()).toContain('重启生效')
  expect(view.find('tbody tr').text()).not.toContain('绑定渠道后可热更新')
  view.unmount()
})

it('shows unclassified snapshot synchronization separately from provider loading', async () => {
  vi.mocked(api.loadEnvironment).mockResolvedValueOnce({enabled: true, restart_required: false,
    backend_available: true, reason: null, version: 'v1', consumers: {}, variables: [
      {name: 'NEW_API_KEY', assigned: true, mode: 'unknown', warning: '', states: {web: 'synced'}},
      {name: 'BOUND_API_KEY', assigned: true, mode: 'credential', warning: '',
        references: ['new-provider'], states: {web: 'loaded'}},
    ]})
  const view = mount(EnvironmentView)
  await flushPromises()
  const rows = view.findAll('tbody tr')
  expect(rows[0]!.text()).toContain('按用途生效')
  expect(rows[0]!.text()).toContain('快照已同步')
  expect(rows[0]!.text()).not.toContain('已加载')
  expect(rows[1]!.text()).toContain('热更新')
  expect(rows[1]!.text()).toContain('已加载')
  view.unmount()
})

const taxonomy = [
  { id: 'services', label: '服务与扩展', groups: [
    { id: 'services.native.llm', label: '原生接入 / LLM' },
    { id: 'services.native.generation', label: '原生接入 / 多模态生成' },
  ]},
  { id: 'deployment', label: '部署与构建', groups: [
    { id: 'deployment.image', label: '镜像与依赖' },
  ]},
]
function directoryListing() {
  const relation = (component: string, required_action: string) => ({
    component, object_id: 'shared', field_path: 'providers[0].api_key_env',
    config_scope: 'published' as const, enabled: true, required: true,
    name_kind: 'configured_name' as const, source_name: 'MINIMAX_API_KEY',
    raw_expression: 'MINIMAX_API_KEY', target_service: 'bot',
    target_kind: 'environment_name', target_name: 'MINIMAX_API_KEY',
    resolution: 'process', delivery: 'provider_credential',
    required_action, observation: 'not_observed',
  })
  return { enabled: true, restart_required: false, backend_available: true, reason: null,
    version: 'v1', consumers: {}, taxonomy,
    directory_errors: [{ component: 'generation', code: 'directory_source_unavailable' }],
    variables: [{ name: 'MINIMAX_API_KEY', assigned: true, mode: 'credential', warning: '', references: ['shared'], states: { bot: 'loaded' } }],
    directory: [
      { name: 'MINIMAX_API_KEY', assigned: true, mode: 'credential' as const, warning: '', references: ['shared'],
        states: { bot: 'loaded' }, groups: ['services.native.llm', 'services.native.generation'],
        relations: [relation('llm.provider', 'next_task'), relation('generation.audio', 'restart_or_recreate')],
        sources: [{ kind: 'llm_config', context: 'published', path: 'providers[0].api_key_env',
          raw_expression: 'MINIMAX_API_KEY', resolution_context: 'managed_snapshot',
          evidence_scope: 'config', observation: 'not_observed' }],
        evidence_flags: {},
        definition: { present: true, value_state: 'nonempty' as const, managed_literal: false, deletion_marker: false },
        allowed_actions: ['replace', 'empty', 'delete'], description: 'MiniMax 凭据' },
      { name: 'PIP_INDEX_URL', assigned: false, mode: 'unknown' as const, warning: '', references: [],
        states: {}, groups: ['deployment.image'], relations: [], sources: [],
        evidence_flags: {}, definition: { present: false, value_state: 'missing' as const, managed_literal: false, deletion_marker: false },
        allowed_actions: ['create'], description: '镜像构建 pip 源', default_present: true },
      { name: 'PYTHONPATH', assigned: false, mode: 'unknown' as const, warning: '', references: [],
        states: {}, groups: ['runtime.framework'], relations: [], sources: [],
        evidence_flags: { internal: true },
        definition: { present: false, value_state: 'missing' as const, managed_literal: false, deletion_marker: false },
        allowed_actions: [] },
    ] }
}

it('shows one mixed row per shared key with an honest summary', async () => {
  vi.mocked(api.loadEnvironment).mockResolvedValueOnce(directoryListing())
  const view = mount(EnvironmentView)
  await flushPromises()
  const rows = view.findAll('tbody tr')
  expect(rows.filter(row => row.text().includes('MINIMAX_API_KEY'))).toHaveLength(1)
  const minimax = rows.find(row => row.text().includes('MINIMAX_API_KEY'))!
  expect(minimax.text()).toContain('部分用途需重启或重建')
  expect(minimax.text()).toContain('原生接入 / LLM · 原生接入 / 多模态生成')
  expect(view.text()).toContain('generation')
  view.unmount()
})

it('hides undefined catalog items until the full directory is requested', async () => {
  vi.mocked(api.loadEnvironment).mockResolvedValue(directoryListing())
  const view = mount(EnvironmentView)
  await flushPromises()
  expect(view.text()).not.toContain('PIP_INDEX_URL')
  expect(view.text()).not.toContain('PYTHONPATH')
  await view.find('select[aria-label="目录范围"]').setValue('full')
  expect(view.text()).toContain('PIP_INDEX_URL')
  expect(view.text()).toContain('PYTHONPATH')
  await view.find('select[aria-label="变量领域"]').setValue('deployment')
  expect(view.text()).toContain('PIP_INDEX_URL')
  expect(view.text()).not.toContain('MINIMAX_API_KEY')
  view.unmount()
})

it('filters and expansion keep draft edits, and ARIA wiring matches the region', async () => {
  vi.mocked(api.loadEnvironment).mockResolvedValue(directoryListing())
  const view = mount(EnvironmentView)
  await flushPromises()
  await view.find('textarea[aria-label="MINIMAX_API_KEY 新值"]').setValue('draft-secret')
  const toggle = view.findAll('button').find(b => b.text() === '详情')!
  expect(toggle.attributes('aria-expanded')).toBe('false')
  expect(toggle.attributes('aria-controls')).toBe('environment-details-MINIMAX_API_KEY')
  await toggle.trigger('click')
  expect(toggle.attributes('aria-expanded')).toBe('true')
  const region = view.find('#environment-details-MINIMAX_API_KEY')
  expect(region.attributes('role')).toBe('region')
  expect(region.text()).toContain('llm.provider（shared）')
  expect(region.text()).toContain('新任务生效')
  expect(region.text()).toContain('此处不宣称远端已生效')
  expect((view.find('textarea[aria-label="MINIMAX_API_KEY 新值"]').element as HTMLTextAreaElement).value).toBe('draft-secret')
  view.unmount()
})

it('creates undefined fixed items and refuses internal ones', async () => {
  vi.mocked(api.loadEnvironment).mockResolvedValue(directoryListing())
  const view = mount(EnvironmentView)
  await flushPromises()
  await view.find('select[aria-label="目录范围"]').setValue('full')
  await view.find('textarea[aria-label="PIP_INDEX_URL 新值"]').setValue('https://mirror.example/simple')
  expect(view.text()).toContain('待新增')
  await view.findAll('button').find(b => b.text() === '预览修改')!.trigger('click')
  await flushPromises()
  expect(api.previewEnvironment).toHaveBeenLastCalledWith('v1', [
    { name: 'PIP_INDEX_URL', action: 'create', value: 'https://mirror.example/simple' },
  ])
  expect(view.find('textarea[aria-label="PYTHONPATH 新值"]').exists()).toBe(false)
  expect(view.text()).toContain('由编排或进程内部提供')
  view.unmount()
})

it('locates an existing directory row instead of duplicating a local add', async () => {
  vi.mocked(api.loadEnvironment).mockResolvedValue(directoryListing())
  const view = mount(EnvironmentView)
  await flushPromises()
  await view.find('input[aria-label="新变量名"]').setValue('PIP_INDEX_URL')
  await view.find('input[aria-label="新变量名"]').trigger('keyup', {key: 'Enter'})
  await flushPromises()
  expect(view.text()).toContain('PIP_INDEX_URL')
  expect(view.findAll('textarea[aria-label="PIP_INDEX_URL 新值"]')).toHaveLength(1)
  expect(view.find('input[aria-label="新变量名"]').element).toBeTruthy()
  view.unmount()
})

it('falls back to legacy rows when the backend has no directory', async () => {
  const view = mount(EnvironmentView)
  await flushPromises()
  expect(view.find('select[aria-label="变量领域"]').exists()).toBe(false)
  expect(view.find('textarea[aria-label="TEST_API_KEY 新值"]').exists()).toBe(true)
  await view.find('textarea[aria-label="TEST_API_KEY 新值"]').setValue('still-works')
  await view.findAll('button').find(b => b.text() === '预览修改')!.trigger('click')
  await flushPromises()
  expect(api.previewEnvironment).toHaveBeenLastCalledWith('v1', [
    { name: 'TEST_API_KEY', action: 'replace', value: 'still-works' },
  ])
  view.unmount()
})

it('expands the deep-linked variable from the query', async () => {
  routeQuery.variable = 'MINIMAX_API_KEY'
  vi.mocked(api.loadEnvironment).mockResolvedValue(directoryListing())
  const view = mount(EnvironmentView)
  await flushPromises()
  expect(view.find('#environment-details-MINIMAX_API_KEY').exists()).toBe(true)
  view.unmount()
})
