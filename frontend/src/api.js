// api.js — WetterExtended Frontend API-Client
//
// JWT-Auth: Token wird von AuthContext via setToken() gesetzt.
// Öffentliche GET-Endpunkte (/karte, /api/objects usw.) funktionieren ohne Token.

let _token = '';
let _onUnauthorized = null;

const API_CACHE_TTL_MS = Number(import.meta?.env?.VITE_API_CACHE_TTL_MS || 3000);
const _inFlightMap = new Map();
const _memCache = new Map();
const _controllers = new Set();

export function setToken(t) {
  _token = t || '';
}

export function onUnauthorized(cb) {
  _onUnauthorized = cb;
}

export function abortApiRequests() {
  for (const controller of _controllers) controller.abort();
  _controllers.clear();
}

function _authHeaders(extra = {}) {
  const h = { 'Content-Type': 'application/json', ...extra };
  if (_token) h.Authorization = `Bearer ${_token}`;
  return h;
}

function _readHeaders() {
  return _token ? { Authorization: `Bearer ${_token}` } : {};
}

function _cacheableGet(url) {
  return !/[?&]nocache=true\b/i.test(url);
}

function _cacheKey(url) {
  return String(url);
}

async function _handleResponse(r, url) {
  if (r.status === 401) {
    if (_onUnauthorized) _onUnauthorized();
    throw new Error('Nicht authentifiziert');
  }
  if (!r.ok) {
    const err = await r.json().catch(() => ({}));
    throw new Error(err.error || `${url}: ${r.status}`);
  }
  return r.json();
}

async function _fetchJson(url, options = {}) {
  const controller = new AbortController();
  _controllers.add(controller);
  const merged = { ...options, signal: options.signal || controller.signal };
  try {
    const r = await fetch(url, merged);
    return await _handleResponse(r, url);
  } catch (err) {
    if (err?.name === 'AbortError') return Promise.reject(err);
    throw err;
  } finally {
    _controllers.delete(controller);
  }
}

const api = {
  async get(url) {
    const key = _cacheKey(url);
    if (_cacheableGet(url)) {
      const cached = _memCache.get(key);
      if (cached && Date.now() - cached.ts <= API_CACHE_TTL_MS) return cached.data;
      if (_inFlightMap.has(key)) return _inFlightMap.get(key);
    }
    const promise = _fetchJson(url, { headers: _readHeaders() })
      .then(data => {
        if (_cacheableGet(url)) _memCache.set(key, { data, ts: Date.now() });
        return data;
      })
      .finally(() => _inFlightMap.delete(key));
    if (_cacheableGet(url)) _inFlightMap.set(key, promise);
    return promise;
  },
  async post(url, body) {
    return _fetchJson(url, { method: 'POST', headers: _authHeaders(), body: JSON.stringify(body) });
  },
  async patch(url, body) {
    return _fetchJson(url, { method: 'PATCH', headers: _authHeaders(), body: JSON.stringify(body) });
  },
  async delete(url) {
    return _fetchJson(url, { method: 'DELETE', headers: _authHeaders() });
  },
  async download(url) {
    const r = await fetch(url, { headers: _readHeaders() });
    if (r.status === 401) {
      if (_onUnauthorized) _onUnauthorized();
      throw new Error('Nicht authentifiziert');
    }
    if (!r.ok) {
      const err = await r.json().catch(() => ({}));
      throw new Error(err.error || `${url}: ${r.status}`);
    }
    const disposition = r.headers.get('content-disposition') || '';
    const match = disposition.match(/filename\*=UTF-8''([^;]+)|filename="?([^";]+)"?/i);
    const filename = match ? decodeURIComponent(match[1] || match[2]) : 'wetterextended_debug_last24h.zip';
    return { blob: await r.blob(), filename };
  },
};

export default api;
