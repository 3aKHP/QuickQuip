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
    { name: 'TEST_API_KEY', assigned: true, mode: 'credential', warning: '' },
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
