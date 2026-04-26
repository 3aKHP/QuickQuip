const BASE = import.meta.env.BASE_URL.replace(/\/$/, '')

class ApiError extends Error {
  status: number
  _isUnauthorized?: boolean
  data?: unknown
  constructor(message: string, status: number) {
    super(message)
    this.status = status
  }
}

let unauthorizedHandler: (() => void) | null = null

export function setUnauthorizedHandler(handler: (() => void) | null): void {
  unauthorizedHandler = handler
}

function formatErrorDetail(detail: unknown): string {
  if (typeof detail === 'string') return detail
  if (Array.isArray(detail)) {
    return detail.map(item => {
      if (typeof item === 'string') return item
      if (typeof item === 'object' && item !== null) {
        const record = item as Record<string, unknown>
        const loc = Array.isArray(record.loc) ? record.loc.join('.') : ''
        const msg = typeof record.msg === 'string' ? record.msg : JSON.stringify(record)
        return loc ? `${loc}: ${msg}` : msg
      }
      return String(item)
    }).join('; ')
  }
  if (typeof detail === 'object' && detail !== null) return JSON.stringify(detail)
  return String(detail)
}

async function parseResponse(res: Response) {
  if (res.status === 401) {
    if (unauthorizedHandler) unauthorizedHandler()
    const err = new ApiError('401 admin login required', 401)
    err._isUnauthorized = true
    throw err
  }

  const text = await res.text()
  if (!text) return null

  let data: unknown
  try {
    data = JSON.parse(text)
  } catch {
    if (!res.ok) throw new Error(`${res.status}: ${res.statusText}`)
    return text
  }

  if (!res.ok) {
    const detail = typeof data === 'object' && data !== null && 'detail' in data
      ? (data as Record<string, unknown>).detail
      : res.statusText
    const err = new ApiError(`${res.status} ${formatErrorDetail(detail)}`, res.status)
    err.data = data
    throw err
  }

  return data
}

export async function request(path: string, options: RequestInit = {}): Promise<any> {
  const headers: Record<string, string> = {}
  const incoming = options.headers
  if (incoming) {
    if (Array.isArray(incoming)) {
      for (const [k, v] of incoming) headers[k] = v
    } else if (incoming instanceof Headers) {
      incoming.forEach((v, k) => { headers[k] = v })
    } else {
      Object.assign(headers, incoming)
    }
  }
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
