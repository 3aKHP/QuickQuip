import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { useTheme } from '@/composables/useTheme'
import { resetLightFieldBus, subscribeLightField, type LightFieldEvent } from '@/lib/lightFieldBus'

describe('useTheme toggleTheme', () => {
  beforeEach(() => {
    localStorage.clear()
    delete document.documentElement.dataset.motion
    document.documentElement.classList.remove('theme-anim')
    document.documentElement.setAttribute('data-theme', 'light')
    useTheme().theme.value = 'light'
  })

  afterEach(() => {
    delete (document as unknown as Record<string, unknown>).startViewTransition
    delete (document.documentElement as unknown as Record<string, unknown>).animate
    delete document.documentElement.dataset.motion
    document.documentElement.classList.remove('theme-anim')
    vi.useRealTimers()
  })

  it('uses View Transitions circular clipPath reveal when supported', async () => {
    resetLightFieldBus()
    const fieldEvents: LightFieldEvent[] = []
    const unsub = subscribeLightField(e => fieldEvents.push(e))
    const animateMock = vi.fn()
    const startVtMock = vi.fn((cb: () => void) => {
      cb()
      return { ready: Promise.resolve() }
    })
    ;(document as unknown as Record<string, unknown>).startViewTransition = startVtMock
    ;(document.documentElement as unknown as Record<string, unknown>).animate = animateMock

    const { theme, toggleTheme } = useTheme()
    toggleTheme({ x: 40, y: 80 })
    await Promise.resolve()
    unsub()

    expect(theme.value).toBe('dark')
    expect(document.documentElement.getAttribute('data-theme')).toBe('dark')
    expect(startVtMock).toHaveBeenCalledOnce()
    expect(animateMock).toHaveBeenCalledOnce()
    const [keyframes, options] = animateMock.mock.calls[0] as [
      { clipPath: string[] },
      { pseudoElement: string },
    ]
    expect(keyframes.clipPath[0]).toBe('circle(0px at 40px 80px)')
    expect(keyframes.clipPath[1]).toContain('at 40px 80px)')
    expect(options.pseudoElement).toBe('::view-transition-new(root)')
    expect(fieldEvents).toEqual([
      { type: 'sonar', payload: { x: 40, y: 80, kind: 'action', scale: 1.35 } },
    ])
  })

  it('computes next theme inside async View Transition callback to avoid rapid double-click race', async () => {
    const callbacks: Array<() => void | Promise<void>> = []
    const startVtMock = vi.fn((cb: () => void | Promise<void>) => {
      callbacks.push(cb)
      return { ready: Promise.resolve() }
    })
    ;(document as unknown as Record<string, unknown>).startViewTransition = startVtMock
    ;(document.documentElement as unknown as Record<string, unknown>).animate = vi.fn()

    const { theme, toggleTheme } = useTheme()
    toggleTheme({ x: 20, y: 20 })
    toggleTheme({ x: 20, y: 20 })
    expect(callbacks).toHaveLength(2)

    await callbacks[0]()
    expect(theme.value).toBe('dark')
    await callbacks[1]()
    expect(theme.value).toBe('light')
  })

  it('bypasses View Transitions and theme-anim when lowMotion is enabled', () => {
    const startVtMock = vi.fn()
    ;(document as unknown as Record<string, unknown>).startViewTransition = startVtMock
    ;(document.documentElement as unknown as Record<string, unknown>).animate = vi.fn()
    document.documentElement.dataset.motion = 'reduced'

    const { theme, toggleTheme } = useTheme()
    toggleTheme({ x: 10, y: 10 })

    expect(theme.value).toBe('dark')
    expect(startVtMock).not.toHaveBeenCalled()
    expect(document.documentElement.classList.contains('theme-anim')).toBe(false)
  })

  it('falls back to theme-anim class when startViewTransition is unavailable', () => {
    vi.useFakeTimers()
    delete (document as unknown as Record<string, unknown>).startViewTransition

    const { theme, toggleTheme } = useTheme()
    toggleTheme()

    expect(theme.value).toBe('dark')
    expect(document.documentElement.classList.contains('theme-anim')).toBe(true)

    vi.advanceTimersByTime(330)
    expect(document.documentElement.classList.contains('theme-anim')).toBe(false)
  })
})
