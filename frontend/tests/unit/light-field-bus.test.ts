import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import {
  getApiActivityState,
  getLightFieldDomain,
  notifyApiActivity,
  resetLightFieldBus,
  setLightFieldDomain,
  subscribeApiActivity,
  subscribeLightField,
  triggerLightFieldSonar,
  triggerRouteWarp,
  type LightFieldEvent,
} from '@/lib/lightFieldBus'
import { request } from '@/api/index'

describe('lightFieldBus', () => {
  beforeEach(() => {
    resetLightFieldBus()
  })

  afterEach(() => {
    vi.unstubAllGlobals()
    resetLightFieldBus()
  })

  it('deduplicates repeated domain updates and emits warp/sonar events', () => {
    const received: LightFieldEvent[] = []
    const unsub = subscribeLightField(e => received.push(e))

    setLightFieldDomain('overview')
    expect(received).toHaveLength(0)

    setLightFieldDomain('llm')
    setLightFieldDomain('llm')
    expect(getLightFieldDomain()).toBe('llm')
    expect(received).toHaveLength(1)
    expect(received[0]).toEqual({ type: 'domain', domain: 'llm' })

    triggerRouteWarp('forward')
    triggerRouteWarp('forward', 1.9)
    triggerLightFieldSonar({ x: 100, y: 200, kind: 'success' })
    triggerLightFieldSonar({ x: 50, y: 60, kind: 'ripple', scale: 1.25 })
    expect(received).toHaveLength(5)
    expect(received[1]).toEqual({ type: 'warp', direction: 'forward' })
    expect(received[2]).toEqual({ type: 'warp', direction: 'forward', intensity: 1.9 })
    expect(received[3]).toEqual({ type: 'sonar', payload: { x: 100, y: 200, kind: 'success' } })
    expect(received[4]).toEqual({ type: 'sonar', payload: { x: 50, y: 60, kind: 'ripple', scale: 1.25 } })

    unsub()
    triggerRouteWarp('back')
    expect(received).toHaveLength(5)
  })

  it('tracks API in-flight count and lastOk state without dropping below zero', () => {
    const snapshots: Array<{ inFlight: number; lastOk: boolean }> = []
    const unsub = subscribeApiActivity(s => snapshots.push({ inFlight: s.inFlight, lastOk: s.lastOk }))

    notifyApiActivity('start')
    notifyApiActivity('start')
    expect(getApiActivityState().inFlight).toBe(2)

    notifyApiActivity('end', true)
    notifyApiActivity('end', false)
    notifyApiActivity('end', true)
    expect(getApiActivityState().inFlight).toBe(0)
    expect(getApiActivityState().lastOk).toBe(true)
    expect(snapshots[snapshots.length - 2]).toEqual({ inFlight: 0, lastOk: false })

    unsub()
  })

  it('triggers sonar on successful mutating API calls but not on GET or logout', async () => {
    const received: LightFieldEvent[] = []
    const unsub = subscribeLightField(e => received.push(e))

    vi.stubGlobal('fetch', vi.fn(async () => ({
      status: 200,
      ok: true,
      statusText: 'OK',
      text: async () => '{"ok":true}',
    }) as unknown as Response))

    await request('/api/ping')
    expect(received.filter(e => e.type === 'sonar')).toHaveLength(0)

    await request('/api/rules', { method: 'PUT', body: '{}' })
    expect(received.filter(e => e.type === 'sonar')).toHaveLength(1)

    await request('/api/auth/logout', { method: 'POST' })
    expect(received.filter(e => e.type === 'sonar')).toHaveLength(1)
    expect(getApiActivityState().inFlight).toBe(0)

    unsub()
  })

  it('does not mark AbortError as an API error in activity state', async () => {
    vi.stubGlobal('fetch', vi.fn(async () => {
      const err = new Error('The operation was aborted')
      err.name = 'AbortError'
      throw err
    }))

    await expect(request('/api/epochs/timeline')).rejects.toThrow('aborted')
    expect(getApiActivityState().inFlight).toBe(0)
    expect(getApiActivityState().lastOk).toBe(true)
  })
})
