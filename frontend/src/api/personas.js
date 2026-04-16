import { request } from './index.js'

export async function listPersonas() {
  return request('/api/personas')
}

export async function fetchPersona(name) {
  return request(`/api/personas/${encodeURIComponent(name)}`)
}

export async function updatePersona(name, content) {
  return request(`/api/personas/${encodeURIComponent(name)}`, {
    method: 'PUT',
    body: JSON.stringify({ content }),
  })
}

export async function createPersona(name, content) {
  return request('/api/personas', {
    method: 'POST',
    body: JSON.stringify({ name, content }),
  })
}

export async function deletePersona(name) {
  return request(`/api/personas/${encodeURIComponent(name)}`, {
    method: 'DELETE',
  })
}
