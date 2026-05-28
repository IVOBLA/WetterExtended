# auth.py — WetterExtended JWT-Benutzerverwaltung
#
# Ersetzt nginx Basic-Auth + ADMIN_API_TOKEN durch rollenbasiertes JWT-Auth.
#
# Rollen:
#   superadmin  — alle Rechte + Benutzerverwaltung
#   admin       — alle Konfigurationen, kein User-Management
#   operator    — manuelle Aktionen (Training, Radar-Refresh), keine Konfiguration
#   viewer      — nur Lesen
#
# Token-Strategie:
#   Access Token:  JWT, 1h Laufzeit, im React-Memory (kein localStorage)
#   Refresh Token: JWT, 7 Tage, HttpOnly-Cookie (Pfad /api/auth/)
#   Blacklist:     SQLite-Tabelle refresh_token_blacklist (JTI-basiert)

import os
import sqlite3
import uuid
from datetime import datetime, timedelta, timezone
from functools import wraps
from pathlib import Path

import bcrypt
import jwt
from flask import Blueprint, jsonify, make_response, request

# ---------------------------------------------------------------------------
# Konfiguration
# ---------------------------------------------------------------------------
_PROJECT_DIR = Path(__file__).parent.resolve()
_DB_PATH = _PROJECT_DIR / "users.db"

_JWT_SECRET: str = os.getenv("JWT_SECRET", "").strip()
_ACCESS_TOKEN_MINUTES = 60
_REFRESH_TOKEN_DAYS = 7
_REFRESH_COOKIE = "we_refresh"

ROLES = ("superadmin", "admin", "operator", "viewer")

ROLE_LEVEL: dict[str, int] = {
    "superadmin": 40,
    "admin":      30,
    "operator":   20,
    "viewer":     10,
}

if not _JWT_SECRET:
    import secrets as _sec
    _JWT_SECRET = _sec.token_hex(32)
    print(
        "[AUTH] JWT_SECRET nicht in .env gesetzt — zufälliger Secret wurde generiert. "
        "Alle Sessions werden nach App-Neustart invalidiert. "
        "Fuege JWT_SECRET=<wert> zur .env-Datei hinzu (openssl rand -hex 32).",
        flush=True,
    )

auth_bp = Blueprint("auth", __name__)

# ---------------------------------------------------------------------------
# Datenbank
# ---------------------------------------------------------------------------

def _get_db() -> sqlite3.Connection:
    conn = sqlite3.connect(str(_DB_PATH))
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA foreign_keys=ON")
    return conn


def init_db() -> None:
    """Erstellt Tabellen falls nicht vorhanden. Legt Superadmin an wenn DB leer."""
    _DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    with _get_db() as conn:
        conn.execute("""
            CREATE TABLE IF NOT EXISTS users (
                id            INTEGER PRIMARY KEY AUTOINCREMENT,
                username      TEXT    NOT NULL UNIQUE,
                password_hash TEXT    NOT NULL,
                role          TEXT    NOT NULL
                              CHECK(role IN ('superadmin','admin','operator','viewer')),
                created_at    TEXT    NOT NULL,
                last_login    TEXT,
                active        INTEGER NOT NULL DEFAULT 1
            )
        """)
        conn.execute("""
            CREATE TABLE IF NOT EXISTS refresh_token_blacklist (
                jti        TEXT PRIMARY KEY,
                expires_at TEXT NOT NULL
            )
        """)
        conn.commit()

        row = conn.execute("SELECT COUNT(*) AS cnt FROM users").fetchone()
        if row["cnt"] == 0:
            _create_initial_superadmin(conn)


def _create_initial_superadmin(conn: sqlite3.Connection) -> None:
    """Liest Passwort aus .admin_password oder generiert eines neu."""
    pw_file = _PROJECT_DIR / ".admin_password"
    if pw_file.exists():
        password = pw_file.read_text().strip()
    else:
        import secrets as _s
        password = _s.token_urlsafe(16)
        pw_file.write_text(password)
        pw_file.chmod(0o600)

    pw_hash = bcrypt.hashpw(password.encode(), bcrypt.gensalt()).decode()
    now = _utcnow()
    conn.execute(
        "INSERT INTO users (username, password_hash, role, created_at) VALUES (?,?,?,?)",
        ("admin", pw_hash, "superadmin", now),
    )
    conn.commit()
    print(
        f"\n╔══════════════════════════════════════════════════╗\n"
        f"║  SUPERADMIN angelegt                             ║\n"
        f"║  Benutzername: admin                             ║\n"
        f"║  Passwort:     {password:<34}║\n"
        f"╚══════════════════════════════════════════════════╝\n",
        flush=True,
    )


