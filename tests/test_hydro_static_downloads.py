import zipfile
from pathlib import Path
import hydro_static_import as h

class Resp:
    status_code=200; headers={"content-type":"application/zip"}; url="https://example/x.zip"; text=""; request=type("R",(),{"headers":{}})()
    @property
    def content(self):
        import io
        b=io.BytesIO()
        with zipfile.ZipFile(b,"w") as zf: zf.writestr("a.txt","abc")
        return b.getvalue()

def test_cached_download_is_not_reloaded(tmp_path, monkeypatch):
    monkeypatch.setattr(h.config, "HYDRO_DRAINAGEBASIN_GDB_URL", "https://example/x.zip")
    p = tmp_path / "source/_downloads/x.zip"; p.parent.mkdir(parents=True)
    with zipfile.ZipFile(p, "w") as zf: zf.writestr("cached.txt", "cached")
    monkeypatch.setitem(__import__('sys').modules, 'http_retry', type('M',(),{'retry_get':lambda *a,**k: (_ for _ in ()).throw(AssertionError('network'))})())
    info = h.download_basins(str(tmp_path))
    assert info["status"] == "cached"

def test_zero_byte_download_is_reloaded(tmp_path, monkeypatch):
    import sys, types
    monkeypatch.setattr(h.config, "HYDRO_DRAINAGEBASIN_GDB_URL", "https://example/x.zip")
    p = tmp_path / "source/_downloads/x.zip"; p.parent.mkdir(parents=True); p.write_bytes(b"")
    monkeypatch.setitem(sys.modules, 'http_retry', types.SimpleNamespace(retry_get=lambda *a,**k: Resp()))
    monkeypatch.setitem(sys.modules, 'external_response_logger', types.SimpleNamespace(persist_requests_response=lambda *a,**k: None, persist_external_response=lambda *a,**k: None))
    info = h.download_basins(str(tmp_path))
    assert info["status"] == "downloaded" and zipfile.is_zipfile(p)
