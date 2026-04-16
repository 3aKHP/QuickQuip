import { ref } from 'vue'
import { getAuthState, login as apiLogin, logout as apiLogout } from '../api/auth.js'
import { setUnauthorizedHandler } from '../api/index.js'
import { toastMsg } from '../toast.js'

const authReady = ref(false)
const authenticated = ref(false)
const authBusy = ref(false)
const authError = ref('')

async function initializeAuth() {
  authReady.value = false
  authError.value = ''
  try {
    await getAuthState()
    authenticated.value = true
  } catch (error) {
    if (error.status !== 401) {
      authError.value = error.data?.detail || error.message || '鉴权检查失败'
    }
    authenticated.value = false
  } finally {
    authReady.value = true
  }
}

async function handleLogin(password) {
  authBusy.value = true
  authError.value = ''
  try {
    await apiLogin(password)
    authenticated.value = true
    toastMsg.value = null
  } catch (error) {
    authenticated.value = false
    authError.value = error.status === 401
      ? '口令错误，请重试。'
      : (error.data?.detail || error.message || '登录失败')
  } finally {
    authBusy.value = false
  }
}

async function handleLogout() {
  authBusy.value = true
  authError.value = ''
  try {
    await apiLogout()
  } catch (error) {
    authError.value = error.data?.detail || error.message || '退出失败'
  } finally {
    authenticated.value = false
    authBusy.value = false
  }
}

function attachUnauthorizedHandler() {
  setUnauthorizedHandler(() => {
    authenticated.value = false
    authReady.value = true
    authBusy.value = false
    authError.value = '登录状态已失效，请重新登录。'
  })
}

function detachUnauthorizedHandler() {
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
