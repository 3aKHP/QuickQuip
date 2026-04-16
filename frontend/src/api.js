const BASE = import.meta.env.BASE_URL.replace(/\/$/, '')

let unauthorizedHandler = null

export function setUnauthorizedHandler(handler) {
  unauthorizedHandler = handler
}

// H6: 先处理 401，再解析 JSON，避免解析失败吞掉 HTTP 错误信息
async function parseResponse(res) {
  // L2: 401 时触发 handler 后抛出特殊标记，让调用方可以静默处理
  if (res.status === 401) {
    if (unauthorizedHandler) unauthorizedHandler()
    const err = new Error('401 admin login required')
    err.status = 401
    err._isUnauthorized = true
    throw err
  }

  const text = await res.text()
  if (!text) return null

  // 尝试解析 JSON；失败时返回原始文本（2xx）或抛出带状态码的错误（非 2xx）
  let data
  try {
    data = JSON.parse(text)
  } catch {
    if (!res.ok) throw new Error(`${res.status}: ${res.statusText}`)
    return text
  }

  if (!res.ok) {
    const detail = typeof data === 'object' && data !== null && 'detail' in data
      ? data.detail
      : res.statusText
    const err = new Error(`${res.status} ${detail}`)
    err.status = res.status
    err.data = data
    throw err
  }

  return data
}

async function request(path, options = {}) {
  const headers = { ...(options.headers || {}) }
  if (options.body !== undefined && !headers['Content-Type']) {
    headers['Content-Type'] = 'application/json'
  }

  const res = await fetch(BASE + path, {
    credentials: 'same-origin',
    ...options,
    headers,
  })
  return parseResponse(res)
}

export async function apiFetch(path, options = {}) {
  return request(path, options)
}

export async function login(password) {
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