# ---------------------------------------------------------------------------
# JWT Helpers
# ---------------------------------------------------------------------------

def _utcnow() -> str:
    return datetime.now(timezone.utc).isoformat()


def _make_access_token(user_id: int, username: str, role: str) -> str:
    payload = {
        "sub":      str(user_id),
        "username": username,
        "role":     role,
        "exp":      datetime.now(timezone.utc) + timedelta(minutes=_ACCESS_TOKEN_MINUTES),
        "iat":      datetime.now(timezone.utc),
        "type":     "access",
    }
    return jwt.encode(payload, _JWT_SECRET, algorithm="HS256")


def _make_refresh_token(user_id: int) -> tuple[str, str]:
    """Gibt (encoded_token, jti) zurueck."""
    jti = str(uuid.uuid4())
    payload = {
        "sub":  str(user_id),
        "jti":  jti,
        "exp":  datetime.now(timezone.utc) + timedelta(days=_REFRESH_TOKEN_DAYS),
        "iat":  datetime.now(timezone.utc),
        "type": "refresh",
    }
    return jwt.encode(payload, _JWT_SECRET, algorithm="HS256"), jti


def _decode_token(token: str) -> dict:
    """Dekodiert und validiert ein JWT. Wirft jwt.PyJWTError bei Fehler."""
    return jwt.decode(token, _JWT_SECRET, algorithms=["HS256"])


def _is_blacklisted(jti: str) -> bool:
    with _get_db() as conn:
        row = conn.execute(
            "SELECT jti FROM refresh_token_blacklist WHERE jti = ?", (jti,)
        ).fetchone()
        return row is not None


def _blacklist_jti(jti: str, expires_at: str) -> None:
    with _get_db() as conn:
        conn.execute(
            "INSERT OR IGNORE INTO refresh_token_blacklist (jti, expires_at) VALUES (?,?)",
            (jti, expires_at),
        )
        conn.commit()


def _cleanup_blacklist() -> None:
    """Entfernt abgelaufene Blacklist-Eintraege."""
    now = _utcnow()
    with _get_db() as conn:
        conn.execute(
            "DELETE FROM refresh_token_blacklist WHERE expires_at < ?", (now,)
        )
        conn.commit()


# ---------------------------------------------------------------------------
# Auth-Decorator (wird in app.py before_request-Hook verwendet)
# ---------------------------------------------------------------------------

def get_current_user() -> dict | None:
    """Liest Access Token aus Authorization-Header. Gibt None bei Fehler."""
    auth_header = request.headers.get("Authorization", "")
    if not auth_header.startswith("Bearer "):
        return None
    token = auth_header[7:]
    try:
        payload = _decode_token(token)
        if payload.get("type") != "access":
            return None
        return payload
    except jwt.PyJWTError:
        return None


def require_role(*roles: str):
    """
    Decorator fuer Flask-Routen. Erlaubt Zugriff wenn der User eine der
    angegebenen Rollen hat — oder eine hoeherwertige Rolle.

    Beispiele:
        @require_role('admin')      -> admin + superadmin
        @require_role('operator')   -> operator + admin + superadmin
        @require_role('viewer')     -> alle eingeloggten User
        @require_role('superadmin') -> nur superadmin
    """
    min_level = min(ROLE_LEVEL.get(r, 0) for r in roles)

    def decorator(f):
        @wraps(f)
        def wrapper(*args, **kwargs):
            user = get_current_user()
            if user is None:
                return jsonify({"error": "Nicht authentifiziert"}), 401
            user_level = ROLE_LEVEL.get(user.get("role", ""), 0)
            if user_level < min_level:
                return jsonify({"error": "Keine Berechtigung"}), 403
            return f(*args, **kwargs)
        return wrapper
    return decorator


# ---------------------------------------------------------------------------
# Auth-Endpunkte
# ---------------------------------------------------------------------------

