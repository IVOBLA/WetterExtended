// api.js — WetterExtended Frontend API-Client
//
// JWT-Auth: Token wird von AuthContext via setToken() gesetzt.
// Alle Requests senden Authorization: Bearer <token> wenn Token vorhanden.
// Bei 401-Response → onUnauthorized-Callback wird aufgerufen (AuthContext
// registriert diesen und löscht daraufhin den User-State).
//
// Öffentliche GET-Endpunkte (/karte, /api/objects usw.) funktionieren
// ohne Token — da Backend alle GETs öffentlich lässt.

let _token = '';
let _onUnauthorized = null;

/** Wird von AuthContext aufgerufen wenn Token gesetzt/gelöscht wird. */
export function setToken(t) {
  _token = t || '';
}

/** Wird von AuthContext registriert — löst Logout aus bei 401. */
export function onUnauthorized(cb) {
  _onUnauthorized = cb;
}

function _authHeaders(extra = {}) {
  const h = { 'Content-Type': 'application/json', ...extra };
  if (_token) h['Authorization'] = `Bearer ${_token}`;
  return h;
}

function _readHeaders() {
  return _token ? { Authorization: `Bearer ${_token}` } : {};
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

const api = {
  async get(url) {
    const r = await fetch(url, { headers: _readHeaders() });
    return _handleResponse(r, url);
  },
  async post(url, body) {
    const r = await fetch(url, {
      method: 'POST',
      headers: _authHeaders(),
      body: JSON.stringify(body),
    });
    return _handleResponse(r, url);
  },
  async patch(url, body) {
    const r = await fetch(url, {
      method: 'PATCH',
      headers: _authHeaders(),
      body: JSON.stringify(body),
    });
    return _handleResponse(r, url);
  },
  async delete(url) {
    const r = await fetch(url, {
      method: 'DELETE',
      headers: _authHeaders(),
    });
    return _handleResponse(r, url);
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
