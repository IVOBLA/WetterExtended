"""Auto-Importer für statische Hydro-Geodaten.

Das Modul lädt ausschließlich offizielle freie INSPIRE-/Kärnten-Quellen im
expliziten Auto-/Full-Kontext, cached Downloads lokal und baut konservative
Hydro-Impact-Indizes ohne Nächster-Pegel-Fallback.
"""
from __future__ import annotations

import json
import os
import shutil
import subprocess
import time
import zipfile
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

import config
from hydro_station_index import build_station_index

STATUS_VALUES = {"hydro_ready","hydro_static_missing","hydro_static_download_failed","hydro_static_convert_failed","hydro_station_import_failed","station_catchment_unavailable","upstream_topology_missing","invalid_static_json","hydro_static_partial"}


def static_paths(static_dir: str | None = None) -> dict[str, str]:
    base = static_dir or getattr(config, "HYDRO_STATIC_DIR", "train_data/hydro/static")
    dl = getattr(config, "HYDRO_STATIC_DOWNLOAD_DIR", os.path.join(base, "source", "_downloads"))
    if not os.path.isabs(dl) and static_dir:
        dl = os.path.join(base, "source", "_downloads")
    return {
        "base": base, "source": os.path.join(base, "source"), "generated": os.path.join(base, "generated"),
        "downloads": dl,
        "stations_source": os.path.join(base, "source", "hydro_stations.geojson"),
        "basins_source": os.path.join(base, "source", "basins.geojson"),
        "flowlines_source": os.path.join(base, "source", "flowlines.geojson"),
        "stations_generated": os.path.join(base, "generated", "hydro_stations.geojson"),
        "catchments_generated": os.path.join(base, "generated", "station_catchments.geojson"),
        "index": os.path.join(base, "generated", "station_network_index.json"),
        "status": os.path.join(base, "generated", "hydro_static_status.json"),
    }


def ensure_static_dirs(static_dir: str | None = None) -> dict[str, str]:
    paths = static_paths(static_dir)
    for key in ("source", "generated", "downloads"):
        os.makedirs(paths[key], exist_ok=True)
    return paths


def _now() -> str: return datetime.now(timezone.utc).isoformat()


def _count_geojson(path: str) -> int:
    try:
        data = json.loads(Path(path).read_text(encoding="utf-8"))
        return len(data.get("features") or []) if isinstance(data, dict) else 0
    except Exception:
        return 0


def _default_downloads(paths: dict[str, str]) -> dict[str, dict]:
    return {
        "basins": {"url": getattr(config, "HYDRO_STATIC_BASINS_URL", ""), "path": str(Path(paths["downloads"]) / Path(getattr(config, "HYDRO_STATIC_BASINS_URL", "basins.zip")).name), "status": "skipped", "size_bytes": 0},
        "flowlines": {"url": getattr(config, "HYDRO_STATIC_FLOWLINES_URL", ""), "path": str(Path(paths["downloads"]) / Path(getattr(config, "HYDRO_STATIC_FLOWLINES_URL", "flowlines.zip")).name), "status": "skipped", "size_bytes": 0},
        "watercourse": {"url": getattr(config, "HYDRO_STATIC_WATERCOURSE_URL", ""), "path": str(Path(paths["downloads"]) / Path(getattr(config, "HYDRO_STATIC_WATERCOURSE_URL", "watercourse.zip")).name), "status": "skipped", "size_bytes": 0},
    }


def write_status(status: str, message: str, static_dir: str | None = None, **extra: Any) -> dict:
    paths = ensure_static_dirs(static_dir)
    missing = [p for k,p in {"stations_source":paths["stations_source"],"basins_source":paths["basins_source"],"flowlines_source":paths["flowlines_source"],"index":paths["index"]}.items() if not Path(p).exists()]
    payload = {
        "ok": status == "hydro_ready", "status": status, "message": message, "generated_at": _now(),
        "required_files": {"stations_source": paths["stations_source"], "basins_source": paths["basins_source"], "flowlines_source": paths["flowlines_source"]},
        "downloads": _default_downloads(paths), "station_count": _count_geojson(paths["stations_source"]),
        "basin_count": _count_geojson(paths["basins_source"]), "flowline_count": _count_geojson(paths["flowlines_source"]),
        "station_basin_match_count": 0, "impact_eligible_station_count": 0,
        "missing": missing, "errors": [], "warnings": [], **extra,
    }
    Path(paths["status"]).write_text(json.dumps(payload, indent=2, ensure_ascii=False)+"\n", encoding="utf-8")
    return payload


