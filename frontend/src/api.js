// api.js — WetterExtended Frontend API-Client
// P10: Holt beim Start den Admin-Token für Schreiboperationen
// und sendet ihn als X-Admin-Token Header bei POST/PATCH/DELETE.

let _adminToken = '';

async function _initToken() {
  try {
    const r = await fetch('/api/admin_token');
    if (r.ok) {
      const d = await r.json();
      _adminToken = d.token || '';
    }
  } catch (_) {
    // Token-Auth deaktiviert oder Endpoint nicht erreichbar — kein Fehler
  }
}

// Token nur im Admin-Bereich holen — nicht auf der öffentlichen /karte.
// Verhindert 401-Noise in der Konsole wenn /karte ohne Login geöffnet wird.
if (!window.location.pathname.startsWith('/karte')) {
  _initToken();
}

function _writeHeaders(extra) {
  const h = { 'Content-Type': 'application/json', ...extra };
  if (_adminToken) h['X-Admin-Token'] = _adminToken;
  return h;
}

const api = {
  async get(url) {
    const r = await fetch(url);
    if (!r.ok) throw new Error(`${url}: ${r.status}`);
    return r.json();
  },
  async post(url, body) {
    const r = await fetch(url, {
      method: 'POST',
      headers: _writeHeaders(),
      body: JSON.stringify(body)
    });
    if (!r.ok) {
      const err = await r.json().catch(() => ({}));
      throw new Error(err.error || `${url}: ${r.status}`);
    }
    return r.json();
  },
  async patch(url, body) {
    const r = await fetch(url, {
      method: 'PATCH',
      headers: _writeHeaders(),
      body: JSON.stringify(body)
    });
    if (!r.ok) {
      const err = await r.json().catch(() => ({}));
      throw new Error(err.error || `${url}: ${r.status}`);
    }
    return r.json();
  },
  async delete(url) {
    const r = await fetch(url, {
      method: 'DELETE',
      headers: _adminToken ? { 'X-Admin-Token': _adminToken } : {}
    });
    if (!r.ok) {
      const err = await r.json().catch(() => ({}));
      throw new Error(err.error || `${url}: ${r.status}`);
    }
    return r.json();
  }
};

export default api;