@auth_bp.route("/api/auth/login", methods=["POST"])
def login():
    data = request.get_json(force=True) or {}
    username = str(data.get("username", "")).strip()
    password = str(data.get("password", ""))

    if not username or not password:
        return jsonify({"error": "Benutzername und Passwort erforderlich"}), 400

    _cleanup_blacklist()

    with _get_db() as conn:
        row = conn.execute(
            "SELECT * FROM users WHERE username = ? AND active = 1", (username,)
        ).fetchone()

    if row is None:
        return jsonify({"error": "Ungueltige Anmeldedaten"}), 401

    if not bcrypt.checkpw(password.encode(), row["password_hash"].encode()):
        return jsonify({"error": "Ungueltige Anmeldedaten"}), 401

    with _get_db() as conn:
        conn.execute(
            "UPDATE users SET last_login = ? WHERE id = ?",
            (_utcnow(), row["id"]),
        )
        conn.commit()

    access_token = _make_access_token(row["id"], row["username"], row["role"])
    refresh_token, _jti = _make_refresh_token(row["id"])

    resp = make_response(jsonify({
        "access_token": access_token,
        "user": {
            "id":       row["id"],
            "username": row["username"],
            "role":     row["role"],
        },
    }))
    resp.set_cookie(
        _REFRESH_COOKIE,
        refresh_token,
        httponly=True,
        samesite="Lax",
        max_age=_REFRESH_TOKEN_DAYS * 86400,
        path="/api/auth/",
        secure=False,
    )
    return resp


@auth_bp.route("/api/auth/refresh", methods=["POST"])
def refresh():
    token = request.cookies.get(_REFRESH_COOKIE)
    if not token:
        return jsonify({"error": "Kein Refresh-Token"}), 401

    try:
        payload = _decode_token(token)
    except jwt.ExpiredSignatureError:
        return jsonify({"error": "Refresh-Token abgelaufen, bitte neu einloggen"}), 401
    except jwt.PyJWTError:
        return jsonify({"error": "Ungueltiger Refresh-Token"}), 401

    if payload.get("type") != "refresh":
        return jsonify({"error": "Falscher Token-Typ"}), 401

    jti = payload.get("jti", "")
    if _is_blacklisted(jti):
        return jsonify({"error": "Token widerrufen, bitte neu einloggen"}), 401

    user_id = int(payload["sub"])
    with _get_db() as conn:
        row = conn.execute(
            "SELECT * FROM users WHERE id = ? AND active = 1", (user_id,)
        ).fetchone()

    if row is None:
        return jsonify({"error": "Benutzer nicht gefunden oder deaktiviert"}), 401

    exp_iso = datetime.fromtimestamp(payload["exp"], tz=timezone.utc).isoformat()
    _blacklist_jti(jti, exp_iso)

    access_token = _make_access_token(row["id"], row["username"], row["role"])
    new_refresh, _new_jti = _make_refresh_token(row["id"])

    resp = make_response(jsonify({
        "access_token": access_token,
        "user": {
            "id":       row["id"],
            "username": row["username"],
            "role":     row["role"],
        },
    }))
    resp.set_cookie(
        _REFRESH_COOKIE,
        new_refresh,
        httponly=True,
        samesite="Lax",
        max_age=_REFRESH_TOKEN_DAYS * 86400,
        path="/api/auth/",
        secure=False,
    )
    return resp


@auth_bp.route("/api/auth/logout", methods=["POST"])
def logout():
    token = request.cookies.get(_REFRESH_COOKIE)
    if token:
        try:
            payload = _decode_token(token)
            jti = payload.get("jti", "")
            exp_iso = datetime.fromtimestamp(payload["exp"], tz=timezone.utc).isoformat()
            _blacklist_jti(jti, exp_iso)
        except jwt.PyJWTError:
            pass

    resp = make_response(jsonify({"ok": True}))
    resp.delete_cookie(_REFRESH_COOKIE, path="/api/auth/")
    return resp


@auth_bp.route("/api/auth/me")
def me():
    user = get_current_user()
    if user is None:
        return jsonify({"error": "Nicht authentifiziert"}), 401
    return jsonify({
        "id":       user["sub"],
        "username": user["username"],
        "role":     user["role"],
    })