def hydro_json_to_geojson(data: Any) -> dict:
    rows = data.get("features") or data.get("stations") or data.get("data") or data.get("pegel") or [] if isinstance(data, dict) else data
    features = []
    for idx, row in enumerate(rows if isinstance(rows, list) else []):
        props = row.get("properties", row) if isinstance(row, dict) else {}
        geom = row.get("geometry") if isinstance(row, dict) else None
        lon = props.get("lon") or props.get("longitude") or props.get("lng") or props.get("x")
        lat = props.get("lat") or props.get("latitude") or props.get("y")
        if geom and geom.get("type") == "Point": lon, lat = geom.get("coordinates", [None, None])[:2]
        if lon is None or lat is None: continue
        sid = props.get("station_id") or props.get("id") or props.get("number") or props.get("pegel_id") or props.get("kennzahl") or str(idx+1)
        out = dict(props); out.setdefault("station_id", str(sid)); out.setdefault("station_name", props.get("name") or props.get("station_name") or str(sid)); out.setdefault("river_name", props.get("river") or props.get("river_name") or props.get("gewaesser") or props.get("Gewässer") or ""); out.setdefault("live_source", data.get("source") if isinstance(data, dict) else "hydro_live"); out.setdefault("live_metadata", {k: props.get(k) for k in ("q_m3s","w_cm","measured_at") if k in props})
        features.append({"type":"Feature","geometry":{"type":"Point","coordinates":[float(lon),float(lat)]},"properties":out})
    return {"type":"FeatureCollection","features":features}


def _is_http_url(source: str | None) -> bool: return urlparse(source or "").scheme in {"http","https"}


def _read_station_source(source: str, timeout: int, allow_url_import: bool) -> Any:
    if _is_http_url(source):
        if not allow_url_import: raise ValueError("URL-Import ist nur für explizit manuell gestartete CLI-/Admin-Imports erlaubt.")
        from external_response_logger import persist_requests_response
        from http_retry import retry_get
        r = retry_get(source, service="hydro_static_manual_import", timeout=timeout, max_retries=2, abort_on_4xx=True, breaker_service="hydro_static_manual_import")
        persist_requests_response("hydro", "GET", r, fallback=False)
        return r.json()
    return json.loads(Path(source).read_text(encoding="utf-8"))


def import_station_json(url: str | None = None, static_dir: str | None = None, timeout: int = 20, *, allow_url_import: bool = False) -> str:
    paths = ensure_static_dirs(static_dir); source = url or getattr(config, "HYDRO_STATIONS_LOCAL_JSON", "")
    try:
        if not source: raise ValueError("Keine lokale Pegel-JSON-Quelle angegeben.")
        gj = hydro_json_to_geojson(_read_station_source(source, timeout, allow_url_import))
        Path(paths["stations_source"]).write_text(json.dumps(gj, indent=2, ensure_ascii=False)+"\n", encoding="utf-8")
        write_status("hydro_station_import_ok", "Statischer Hydro-Pegelimport abgeschlossen.", static_dir, source_type="url" if _is_http_url(source) else "local_file", station_count=len(gj["features"]))
        return paths["stations_source"]
    except Exception as exc:
        write_status("hydro_station_import_failed", f"Statischer Hydro-Pegelimport fehlgeschlagen: {type(exc).__name__}: {exc}", static_dir, source_type="url" if _is_http_url(source) else "local_file")
        return ""


def _download(url: str, paths: dict[str,str], key: str, force: bool=False) -> dict:
    target = Path(paths["downloads"]) / Path(urlparse(url).path).name
    ttl = int(getattr(config, "HYDRO_STATIC_DOWNLOAD_TTL_DAYS", 365)) * 86400
    info = {"url": url, "path": str(target), "status": "skipped", "size_bytes": target.stat().st_size if target.exists() else 0}
    if target.exists() and target.stat().st_size > 0 and not force and time.time() - target.stat().st_mtime < ttl:
        info["status"] = "cached"; return info
    try:
        from external_response_logger import persist_requests_response, persist_external_response
        from http_retry import retry_get
        r = retry_get(url, service="hydro_static_download", timeout=60, max_retries=1, abort_on_4xx=True, breaker_service="hydro_static_download")
        persist_requests_response("hydro", "GET", r, fallback=False)
        target.write_bytes(r.content)
        info.update(status="downloaded", size_bytes=target.stat().st_size)
    except Exception as exc:
        try:
            from external_response_logger import persist_external_response
            persist_external_response("hydro", url=url, method="GET", status_code=getattr(getattr(exc,"response",None),"status_code",None), fallback=True, error=f"{type(exc).__name__}: {exc}")
        except Exception: pass
        info.update(status="failed", error=f"{type(exc).__name__}: {exc}")
    return info


