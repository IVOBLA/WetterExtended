"""P2-1: SHA256-Dedup verhindert unnötigen Tracking-Zyklus bei identischem Inhalt."""
import importlib
import sys
import types

import pytest


def _ensure_import_testdoubles(monkeypatch):
    """Stellt für Minimal-Testumgebungen Import-Testdoubles bereit."""
    if "requests" not in sys.modules:
        requests_stub = types.ModuleType("requests")
        exceptions_stub = types.SimpleNamespace(
            Timeout=TimeoutError,
            HTTPError=RuntimeError,
        )
        requests_stub.exceptions = exceptions_stub
        requests_stub.get = lambda *a, **k: None
        monkeypatch.setitem(sys.modules, "requests", requests_stub)

    if "debug_utils" not in sys.modules:
        debug_utils_stub = types.ModuleType("debug_utils")
        debug_utils_stub.debug_log = lambda *a, **k: None
        debug_utils_stub.log_api_failure = lambda *a, **k: None
        debug_utils_stub.log_api_call = lambda *a, **k: None
        debug_utils_stub.log_http_response = lambda *a, **k: None
        monkeypatch.setitem(sys.modules, "debug_utils", debug_utils_stub)


def _rd(monkeypatch):
    _ensure_import_testdoubles(monkeypatch)
    try:
        return importlib.import_module("radar_download")
    except Exception as exc:
        pytest.skip(f"radar_download nicht importierbar: {exc}")


def test_write_and_read_content_hash(tmp_path, monkeypatch):
    rd = _rd(monkeypatch)
    monkeypatch.setattr(rd, "_CONTENT_HASH_FILE", str(tmp_path / ".kmz_content_sha256"))
    rd._write_content_hash(b"hello radar")
    h = rd._read_content_hash()
    assert h is not None and len(h) == 64  # SHA256 hex


def test_same_content_returns_false(tmp_path, monkeypatch):
    import zipfile, io
    rd = _rd(monkeypatch)
    monkeypatch.setattr(rd, "_CONTENT_HASH_FILE", str(tmp_path / ".kmz_content_sha256"))
    monkeypatch.setattr(rd, "_LAST_MODIFIED_FILE", str(tmp_path / ".kmz_last_modified"))
    monkeypatch.setattr(rd, "KMZ_PATH", str(tmp_path / "weather_data.kmz"))
    monkeypatch.chdir(tmp_path)

    # Minimal-ZIP erstellen
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as zf:
        zf.writestr("dummy.kml", "<kml/>")
        zf.writestr("dummy.png", b"\x89PNG\r\n")
    content = buf.getvalue()
    rd._write_content_hash(content)  # Vorgänger-Hash setzen

    # Mock-Response
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

    _Resp.content = content

    monkeypatch.setattr(rd.requests, "get", lambda *a, **k: _Resp())
    monkeypatch.setattr(rd, "log_api_call", lambda *a, **k: None)
    monkeypatch.setattr(rd, "log_http_response", lambda *a, **k: None)

    result = rd.download_kmz()
    assert result is False  # identischer Inhalt → kein neuer Zyklus


def test_different_content_returns_true(tmp_path, monkeypatch):
    import zipfile, io
    rd = _rd(monkeypatch)
    monkeypatch.setattr(rd, "_CONTENT_HASH_FILE", str(tmp_path / ".kmz_content_sha256"))
    monkeypatch.setattr(rd, "_LAST_MODIFIED_FILE", str(tmp_path / ".kmz_last_modified"))
    monkeypatch.setattr(rd, "KMZ_PATH", str(tmp_path / "weather_data.kmz"))
    monkeypatch.chdir(tmp_path)

    rd._write_content_hash(b"old content")  # anderer Vorgänger

    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as zf:
        zf.writestr("new_radar.kml", "<kml/>")
        zf.writestr("new_radar.png", b"\x89PNG\r\n")
    new_content = buf.getvalue()

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

    monkeypatch.setattr(rd.requests, "get", lambda *a, **k: _Resp())
    monkeypatch.setattr(rd, "log_api_call", lambda *a, **k: None)
    monkeypatch.setattr(rd, "log_http_response", lambda *a, **k: None)

    result = rd.download_kmz()
    assert result is True  # neuer Inhalt → Zyklus starten
