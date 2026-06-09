"""P2-1: SHA256-Dedup verhindert unnötigen Tracking-Zyklus bei identischem Inhalt."""
import importlib
import io
import sys
import types
import zipfile

import pytest


def _make_requests_mock(response_factory):
    """Erstellt einen minimalen requests-Namespace-Mock für radar_download."""
    return types.SimpleNamespace(
        get=lambda *a, **k: response_factory(),
        exceptions=types.SimpleNamespace(
            Timeout=TimeoutError,
            HTTPError=RuntimeError,
        ),
    )


def _ensure_debug_stub(monkeypatch):
    """Stellt debug_utils-Stub bereit wenn nicht installiert."""
    if "debug_utils" not in sys.modules:
        debug_utils_stub = types.ModuleType("debug_utils")
        debug_utils_stub.debug_log = lambda *a, **k: None
        debug_utils_stub.log_api_failure = lambda *a, **k: None
        debug_utils_stub.log_api_call = lambda *a, **k: None
        debug_utils_stub.log_http_response = lambda *a, **k: None
        monkeypatch.setitem(sys.modules, "debug_utils", debug_utils_stub)


def _rd(monkeypatch):
    """
    Importiert radar_download frisch (kein sys.modules-Cache).
    B102: requests wird als Modul-Attribut ersetzt, nicht via rd.requests.get,
    damit der Test unabhängig vom requests-Stub-Typ funktioniert.
    """
    _ensure_debug_stub(monkeypatch)

    # requests-Stub in sys.modules setzen falls nicht vorhanden
    if "requests" not in sys.modules:
        requests_stub = types.ModuleType("requests")
        requests_stub.exceptions = types.SimpleNamespace(
            Timeout=TimeoutError,
            HTTPError=RuntimeError,
        )
        requests_stub.get = lambda *a, **k: None
        monkeypatch.setitem(sys.modules, "requests", requests_stub)

    # B102: radar_download frisch laden (Cache leeren)
    monkeypatch.delitem(sys.modules, "radar_download", raising=False)

    try:
        return importlib.import_module("radar_download")
    except Exception as exc:
        pytest.skip(f"radar_download nicht importierbar: {exc}")


def _make_zip(entries: dict) -> bytes:
    """Erstellt minimales ZIP mit den angegebenen Name→Content Einträgen."""
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as zf:
        for name, content in entries.items():
            zf.writestr(name, content)
    return buf.getvalue()


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


def test_write_and_read_content_hash(tmp_path, monkeypatch):
    rd = _rd(monkeypatch)
    monkeypatch.setattr(rd, "_CONTENT_HASH_FILE", str(tmp_path / ".kmz_content_sha256"))
    rd._write_content_hash(b"hello radar")
    h = rd._read_content_hash()
    assert h is not None and len(h) == 64  # SHA256 hex


def test_same_content_returns_false(tmp_path, monkeypatch):
    """Identischer KMZ-Inhalt → kein Tracking-Zyklus (False)."""
    rd = _rd(monkeypatch)
    monkeypatch.setattr(rd, "_CONTENT_HASH_FILE", str(tmp_path / ".kmz_content_sha256"))
    monkeypatch.setattr(rd, "_LAST_MODIFIED_FILE", str(tmp_path / ".kmz_last_modified"))
    monkeypatch.setattr(rd, "KMZ_PATH", str(tmp_path / "weather_data.kmz"))
    monkeypatch.chdir(tmp_path)

    content = _make_zip({"dummy.kml": "<kml/>", "dummy.png": b"\x89PNG\r\n"})
    rd._write_content_hash(content)  # Vorgänger-Hash setzen

    class _Resp:
        status_code = 200
        headers = {
            "Last-Modified": "Mon, 09 Jun 2026 09:00:00 GMT",
            "content-type": "application/zip",
        }
        text = ""

        def raise_for_status(self):
            pass

        def json(self):
            return {}

    _Resp.content = content  # identisch

    # B102: requests-Namespace im Modul direkt ersetzen
    monkeypatch.setattr(rd, "requests", _make_requests_mock(lambda: _Resp()))
    monkeypatch.setattr(rd, "log_api_call", lambda *a, **k: None)
    monkeypatch.setattr(rd, "log_http_response", lambda *a, **k: None)

    result = rd.download_kmz()
    assert result is False  # identischer Inhalt → kein neuer Zyklus


def test_different_content_returns_true(tmp_path, monkeypatch):
    """Neuer KMZ-Inhalt → Tracking-Zyklus wird gestartet (True)."""
    rd = _rd(monkeypatch)
    monkeypatch.setattr(rd, "_CONTENT_HASH_FILE", str(tmp_path / ".kmz_content_sha256"))
    monkeypatch.setattr(rd, "_LAST_MODIFIED_FILE", str(tmp_path / ".kmz_last_modified"))
    monkeypatch.setattr(rd, "KMZ_PATH", str(tmp_path / "weather_data.kmz"))
    monkeypatch.chdir(tmp_path)

    rd._write_content_hash(b"old content")  # anderer Vorgänger

    new_content = _make_zip({"new_radar.kml": "<kml/>", "new_radar.png": b"\x89PNG\r\n"})

    class _Resp:
        status_code = 200
        headers = {
            "Last-Modified": "Mon, 09 Jun 2026 09:05:00 GMT",
            "content-type": "application/zip",
        }
        text = ""

        def raise_for_status(self):
            pass

        def json(self):
            return {}

    _Resp.content = new_content

    # B102: requests-Namespace im Modul direkt ersetzen
    monkeypatch.setattr(rd, "requests", _make_requests_mock(lambda: _Resp()))
    monkeypatch.setattr(rd, "log_api_call", lambda *a, **k: None)
    monkeypatch.setattr(rd, "log_http_response", lambda *a, **k: None)

    result = rd.download_kmz()
    assert result is True  # neuer Inhalt → Zyklus starten
