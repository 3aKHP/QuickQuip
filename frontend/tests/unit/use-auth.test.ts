import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { getAuthState, login, logout } from '@/api/auth'
import { request, setUnauthorizedHandler } from '@/api/index'
import { useAuth } from '@/composables/useAuth'
import { toastMsg, toastType } from '@/toast'

vi.mock('@/api/auth', () => ({
  login: vi.fn(),
  logout: vi.fn(),
  getAuthState: vi.fn(),
}))

const mockLogin = vi.mocked(login)
const mockLogout = vi.mocked(logout)
const mockGetAuthState = vi.mocked(getAuthState)

const auth = useAuth()

function resetAuthState(): void {
  auth.authenticated.value = false
  auth.authReady.value = false
  auth.authBusy.value = false
  auth.authError.value = ''
  toastMsg.value = null
  setUnauthorizedHandler(null)
}

beforeEach(resetAuthState)
afterEach(() => {
  resetAuthState()
  vi.unstubAllGlobals()
})

describe('useAuth', () => {
  it('initializeAuth marks authenticated when /me succeeds', async () => {
    mockGetAuthState.mockResolvedValue(null)
    await auth.initializeAuth()
    expect(auth.authenticated.value).toBe(true)
    expect(auth.authReady.value).toBe(true)
    expect(auth.authError.value).toBe('')
  })

  it('initializeAuth on 401 stays silent and unauthenticated', async () => {
    mockGetAuthState.mockRejectedValue({ status: 401 })
    await auth.initializeAuth()
    expect(auth.authenticated.value).toBe(false)
    expect(auth.authReady.value).toBe(true)
    expect(auth.authError.value).toBe('')
  })

  it('initializeAuth surfaces non-401 failures in authError', async () => {
    mockGetAuthState.mockRejectedValue({ status: 500, data: { detail: '服务器开小差' } })
    await auth.initializeAuth()
    expect(auth.authenticated.value).toBe(false)
    expect(auth.authError.value).toBe('服务器开小差')
  })

  it('handleLogin success authenticates and clears stale toast', async () => {
    toastMsg.value = '旧提示'
    mockLogin.mockResolvedValue(null)
    await auth.handleLogin('secret')
    expect(mockLogin).toHaveBeenCalledWith('secret')
    expect(auth.authenticated.value).toBe(true)
    expect(auth.authError.value).toBe('')
    expect(toastMsg.value).toBeNull()
    expect(auth.authBusy.value).toBe(false)
  })

  it('handleLogin 401 rejects with a password-specific message', async () => {
    mockLogin.mockRejectedValue({ status: 401 })
    await auth.handleLogin('wrong')
    expect(auth.authenticated.value).toBe(false)
    expect(auth.authError.value).toBe('口令错误，请重试。')
    expect(auth.authBusy.value).toBe(false)
  })

  it('handleLogout success clears the session state', async () => {
    auth.authenticated.value = true
    mockLogout.mockResolvedValue(null)
    await auth.handleLogout()
    expect(auth.authenticated.value).toBe(false)
    expect(auth.authBusy.value).toBe(false)
  })

  it('handleLogout failure keeps the session and reports via toast', async () => {
    auth.authenticated.value = true
    mockLogout.mockRejectedValue({ data: { detail: '连接中断' } })
    await auth.handleLogout()
    expect(auth.authenticated.value).toBe(true)
    expect(auth.authBusy.value).toBe(false)
    expect(toastType.value).toBe('error')
    expect(toastMsg.value).toContain('退出失败')
    expect(toastMsg.value).toContain('连接中断')
  })

  it('a 401 from any request resets the chain and notifies an expired session', async () => {
    auth.authenticated.value = true
    auth.authReady.value = true
    auth.attachUnauthorizedHandler()
    vi.stubGlobal('fetch', vi.fn(async () => ({
      status: 401, ok: false, statusText: 'Unauthorized', text: async () => '',
    } as unknown as Response)))

    await request('/api/anything').catch(() => {})
    expect(auth.authenticated.value).toBe(false)
    expect(auth.authReady.value).toBe(true)
    expect(auth.authBusy.value).toBe(false)
    expect(auth.authError.value).toBe('登录状态已失效，请重新登录。')
  })

  it('a 401 while anonymous resets state without the expiry notice', async () => {
    auth.attachUnauthorizedHandler()
    vi.stubGlobal('fetch', vi.fn(async () => ({
      status: 401, ok: false, statusText: 'Unauthorized', text: async () => '',
    } as unknown as Response)))

    await request('/api/anything').catch(() => {})
    expect(auth.authenticated.value).toBe(false)
    expect(auth.authError.value).toBe('')
  })
})
