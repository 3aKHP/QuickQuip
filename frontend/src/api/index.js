const BASE = import.meta.env.BASE_URL.replace(/\/$/, '')

let unauthorizedHandler = null

export function setUnauthorizedHandler(handler) {
  unauthorizedHandler = handler
}

async function parseResponse(res) {
  if (res.status === 401) {
    if (unauthorizedHandler) unauthorizedHandler()
    const err = new Error('401 admin login required')
    err.status = 401
    err._isUnauthorized = true
    throw err
  }

  const text = await res.text()
  if (!text) return null

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

export async function request(path, options = {}) {
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