def download_basins(static_dir: str | None=None, force: bool=False) -> dict: return _download(getattr(config,"HYDRO_STATIC_BASINS_URL"), ensure_static_dirs(static_dir), "basins", force)
def download_flowlines(static_dir: str | None=None, force: bool=False) -> dict:
    paths=ensure_static_dirs(static_dir); first=_download(getattr(config,"HYDRO_STATIC_FLOWLINES_URL"), paths, "flowlines", force)
    return first if first["status"]!="failed" else _download(getattr(config,"HYDRO_STATIC_WATERCOURSE_URL"), paths, "watercourse", force)

def _ogr_layers(src: str) -> list[str]:
    try:
        out = subprocess.run(["ogrinfo", src], text=True, capture_output=True, check=False, timeout=60).stdout
        layers=[]
        for line in out.splitlines():
            line=line.strip()
            if line[:1].isdigit() and ":" in line: layers.append(line.split(":",1)[1].split("(",1)[0].strip())
        return layers
    except Exception: return []

def _extract_if_zip(path: str) -> str:
    p=Path(path)
    if p.suffix.lower() != ".zip": return str(p)
    d=p.with_suffix("")
    if not d.exists() or not any(d.iterdir()):
        d.mkdir(parents=True, exist_ok=True)
        with zipfile.ZipFile(p) as z: z.extractall(d)
    for pattern in ("*.gpkg","*.gdb","*.shp","*.gml","*.xml"):
        found=list(d.rglob(pattern))
        if found: return str(found[0] if pattern != "*.gdb" else found[0])
    return str(d)

def convert_to_geojson(src: str, dst: str, kind: str, bbox: list[float] | None=None) -> bool:
    if not shutil.which("ogr2ogr") or not shutil.which("ogrinfo"): raise RuntimeError("GDAL/OGR fehlt: ogr2ogr/ogrinfo nicht gefunden")
    dataset=_extract_if_zip(src); layers=_ogr_layers(dataset)
    prefs = ["drainagebasin","catchment"] if kind=="basins" else ["watercourselink","watercourse","flowline"]
    layer = next((l for l in layers if any(p in l.lower() for p in prefs)), layers[0] if layers else None)
    cmd=["ogr2ogr","-f","GeoJSON","-t_srs","EPSG:4326",dst,dataset]
    if bbox or getattr(config,"HYDRO_STATIC_BBOX", None): cmd += ["-spat", *map(str, bbox or getattr(config,"HYDRO_STATIC_BBOX"))]
    if layer: cmd.append(layer)
    res=subprocess.run(cmd, text=True, capture_output=True, check=False, timeout=300)
    if res.returncode != 0: raise RuntimeError((res.stderr or res.stdout or "ogr2ogr fehlgeschlagen").strip())
    return Path(dst).exists() and Path(dst).stat().st_size > 0


def ensure_live_json(static_dir: str | None=None) -> str:
    from hydro_fetch import LATEST_FILE, fetch_hydro_live
    if not LATEST_FILE.exists() or LATEST_FILE.stat().st_size == 0: fetch_hydro_live(force=True)
    return str(LATEST_FILE)


def build_static_hydro(static_dir: str | None = None, downloads: dict | None=None) -> dict:
    paths=ensure_static_dirs(static_dir); missing=[n for n in ("stations_source","basins_source") if not Path(paths[n]).exists()]
    if missing: return write_status("hydro_static_missing", "Statische Hydro-Eingangsdaten fehlen; Hydro-Impact ist noch nicht aktiv.", static_dir, missing=missing, downloads=downloads or _default_downloads(paths))
    status=build_station_index(paths["stations_source"], paths["basins_source"], paths["flowlines_source"] if Path(paths["flowlines_source"]).exists() else None, paths["generated"])
    status["downloads"] = downloads or _default_downloads(paths); status.setdefault("required_files", {"stations_source":paths["stations_source"],"basins_source":paths["basins_source"],"flowlines_source":paths["flowlines_source"]}); status.setdefault("errors", []); status.setdefault("warnings", []); status.setdefault("missing", [])
    Path(paths["status"]).write_text(json.dumps(status, indent=2, ensure_ascii=False)+"\n", encoding="utf-8")
    return status


