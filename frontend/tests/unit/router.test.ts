import { describe, expect, it } from 'vitest'
import { NAV_ITEMS } from '@/config/nav'
import { router } from '@/router/index'

describe('router redirects', () => {
  it('/logs redirects to /logs-live', async () => {
    await router.push('/logs')
    expect(router.currentRoute.value.path).toBe('/logs-live')
  })

  it('/mcp-dashboard redirects to /llm-config?section=tools', async () => {
    await router.push('/mcp-dashboard')
    expect(router.currentRoute.value.path).toBe('/llm-config')
    expect(router.currentRoute.value.query).toEqual({ section: 'tools' })
  })

  it('/mcp redirects to the same tools section', async () => {
    await router.push('/mcp')
    expect(router.currentRoute.value.path).toBe('/llm-config')
    expect(router.currentRoute.value.query).toEqual({ section: 'tools' })
  })

  it('unknown paths fall through the catch-all back to /', async () => {
    await router.push('/definitely-not-a-page/deep')
    expect(router.currentRoute.value.path).toBe('/')
    expect(router.currentRoute.value.name).toBe('home')
  })
})

describe('NAV_ITEMS routes', () => {
  it('every nav entry resolves to a route named after its key', () => {
    expect(NAV_ITEMS.length).toBe(29)
    for (const item of NAV_ITEMS) {
      const resolved = router.resolve(item.path)
      expect(resolved.name, `route for ${item.path}`).toBe(item.key)
    }
  })

  it('every nav route component loads (dynamic imports work under vitest)', async () => {
    for (const item of NAV_ITEMS) {
      const resolved = router.resolve(item.path)
      const record = resolved.matched[resolved.matched.length - 1]
      const component = record?.components?.default
      expect(component, `component for ${item.path}`).toBeDefined()
      if (typeof component === 'function') {
        const loaded = await (component as () => Promise<{ default: unknown }>)()
        expect(loaded?.default ?? loaded, `lazy component for ${item.path}`).toBeTruthy()
      }
    }
  })
})