# ---------------------------------------------------------------------------
# Benutzerverwaltung (nur superadmin)
# ---------------------------------------------------------------------------

@auth_bp.route("/api/users")
@require_role("superadmin")
def list_users():
    with _get_db() as conn:
        rows = conn.execute(
            "SELECT id, username, role, created_at, last_login, active FROM users ORDER BY id"
        ).fetchall()
    return jsonify([dict(r) for r in rows])


@auth_bp.route("/api/users", methods=["POST"])
@require_role("superadmin")
def create_user():
    data = request.get_json(force=True) or {}
    username = str(data.get("username", "")).strip()
    password = str(data.get("password", ""))
    role     = str(data.get("role", ""))

    if not username or not password or role not in ROLES:
        return jsonify({"error": "username, password und gueltige role erforderlich"}), 400
    if len(password) < 8:
        return jsonify({"error": "Passwort muss mindestens 8 Zeichen haben"}), 400

    pw_hash = bcrypt.hashpw(password.encode(), bcrypt.gensalt()).decode()
    try:
        with _get_db() as conn:
            conn.execute(
                "INSERT INTO users (username, password_hash, role, created_at) VALUES (?,?,?,?)",
                (username, pw_hash, role, _utcnow()),
            )
            conn.commit()
            row = conn.execute(
                "SELECT id, username, role, created_at, last_login, active "
                "FROM users WHERE username = ?",
                (username,),
            ).fetchone()
        return jsonify(dict(row)), 201
    except sqlite3.IntegrityError:
        return jsonify({"error": f"Benutzername '{username}' bereits vergeben"}), 409


@auth_bp.route("/api/users/<int:user_id>", methods=["PATCH"])
@require_role("superadmin")
def update_user(user_id: int):
    data = request.get_json(force=True) or {}
    updates: dict = {}

    if "role" in data:
        if data["role"] not in ROLES:
            return jsonify({"error": f"Ungueltige Rolle. Erlaubt: {list(ROLES)}"}), 400
        updates["role"] = data["role"]
    if "active" in data:
        updates["active"] = 1 if data["active"] else 0

    if not updates:
        return jsonify({"error": "Keine Felder zum Aktualisieren angegeben"}), 400

    set_clause = ", ".join(f"{k} = ?" for k in updates)
    values = list(updates.values()) + [user_id]
    with _get_db() as conn:
        cur = conn.execute(f"UPDATE users SET {set_clause} WHERE id = ?", values)
        conn.commit()
        if cur.rowcount == 0:
            return jsonify({"error": "Benutzer nicht gefunden"}), 404
        row = conn.execute(
            "SELECT id, username, role, created_at, last_login, active FROM users WHERE id = ?",
            (user_id,),
        ).fetchone()
    return jsonify(dict(row))


@auth_bp.route("/api/users/<int:user_id>", methods=["DELETE"])
@require_role("superadmin")
def delete_user(user_id: int):
    """Deaktiviert einen Benutzer (kein echtes Loeschen — Audit-Trail bleibt erhalten)."""
    current = get_current_user()
    if current and str(user_id) == current.get("sub"):
        return jsonify({"error": "Eigenen Account kann man nicht deaktivieren"}), 400

    with _get_db() as conn:
        cur = conn.execute("UPDATE users SET active = 0 WHERE id = ?", (user_id,))
        conn.commit()
        if cur.rowcount == 0:
            return jsonify({"error": "Benutzer nicht gefunden"}), 404
    return jsonify({"ok": True})


@auth_bp.route("/api/users/<int:user_id>/password", methods=["POST"])
@require_role("superadmin")
def reset_password(user_id: int):
    data = request.get_json(force=True) or {}
    password = str(data.get("password", ""))
    if len(password) < 8:
        return jsonify({"error": "Passwort muss mindestens 8 Zeichen haben"}), 400

    pw_hash = bcrypt.hashpw(password.encode(), bcrypt.gensalt()).decode()
    with _get_db() as conn:
        cur = conn.execute(
            "UPDATE users SET password_hash = ? WHERE id = ?", (pw_hash, user_id)
        )
        conn.commit()
        if cur.rowcount == 0:
            return jsonify({"error": "Benutzer nicht gefunden"}), 404
    return jsonify({"ok": True})