def auto(static_dir: str | None=None) -> dict:
    paths=ensure_static_dirs(static_dir); downloads=_default_downloads(paths); errors=[]; warnings=[]
    try: import_station_json(ensure_live_json(static_dir), static_dir)
    except Exception as exc: errors.append(f"live_station_import: {type(exc).__name__}: {exc}")
    downloads["basins"] = download_basins(static_dir)
    downloads["flowlines"] = download_flowlines(static_dir)
    try:
        if downloads["basins"].get("status") != "failed": convert_to_geojson(downloads["basins"]["path"], paths["basins_source"], "basins")
        else: errors.append(downloads["basins"].get("error","basins download failed"))
    except Exception as exc: errors.append(f"basins_convert: {type(exc).__name__}: {exc}")
    try:
        if downloads["flowlines"].get("status") != "failed": convert_to_geojson(downloads["flowlines"]["path"], paths["flowlines_source"], "flowlines")
        else: warnings.append(downloads["flowlines"].get("error","flowlines download failed"))
    except Exception as exc: warnings.append(f"flowlines_convert: {type(exc).__name__}: {exc}")
    if any(d.get("status")=="failed" for d in downloads.values() if isinstance(d,dict)):
        return write_status("hydro_static_download_failed", "Hydro-Static-Download fehlgeschlagen; Installation läuft weiter.", static_dir, downloads=downloads, errors=errors, warnings=warnings)
    if errors:
        return write_status("hydro_static_convert_failed", "Hydro-Static-Konvertierung fehlgeschlagen; Installation läuft weiter.", static_dir, downloads=downloads, errors=errors, warnings=warnings)
    status=build_static_hydro(static_dir, downloads)
    status.setdefault("warnings", []).extend(warnings)
    if status.get("status") not in {"hydro_ready","upstream_topology_missing"}: status["status"]="hydro_static_partial"
    Path(paths["status"]).write_text(json.dumps(status, indent=2, ensure_ascii=False)+"\n", encoding="utf-8")
    return status


def status(static_dir: str | None=None) -> dict:
    paths=ensure_static_dirs(static_dir)
    if Path(paths["status"]).exists():
        try: return json.loads(Path(paths["status"]).read_text(encoding="utf-8"))
        except Exception as exc: return write_status("invalid_static_json", f"Status JSON ungültig: {exc}", static_dir)
    return write_status("hydro_static_missing", "Hydro-Static-Status fehlt.", static_dir)

def verify(static_dir: str | None=None) -> dict: return status(static_dir) if Path(static_paths(static_dir)["status"]).exists() else build_static_hydro(static_dir)


def _main() -> int:
    import argparse
    p=argparse.ArgumentParser(description="Hydro-Static Auto-Importer")
    p.add_argument("--static-dir", default=None); p.add_argument("--status", action="store_true"); p.add_argument("--auto", action="store_true"); p.add_argument("--download-all", action="store_true"); p.add_argument("--download-basins", action="store_true"); p.add_argument("--download-flowlines", action="store_true"); p.add_argument("--build", action="store_true"); p.add_argument("--verify", action="store_true"); p.add_argument("--import-stations"); p.add_argument("--allow-url-import", action="store_true")
    a=p.parse_args(); out=None
    if a.status: out=status(a.static_dir)
    elif a.auto: out=auto(a.static_dir)
    elif a.download_all: paths=ensure_static_dirs(a.static_dir); out={"downloads":{"basins":download_basins(a.static_dir),"flowlines":download_flowlines(a.static_dir)}}
    elif a.download_basins: out=download_basins(a.static_dir)
    elif a.download_flowlines: out=download_flowlines(a.static_dir)
    elif a.import_stations: out={"path": import_station_json(a.import_stations, a.static_dir, allow_url_import=a.allow_url_import)}
    elif a.build: out=build_static_hydro(a.static_dir)
    elif a.verify: out=verify(a.static_dir)
    else: out=build_static_hydro(a.static_dir)
    print(json.dumps(out, indent=2, ensure_ascii=False)); return 0
if __name__ == "__main__": raise SystemExit(_main())
