import { request } from './index'

export async function listPersonas() {
  return request('/api/personas')
}

export async function fetchPersona(name: string) {
  return request(`/api/personas/${encodeURIComponent(name)}`)
}

export async function updatePersona(name: string, content: string) {
  return request(`/api/personas/${encodeURIComponent(name)}`, {
    method: 'PUT',
    body: JSON.stringify({ content }),
  })
}

export async function createPersona(name: string, content: string) {
  return request('/api/personas', {
    method: 'POST',
    body: JSON.stringify({ name, content }),
  })
}

export async function deletePersona(name: string) {
  return request(`/api/personas/${encodeURIComponent(name)}`, {
    method: 'DELETE',
  })
}
