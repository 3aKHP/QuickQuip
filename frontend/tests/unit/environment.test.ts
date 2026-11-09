import { afterEach, beforeEach, expect, it, vi } from 'vitest'
import { mount, flushPromises } from '@vue/test-utils'
import EnvironmentView from '@/views/EnvironmentView.vue'
import * as api from '@/api/environment'
vi.mock('vue-router', () => ({ onBeforeRouteLeave: vi.fn(), useRoute: () => ({ query: {} }) }))
vi.mock('@/api/environment', () => ({
  loadEnvironment: vi.fn(), previewEnvironment: vi.fn(), saveEnvironment: vi.fn(),
  getEnvironmentOperation: vi.fn(),
}))
beforeEach(() => {
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
