import { mount } from '@vue/test-utils'
import { describe, expect, it } from 'vitest'
import UiIcon from '@/components/ui/UiIcon.vue'

describe('UiIcon', () => {
  it('renders the mapped lucide icon with the requested size', () => {
    const wrapper = mount(UiIcon, { props: { name: 'Users', size: 20 } })
    const svg = wrapper.find('svg')
    expect(svg.exists()).toBe(true)
    expect(svg.classes()).toContain('lucide-users')
    expect(svg.attributes('width')).toBe('20')
    expect(svg.attributes('height')).toBe('20')
  })

  it('maps renamed icons (BarChart3 -> ChartColumn)', () => {
    const wrapper = mount(UiIcon, { props: { name: 'BarChart3' } })
    expect(wrapper.find('svg').classes()).toContain('lucide-chart-column')
  })

  it('falls back to the Info icon for unknown names', () => {
    const wrapper = mount(UiIcon, { props: { name: 'NoSuchIcon' } })
    expect(wrapper.find('svg').classes()).toContain('lucide-info')
  })

  it('applies the motion class only when requested', () => {
    const withMotion = mount(UiIcon, { props: { name: 'RefreshCw', motion: 'spin' } })
    expect(withMotion.find('svg').classes()).toContain('qq-ico--spin')
    const plain = mount(UiIcon, { props: { name: 'RefreshCw' } })
    expect(plain.find('svg').classes().some(c => c.startsWith('qq-ico'))).toBe(false)
  })
})
