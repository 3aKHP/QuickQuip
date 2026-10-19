import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { BASE, request, setUnauthorizedHandler } from '@/api/index'

function fakeResponse(status: number, body: unknown, statusText = ''): Response {
  const ok = status >= 200 && status < 300
  const text = typeof body === 'string' ? body : body === undefined ? '' : JSON.stringify(body)
  return { status, ok, statusText, text: async () => text } as unknown as Response
}

const fetchMock = vi.fn<typeof fetch>()

beforeEach(() => {
  vi.stubGlobal('fetch', fetchMock)
})

afterEach(() => {
  setUnauthorizedHandler(null)
  vi.unstubAllGlobals()
  fetchMock.mockReset()
})

describe('request', () => {
  it('returns parsed JSON on success and prefixes BASE', async () => {
    fetchMock.mockResolvedValue(fakeResponse(200, { hello: 'world' }))
    const data = await request<{ hello: string }>('/api/ping')
    expect(data).toEqual({ hello: 'world' })
    expect(fetchMock).toHaveBeenCalledOnce()
    const [url, init] = fetchMock.mock.calls[0] as unknown as [string, RequestInit]
    expect(url).toBe(`${BASE}/api/ping`)
    expect(init.credentials).toBe('same-origin')
  })

  it('sets Content-Type: application/json when a body is sent', async () => {
    fetchMock.mockResolvedValue(fakeResponse(200, {}))
    await request('/api/ping', { method: 'POST', body: JSON.stringify({ a: 1 }) })
    const [, init] = fetchMock.mock.calls[0] as unknown as [string, RequestInit]
    expect((init.headers as Record<string, string>)['Content-Type']).toBe('application/json')
  })

  it('on 401 invokes the unauthorized handler and rejects with a marked ApiError', async () => {
    const onUnauthorized = vi.fn()
    setUnauthorizedHandler(onUnauthorized)
    fetchMock.mockResolvedValue(fakeResponse(401, ''))

    const err = await request('/api/protected').catch((e: unknown) => e)
    expect(onUnauthorized).toHaveBeenCalledOnce()
    expect(err).toBeInstanceOf(Error)
    const apiErr = err as { status: number; _isUnauthorized?: boolean; message: string }
    expect(apiErr.status).toBe(401)
    expect(apiErr._isUnauthorized).toBe(true)
    expect(apiErr.message).toContain('401')
  })

  it('on non-401 error rejects with ApiError carrying status, data and formatted detail', async () => {
    const body = { detail: [{ loc: ['body', 'name'], msg: 'field required' }] }
    fetchMock.mockResolvedValue(fakeResponse(422, body))

    const err = await request('/api/submit', { method: 'POST', body: '{}' }).catch((e: unknown) => e)
    const apiErr = err as { status: number; data?: unknown; message: string; _isUnauthorized?: boolean }
    expect(apiErr.status).toBe(422)
    expect(apiErr.data).toEqual(body)
    expect(apiErr.message).toContain('422')
    expect(apiErr.message).toContain('body.name: field required')
    expect(apiErr._isUnauthorized).toBeUndefined()
  })

  it('on error with string detail uses the detail as message', async () => {
    fetchMock.mockResolvedValue(fakeResponse(400, { detail: 'bad param' }))
    const err = await request('/api/x').catch((e: unknown) => e) as { status: number; message: string }
    expect(err.status).toBe(400)
    expect(err.message).toBe('400 bad param')
  })

  it('on non-JSON error body rejects with status and statusText', async () => {
    fetchMock.mockResolvedValue(fakeResponse(502, '<html>bad gateway</html>', 'Bad Gateway'))
    const err = await request('/api/x').catch((e: unknown) => e) as Error
    expect(err.message).toBe('502: Bad Gateway')
  })

  it('propagates network-layer failures without invoking the unauthorized handler', async () => {
    const onUnauthorized = vi.fn()
    setUnauthorizedHandler(onUnauthorized)
    const networkError = new TypeError('fetch failed')
    fetchMock.mockRejectedValue(networkError)

    const err = await request('/api/x').catch((e: unknown) => e)
    expect(err).toBe(networkError)
    expect((err as { status?: number }).status).toBeUndefined()
    expect(onUnauthorized).not.toHaveBeenCalled()
  })
})
