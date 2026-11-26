import { describe, expect, it } from 'vitest'
import { NAV_ITEMS, NAV_SECTIONS } from '@/config/nav'
import {
  buildCommandEntries,
  fuzzyScore,
  searchCommandEntries,
} from '@/lib/commandSearch'

describe('commandSearch', () => {
  const entries = buildCommandEntries(NAV_ITEMS, NAV_SECTIONS, {
    theme: 'light',
    lowMotion: false,
  })

  it('builds entries for every nav item plus quick actions', () => {
    const routes = entries.filter(e => e.kind === 'route')
    const actions = entries.filter(e => e.kind === 'action')
    expect(routes).toHaveLength(NAV_ITEMS.length)
    expect(actions.map(a => a.actionId)).toEqual(['toggle-theme', 'toggle-motion', 'logout'])
    expect(actions[0].label).toContain('暗色')
    expect(actions[1].label).toContain('开启低动态')
  })

  it('reflects dark theme and enabled lowMotion in quick action labels', () => {
    const darkEntries = buildCommandEntries(NAV_ITEMS, NAV_SECTIONS, {
      theme: 'dark',
      lowMotion: true,
    })
    const actions = darkEntries.filter(e => e.kind === 'action')
    expect(actions[0].label).toContain('亮色')
    expect(actions[1].label).toContain('关闭低动态')
  })

  it('scores exact > prefix > substring > ordered fuzzy > non-match', () => {
    const exact = fuzzyScore('epochs', 'epochs')
    const prefix = fuzzyScore('epo', 'epochs')
    const sub = fuzzyScore('poch', 'epochs')
    const fuzzy = fuzzyScore('eps', 'epochs')
    const miss = fuzzyScore('xyz', 'epochs')

    expect(exact).toBeGreaterThan(prefix)
    expect(prefix).toBeGreaterThan(sub)
    expect(sub).toBeGreaterThan(fuzzy)
    expect(fuzzy).toBeGreaterThan(0)
    expect(miss).toBe(0)
  })

  it('matches Chinese labels, pinyin initials, paths, and quick actions', () => {
    expect(searchCommandEntries(entries, '牛牛')[0]?.path).toBe('/niuniu')
    expect(searchCommandEntries(entries, 'ssrz')[0]?.path).toBe('/logs-live')
    expect(searchCommandEntries(entries, 'dsxx')[0]?.path).toBe('/scheduled-messages')
    expect(searchCommandEntries(entries, '/epochs')[0]?.path).toBe('/epochs')
    expect(searchCommandEntries(entries, '暗色')[0]?.actionId).toBe('toggle-theme')
  })

  it('prioritizes recently visited paths when query is empty', () => {
    const res = searchCommandEntries(entries, '', ['/epochs', '/logs-live'])
    expect(res[0]?.path).toBe('/epochs')
    expect(res[1]?.path).toBe('/logs-live')
  })
})
