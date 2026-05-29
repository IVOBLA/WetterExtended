// api.js — WetterExtended Frontend API-Client
// Sendet JWT Access Tokens als Bearer Header und meldet 401-Antworten
// an den AuthContext zurück, damit die Session lokal beendet werden kann.

let _accessToken = ''
let _unauthorizedCallback = null

export function setToken(token) {
  _accessToken = token || ''
}

export function onUnauthorized(callback) {
  _unauthorizedCallback = typeof callback === 'function' ? callback : null
}

function _headers(extra = {}) {
  const h = { 'Content-Type': 'application/json', ...extra }
  if (_accessToken) h.Authorization = `Bearer ${_accessToken}`
  return h
}

async function _handleResponse(r, url) {
  if (r.status === 401 && _unauthorizedCallback) {
    _unauthorizedCallback()
  }
  if (!r.ok) {
    const err = await r.json().catch(() => ({}))
    throw new Error(err.error || `${url}: ${r.status}`)
  }
  return r.json()
}

const api = {
  async get(url) {
    const r = await fetch(url, {
      headers: _accessToken ? { Authorization: `Bearer ${_accessToken}` } : {},
      credentials: 'include',
    })
    return _handleResponse(r, url)
  },
  async post(url, body) {
    const r = await fetch(url, {
      method: 'POST',
      headers: _headers(),
      credentials: 'include',
      body: JSON.stringify(body),
    })
    return _handleResponse(r, url)
  },
  async patch(url, body) {
    const r = await fetch(url, {
      method: 'PATCH',
      headers: _headers(),
      credentials: 'include',
      body: JSON.stringify(body),
    })
    return _handleResponse(r, url)
  },
  async delete(url) {
    const r = await fetch(url, {
      method: 'DELETE',
      headers: _accessToken ? { Authorization: `Bearer ${_accessToken}` } : {},
      credentials: 'include',
    })
    return _handleResponse(r, url)
  },
}

export default api
