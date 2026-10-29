import { flushPromises, mount } from '@vue/test-utils'
import { beforeEach, expect, it, vi } from 'vitest'
import GroupSettingsView from '../../src/views/GroupSettingsView.vue'
import * as api from '../../src/api/groupSettings'

vi.mock('../../src/api/groupSettings', () => ({
  fetchOptions: vi.fn(), listGroupSettings: vi.fn(), fetchGroupSettings: vi.fn(),
  saveGroupSettings: vi.fn(), clearGroupSettings: vi.fn(), setPrivateSessionState: vi.fn(),
}))

beforeEach(() => {
  vi.clearAllMocks()
  vi.mocked(api.fetchOptions).mockResolvedValue({
    providers: [], personas: [], defaults: {}, load_error: null,
  })
  let sessionActive = true
  vi.mocked(api.listGroupSettings).mockImplementation(async () => ({ groups: [{
    group_id: 'private:67890', type: 'private', session_active: sessionActive,
    enabled: null, memory_enabled: null, auto_memory_enabled: null,
    agent_delivery_intermediate_enabled: null, agent_delivery_final_enabled: null,
    provider_id: null, model: null, persona_id: null, trigger_prefix: null,
    allow_prefix: null, allow_at: null, history_limit: null, reasoning_effort: null,
    updated_at: null,
  }] }))
  vi.mocked(api.fetchGroupSettings).mockResolvedValue({
    enabled: null, memory_enabled: null, auto_memory_enabled: null,
    agent_delivery_intermediate_enabled: null, agent_delivery_final_enabled: null,
    provider_id: null, model: null, persona_id: null, trigger_prefix: null,
    allow_prefix: null, allow_at: null, history_limit: null, reasoning_effort: null,
  })
  vi.mocked(api.setPrivateSessionState).mockImplementation(async (_userId, active) => {
    sessionActive = active
    return { active }
  })
})

it('pauses private responses without saving or discarding pending parameter edits', async () => {
  const wrapper = mount(GroupSettingsView, { global: { stubs: { UiPageHeader: true } } })
  await flushPromises()
  await wrapper.findAll('button').find((button) => button.text().includes('67890'))!.trigger('click')
  await flushPromises()
  const input = wrapper.find<HTMLInputElement>('input[placeholder="默认 model"]')
  await input.setValue('pending-model')
  await wrapper.findAll('button').find((button) => button.text() === '暂停响应')!.trigger('click')
  await flushPromises()
  expect(api.setPrivateSessionState).toHaveBeenCalledWith('67890', false)
  expect(api.saveGroupSettings).not.toHaveBeenCalled()
  expect(input.element.value).toBe('pending-model')
  expect(wrapper.text()).toContain('私聊已暂停')
  wrapper.unmount()
})
