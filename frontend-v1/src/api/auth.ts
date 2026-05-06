import { request } from './index'

export async function login(password: string) {
  return request('/api/auth/login', {
    method: 'POST',
    body: JSON.stringify({ password }),
  })
}

export async function logout() {
  return request('/api/auth/logout', {
    method: 'POST',
    body: JSON.stringify({}),
  })
}

export async function getAuthState() {
  return request('/api/auth/me')
}
