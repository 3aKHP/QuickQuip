import { ref } from 'vue'
import type { Ref } from 'vue'
import { getAuthState, login as apiLogin, logout as apiLogout } from '../api/auth'
import { setUnauthorizedHandler } from '../api/index'
import { triggerLightFieldSonar, triggerRouteWarp } from '../lib/lightFieldBus'
import { toast, toastMsg } from '../toast'

interface ApiError {
  status?: number
  data?: { detail?: string }
  message?: string
}

const authReady: Ref<boolean> = ref(false)
const authenticated: Ref<boolean> = ref(false)
const authBusy: Ref<boolean> = ref(false)
const authError: Ref<string> = ref('')

async function initializeAuth(): Promise<void> {
  authReady.value = false
  authError.value = ''
  try {
    await getAuthState()
    authenticated.value = true
  } catch (error: unknown) {
    const err = error as ApiError
    if (err.status !== 401) {
      authError.value = err.data?.detail || err.message || '鉴权检查失败'
    }
    authenticated.value = false
  } finally {
    authReady.value = true
  }
}

async function handleLogin(password: string): Promise<void> {
  authBusy.value = true
  authError.value = ''
  try {
    await apiLogin(password)
    // 登录解锁瞬间触发星海跃迁与中心能量环，配合工作台空间展开
    triggerRouteWarp('forward', 1.9)
    triggerLightFieldSonar({ kind: 'success', scale: 1.45 })
    authenticated.value = true
    toastMsg.value = null
  } catch (error: unknown) {
    const err = error as ApiError
    authenticated.value = false
    authError.value = err.status === 401
      ? '口令错误，请重试。'
      : (err.data?.detail || err.message || '登录失败')
  } finally {
    authBusy.value = false
  }
}

async function handleLogout(): Promise<void> {
  authBusy.value = true
  authError.value = ''
  try {
    await apiLogout()
    authenticated.value = false
  } catch (error: unknown) {
    const err = error as ApiError
    // 若登出时服务端已返回 401，unauthorizedHandler 已完成登出，不再提示矛盾的退出失败
    if (err.status === 401) return
    // 退出请求失败时服务端会话可能仍有效，保留登录态并如实提示
    toast(`退出失败，当前会话仍有效：${err.data?.detail || err.message || '请稍后重试'}`, 'error')
  } finally {
    authBusy.value = false
  }
}

function attachUnauthorizedHandler(): void {
  setUnauthorizedHandler(() => {
    // 仅此前已登录（会话真的失效）才提示；并发 401 到达时不覆盖已写入的失效提示
    const wasAuthenticated = authenticated.value
    authenticated.value = false
    authReady.value = true
    authBusy.value = false
    if (wasAuthenticated) {
      authError.value = '登录状态已失效，请重新登录。'
    }
  })
}

function detachUnauthorizedHandler(): void {
  setUnauthorizedHandler(null)
}

export function useAuth() {
  return {
    authReady,
    authenticated,
    authBusy,
    authError,
    initializeAuth,
    handleLogin,
    handleLogout,
    attachUnauthorizedHandler,
    detachUnauthorizedHandler,
  }
}
