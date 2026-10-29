import { afterEach, beforeEach, expect, it, vi } from 'vitest'
import { flushPromises, mount } from '@vue/test-utils'
import MemoryView from '@/views/MemoryView.vue'
import * as api from '@/api/memory'
import type { MemoryEntry } from '@/api/memory'

vi.mock('@/api/groups', () => ({ fetchKnownGroups: vi.fn(async () => ({ groups: ['12345'] })) }))
vi.mock('@/api/memory', () => ({
  fetchMemories: vi.fn(), fetchMemoryStatus: vi.fn(), createMemory: vi.fn(),
  updateMemory: vi.fn(), deleteMemory: vi.fn(), clearAllMemories: vi.fn(),
}))
vi.mock('@/toast', () => ({ toast: vi.fn() }))
const entry: MemoryEntry = {
  id: 42, title: '联机', description: '周六八点', content: '# 联机\n周六八点',
  content_display: '# 联机\n周六八点', version: 7, source: 'manual', writer: 'command',
  source_user_id: '20001', source_message_id: 'm1', source_role: 'GROUP_OWNER',
  updated_at: '2026-10-29T12:00:00',
  content_parts: { version: 1, parts: [{ type: 'text', text: '# 联机\n周六八点' }] },
}
beforeEach(() => {
  vi.mocked(api.fetchMemories).mockResolvedValue([structuredClone(entry)])
  vi.mocked(api.fetchMemoryStatus).mockResolvedValue({ count: 1, capacity: 20 })
})
afterEach(() => vi.clearAllMocks())
function view() {
  return mount(MemoryView, { global: { stubs: { RouterLink: true, UiPageHeader: true, RecordContentEditor: true } } })
}
it('uses an independent private scope and displays configured capacity', async () => {
  const wrapper = view()
  await wrapper.find('select').setValue('private')
  await wrapper.find('input').setValue('12345')
  await flushPromises()
  expect(api.fetchMemories).toHaveBeenLastCalledWith('private:12345', '', 0)
  expect(wrapper.text()).toContain('已使用 1 / 20 条')
  expect(wrapper.text()).toContain('群主')
  wrapper.unmount()
})
it('sends the read version and preserves the editor when an update conflicts', async () => {
  vi.mocked(api.updateMemory).mockRejectedValue(new Error('记忆已修改，请重新读取'))
  const wrapper = view()
  await wrapper.find('input').setValue('12345')
  await flushPromises()
  await wrapper.findAll('button').find(button => button.text() === '编辑')!.trigger('click')
  await wrapper.find('input[aria-label="标题"]').setValue('新的标题')
  await wrapper.findAll('button').find(button => button.text() === '保存')!.trigger('click')
  await flushPromises()
  expect(api.updateMemory).toHaveBeenCalledWith('12345', 42, expect.objectContaining({
    version: 7, title: '新的标题', content_parts: entry.content_parts,
  }))
  expect(wrapper.find('input[aria-label="标题"]').exists()).toBe(true)
  wrapper.unmount()
})
