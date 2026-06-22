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
import tempfile
import time
import zipfile
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

import config
from hydro_station_index import build_station_index

STATUS_VALUES = {"ok","hydro_ready","hydro_static_missing","basins_available","flowlines_missing","hydro_static_ready","hydro_static_download_failed","hydro_static_convert_failed","hydro_station_import_failed","station_catchment_unavailable","station_basin_available","station_basin_unavailable","upstream_topology_missing","invalid_static_json","hydro_static_partial"}


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
        "coverage": os.path.join(base, "generated", "hydro_static_coverage.json"),
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



def _config_url(name: str, fallback: str = "") -> str:
    return str(getattr(config, name, "") or getattr(config, fallback, "") or "")


def _download_url_to_path(url: str, paths: dict[str, str], default_name: str) -> Path:
    name = Path(urlparse(url).path).name or default_name
    return Path(paths["downloads"]) / name


def _valid_cached_file(path: Path) -> bool:
    if not path.exists() or path.stat().st_size <= 0:
        return False
    if path.suffix.lower() == ".zip":
        try:
            return zipfile.is_zipfile(path) and not zipfile.ZipFile(path).testzip()
        except Exception:
            return False
    return True




def _geojson_valid(path: str, kind: str, bbox: list[float] | None = None) -> bool:
    try:
        validate_geojson_output(path, kind, bbox)
        return True
    except Exception:
        return False


def _download_size(path: str | Path | None) -> int:
    try:
        p = Path(path or "")
        return p.stat().st_size if p.exists() else 0
    except Exception:
        return 0


def _refresh_download_size(info: dict) -> dict:
    if isinstance(info, dict):
        info["size_bytes"] = _download_size(info.get("path"))
    return info


def _download_urls_for(kind: str) -> list[str]:
    if kind == "flowlines":
        urls = [
            _config_url("HYDRO_FLOWLINES_GDB_URL", "HYDRO_STATIC_FLOWLINES_URL"),
            getattr(config, "HYDRO_STATIC_WATERCOURSE_URL", ""),
        ]
    else:
        urls = [_config_url("HYDRO_DRAINAGEBASIN_GDB_URL", "HYDRO_STATIC_BASINS_URL")]
    out=[]
    for url in urls:
        if url and url not in out:
            out.append(url)
    return out

def _normalize_bbox(value: Any) -> list[float] | None:
    if isinstance(value, dict):
        try:
            return [float(value["west"]), float(value["south"]), float(value["east"]), float(value["north"])]
        except Exception:
            return None
    if isinstance(value, (list, tuple)) and len(value) == 4:
        try:
            return [float(v) for v in value]
        except Exception:
            return None
    return None


def _feature_identifier(props: dict[str, Any]) -> str:
    candidates = ["HYDROID", "ID", "IDENTIFIER", "INSPIREID_IDENTIFIER_LOCALID", "OBJECTID"]
    lower = {str(k).lower(): v for k, v in props.items()}
    for key in candidates:
        val = props.get(key)
        if val in (None, ""):
            val = lower.get(key.lower())
        if val not in (None, ""):
            return str(val)
    return ""


def normalize_basin_properties(path: str) -> bool:
    p = Path(path)
    data = json.loads(p.read_text(encoding="utf-8"))
    changed = False
    for idx, feature in enumerate(data.get("features") or [], start=1):
        props = feature.setdefault("properties", {})
        ident = _feature_identifier(props) or str(idx)
        for key in ("catchment_id", "basin_id", "id"):
            if props.get(key) in (None, ""):
                props[key] = ident
                changed = True
    if changed:
        p.write_text(json.dumps(data, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    return True


KAERNTEN_BBOX = [12.55, 46.25, 15.25, 47.25]
FELDKIRCHEN_BBOX = [13.78, 46.62, 14.22, 46.88]
FELDKIRCHEN_POINTS = {
    "feldkirchen": (14.0958, 46.7237),
    "poitschach": (14.045, 46.754),
    "tiebel_glan_ossiacher_see_umfeld": (13.98, 46.68),
}


def _geom_bbox(geom: dict | None) -> list[float] | None:
    if not isinstance(geom, dict):
        return None
    vals=[]
    def walk(x):
        if isinstance(x, (list, tuple)):
            if len(x) >= 2 and all(isinstance(v, (int, float)) for v in x[:2]):
                vals.append((float(x[0]), float(x[1])))
            else:
                for y in x: walk(y)
    walk(geom.get("coordinates"))
    if not vals: return None
    xs=[v[0] for v in vals]; ys=[v[1] for v in vals]
    return [min(xs), min(ys), max(xs), max(ys)]


def _bbox_intersects(a: list[float] | None, b: list[float] | None) -> bool:
    return bool(a and b and a[0] <= b[2] and a[2] >= b[0] and a[1] <= b[3] and a[3] >= b[1])


def _bbox_contains_point(b: list[float], lon: float, lat: float) -> bool:
    return b[0] <= lon <= b[2] and b[1] <= lat <= b[3]


def _load_geojson(path: str) -> dict:
    p=Path(path)
    if not p.exists() or p.stat().st_size <= 163:
        raise ValueError(f"{p.name} ist leer/zu klein ({p.stat().st_size if p.exists() else 0} Bytes)")
    data=json.loads(p.read_text(encoding="utf-8"))
    if not isinstance(data, dict) or data.get("type") != "FeatureCollection":
        raise ValueError(f"{p.name} ist keine GeoJSON FeatureCollection")
    if not data.get("features"):
        raise ValueError(f"{p.name} enthält keine Features")
    return data


def validate_geojson_output(path: str, kind: str, bbox: list[float] | None=None) -> dict:
    data=_load_geojson(path); bbox = bbox or KAERNTEN_BBOX
    features=data.get("features") or []
    expected = {"Polygon", "MultiPolygon"} if kind == "basins" else {"LineString", "MultiLineString"}
    hits=[]; typed_hits=0
    for f in features:
        geom=f.get("geometry") if isinstance(f, dict) else None
        gtype=geom.get("type") if isinstance(geom, dict) else ""
        gb=_geom_bbox(geom)
        if gtype in expected and _bbox_intersects(gb, bbox):
            typed_hits += 1
            hits.append(f)
    if not hits:
        raise ValueError(f"{Path(path).name} enthält keine {('/'.join(sorted(expected)))}-Features in Kärnten-BBOX")
    if typed_hits <= 0:
        raise ValueError(f"{Path(path).name} enthält keine passenden Geometrien in Kärnten-BBOX")
    return {"feature_count": len(features), "bbox_hit_count": len(hits)}


def check_coverage(area: str="feldkirchen", static_dir: str | None=None) -> dict:
    if area.lower() != "feldkirchen":
        raise ValueError("Derzeit wird nur 'feldkirchen' unterstützt")
    paths=ensure_static_dirs(static_dir); errors=[]; sample_names=[]; sample_ids=[]
    basin_hits=[]; flow_hits=[]; samples={}
    try:
        basins=_load_geojson(paths["basins_source"])
        for f in basins.get("features") or []:
            if _bbox_intersects(_geom_bbox(f.get("geometry")), FELDKIRCHEN_BBOX):
                basin_hits.append(f)
                if len(sample_ids) < 10: sample_ids.append(_feature_identifier(f.get("properties") or {}) or str(len(sample_ids)+1))
    except Exception as exc: errors.append(f"basins: {type(exc).__name__}: {exc}")
    try:
        flows=_load_geojson(paths["flowlines_source"])
        for f in flows.get("features") or []:
            geom=f.get("geometry") or {}; props=f.get("properties") or {}
            if geom.get("type") in {"LineString","MultiLineString"} and _bbox_intersects(_geom_bbox(geom), FELDKIRCHEN_BBOX):
                flow_hits.append(f)
                name=props.get("name") or props.get("NAME") or props.get("gewaesser") or props.get("river") or props.get("GN")
                if name and name not in sample_names and len(sample_names) < 10: sample_names.append(str(name))
    except Exception as exc: errors.append(f"flowlines: {type(exc).__name__}: {exc}")
    coverage_bbox = None
    all_boxes=[_geom_bbox(f.get("geometry")) for f in basin_hits + flow_hits]
    all_boxes=[b for b in all_boxes if b]
    if all_boxes:
        coverage_bbox=[min(b[0] for b in all_boxes), min(b[1] for b in all_boxes), max(b[2] for b in all_boxes), max(b[3] for b in all_boxes)]
    for name,(lon,lat) in FELDKIRCHEN_POINTS.items():
        samples[name] = bool(coverage_bbox and _bbox_contains_point(coverage_bbox, lon, lat))
    if not basin_hits: errors.append("feldkirchen_basins_missing")
    if not flow_hits: errors.append("feldkirchen_flowlines_missing")
    if not any(samples.values()): errors.append("feldkirchen_sample_places_outside_data_extent")
    out={"coverage_ok": not errors, "area": "feldkirchen", "basin_features_feldkirchen": len(basin_hits), "flowline_features_feldkirchen": len(flow_hits), "sample_river_names": sample_names, "sample_basin_ids": sample_ids, "sample_places": samples, "errors": errors, "generated_at": _now()}
    Path(paths["coverage"]).write_text(json.dumps(out, indent=2, ensure_ascii=False)+"\n", encoding="utf-8")
    return out

def _default_downloads(paths: dict[str, str]) -> dict[str, dict]:
    basins_url = _config_url("HYDRO_DRAINAGEBASIN_GDB_URL", "HYDRO_STATIC_BASINS_URL")
    flow_url = _config_url("HYDRO_FLOWLINES_GDB_URL", "HYDRO_STATIC_FLOWLINES_URL")
    water_url = getattr(config, "HYDRO_STATIC_WATERCOURSE_URL", "")
    items = {
        "basins": {"url": basins_url, "path": str(_download_url_to_path(basins_url, paths, "basins.zip")), "status": "skipped"},
        "flowlines": {"url": flow_url, "path": str(_download_url_to_path(flow_url, paths, "flowlines.zip")), "status": "skipped"},
        "watercourse": {"url": water_url, "path": str(_download_url_to_path(water_url, paths, "watercourse.zip")), "status": "skipped"},
    }
    for info in items.values():
        _refresh_download_size(info)
    return items


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
    if not url:
        return {"url": url, "path": "", "status": "skipped", "size_bytes": 0, "error": "missing_url"}
    target = _download_url_to_path(url, paths, f"{key}.zip")
    ttl = int(getattr(config, "HYDRO_STATIC_DOWNLOAD_TTL_DAYS", 365)) * 86400
    info = {"url": url, "path": str(target), "status": "skipped", "size_bytes": target.stat().st_size if target.exists() else 0}
    if _valid_cached_file(target) and not force and time.time() - target.stat().st_mtime < ttl:
        info["status"] = "cached"; return info
    try:
        from external_response_logger import persist_requests_response, persist_external_response
        from http_retry import retry_get
        r = retry_get(url, service="hydro_static_download", timeout=60, max_retries=1, abort_on_4xx=True, breaker_service="hydro_static_download")
        persist_requests_response("hydro", "GET", r, fallback=False)
        target.write_bytes(r.content)
        if not _valid_cached_file(target):
            raise RuntimeError("Download ist leer oder kein gültiges ZIP")
        info.update(status="downloaded", size_bytes=target.stat().st_size)
    except Exception as exc:
        try:
            from external_response_logger import persist_external_response
            persist_external_response("hydro", url=url, method="GET", status_code=getattr(getattr(exc,"response",None),"status_code",None), fallback=True, error=f"{type(exc).__name__}: {exc}")
        except Exception: pass
        info.update(status="failed", error=f"{type(exc).__name__}: {exc}")
    return info


def download_basins(static_dir: str | None=None, force: bool=False) -> dict: return _download(_config_url("HYDRO_DRAINAGEBASIN_GDB_URL", "HYDRO_STATIC_BASINS_URL"), ensure_static_dirs(static_dir), "basins", force)
def download_flowlines(static_dir: str | None=None, force: bool=False) -> dict:
    paths=ensure_static_dirs(static_dir); attempts=[]
    for idx, url in enumerate(_download_urls_for("flowlines")):
        info=_download(url, paths, "flowlines" if idx == 0 else "watercourse", force)
        attempts.append(dict(info))
        if info.get("status") != "failed":
            info["attempts"] = attempts
            return _refresh_download_size(info)
    return _refresh_download_size(attempts[-1] if attempts else {"url":"", "path":"", "status":"failed", "size_bytes":0, "error":"missing_url"})

def _ogr_layers(src: str) -> list[str]:
    try:
        out = subprocess.run(["ogrinfo", src], text=True, capture_output=True, check=False, timeout=60).stdout
        layers=[]
        for line in out.splitlines():
            line=line.strip()
            lower=line.lower()
            if lower.startswith("layer:") or lower.startswith("layer name:"):
                layers.append(line.split(":",1)[1].split("(",1)[0].strip())
            elif line[:1].isdigit() and ":" in line:
                layers.append(line.split(":",1)[1].split("(",1)[0].strip())
        return [l for l in layers if l]
    except Exception: return []



def _ogr_layer_geometry(src: str, layer: str) -> str:
    try:
        out = subprocess.run(["ogrinfo", "-so", src, layer], text=True, capture_output=True, check=False, timeout=60).stdout
        for line in out.splitlines():
            lower=line.lower()
            if "geometry:" in lower or "geometry type:" in lower:
                return line.split(":", 1)[1].strip()
            if "multi polygon" in lower or "multipolygon" in lower: return "Multi Polygon"
            if "line string" in lower or "linestring" in lower: return "Line String"
            if "polygon" in lower: return "Polygon"
    except Exception:
        pass
    return ""


def _layer_matches_kind(geom: str, kind: str) -> bool:
    g=geom.lower().replace(" ", "")
    if not g: return True
    return ("polygon" in g and kind == "basins") or ("linestring" in g and kind == "flowlines")


def _ogr_bbox_feature_count(dataset: str, layer: str, bbox: list[float] | None) -> int:
    if not bbox: return -1
    cmd=["ogrinfo", "-so", "-spat_srs", "EPSG:4326", "-spat", *map(str, bbox), dataset, layer]
    try:
        out=subprocess.run(cmd, text=True, capture_output=True, check=False, timeout=60).stdout
        for line in out.splitlines():
            if "feature count:" in line.lower():
                return int(line.split(":",1)[1].strip())
    except Exception:
        pass
    return -1


def _select_ogr_layer(dataset: str, kind: str, layers: list[str], bbox: list[float] | None=None) -> str | None:
    prefs = ["drainagebasin", "catchment"] if kind == "basins" else ["watercourselink", "watercourse", "flowline"]
    typed=[l for l in layers if _layer_matches_kind(_ogr_layer_geometry(dataset, l), kind)]
    candidates = sorted(typed, key=lambda l: 0 if any(p in l.lower() for p in prefs) else 1)
    if kind == "flowlines" and candidates:
        scored=[(_ogr_bbox_feature_count(dataset, l, bbox), 0 if any(p in l.lower() for p in prefs) else 1, l) for l in candidates]
        scored.sort(key=lambda x: (-x[0], x[1]))
        return scored[0][2] if scored[0][0] != 0 else None
    return candidates[0] if candidates else None

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
    spat = _normalize_bbox(bbox) or _normalize_bbox(getattr(config,"HYDRO_STATIC_BBOX", None)) or KAERNTEN_BBOX
    layer = _select_ogr_layer(dataset, kind, layers, spat)
    if layers and not layer:
        raise RuntimeError(f"Keine passende OGR-Layer für {kind} gefunden")
    dst_path=Path(dst); dst_path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp_name = tempfile.mkstemp(prefix=f".{dst_path.name}.", suffix=".tmp.geojson", dir=str(dst_path.parent))
    os.close(fd)
    tmp_path=Path(tmp_name)
    try:
        cmd=["ogr2ogr","-f","GeoJSON","-t_srs","EPSG:4326",str(tmp_path),dataset]
        if spat: cmd += ["-spat_srs", "EPSG:4326", "-spat", *map(str, spat)]
        if layer: cmd.append(layer)
        res=subprocess.run(cmd, text=True, capture_output=True, check=False, timeout=300)
        if res.returncode != 0: raise RuntimeError((res.stderr or res.stdout or "ogr2ogr fehlgeschlagen").strip())
        if (not tmp_path.exists() or tmp_path.stat().st_size == 0) and dst_path.exists():
            shutil.move(str(dst_path), str(tmp_path))
        validate_geojson_output(str(tmp_path), kind, spat)
        if kind == "basins": normalize_basin_properties(str(tmp_path))
        os.replace(tmp_path, dst_path)
        return True
    except Exception:
        try:
            if tmp_path.exists(): tmp_path.unlink()
        finally:
            pass
        raise


def ensure_live_json(static_dir: str | None=None) -> str:
    from hydro_fetch import LATEST_FILE, fetch_hydro_live
    if not LATEST_FILE.exists() or LATEST_FILE.stat().st_size == 0: fetch_hydro_live(force=True)
    return str(LATEST_FILE)


def build_static_hydro(static_dir: str | None = None, downloads: dict | None=None) -> dict:
    paths=ensure_static_dirs(static_dir); missing=[n for n in ("stations_source","basins_source") if not Path(paths[n]).exists()]
    if missing: return write_status("hydro_static_missing", "Statische Hydro-Eingangsdaten fehlen; Hydro-Impact ist noch nicht aktiv.", static_dir, missing=missing, downloads=downloads or _default_downloads(paths))
    status=build_station_index(paths["stations_source"], paths["basins_source"], paths["flowlines_source"] if _geojson_valid(paths["flowlines_source"], "flowlines") else None, paths["generated"])
    status["downloads"] = downloads or _default_downloads(paths); status.setdefault("required_files", {"stations_source":paths["stations_source"],"basins_source":paths["basins_source"],"flowlines_source":paths["flowlines_source"]}); status.setdefault("errors", []); status.setdefault("warnings", []); status.setdefault("missing", [])
    Path(paths["status"]).write_text(json.dumps(status, indent=2, ensure_ascii=False)+"\n", encoding="utf-8")
    return status


def auto(static_dir: str | None=None, force: bool=False) -> dict:
    paths=ensure_static_dirs(static_dir); downloads=_default_downloads(paths); errors=[]; warnings=[]
    try: import_station_json(ensure_live_json(static_dir), static_dir)
    except Exception as exc: errors.append(f"live_station_import: {type(exc).__name__}: {exc}")

    downloads["basins"] = download_basins(static_dir, force=force or not _geojson_valid(paths["basins_source"], "basins"))
    flowlines_ok = _geojson_valid(paths["flowlines_source"], "flowlines")
    downloads["flowlines"]["status"] = "cached" if flowlines_ok and not force else "pending"
    if not flowlines_ok or force:
        downloads["flowlines"] = download_flowlines(static_dir, force=force or not flowlines_ok)

    try:
        if downloads["basins"].get("status") != "failed":
            if force or not _geojson_valid(paths["basins_source"], "basins"):
                convert_to_geojson(downloads["basins"]["path"], paths["basins_source"], "basins")
            validate_geojson_output(paths["basins_source"], "basins")
        else: errors.append(downloads["basins"].get("error","basins download failed"))
    except Exception as exc: errors.append(f"basins_convert: {type(exc).__name__}: {exc}")

    flow_convert_errors=[]
    if downloads["flowlines"].get("status") == "failed":
        warnings.append(downloads["flowlines"].get("error","flowlines download failed"))
    else:
        attempts = downloads["flowlines"].get("attempts") or [downloads["flowlines"]]
        for info in attempts:
            try:
                if force or not _geojson_valid(paths["flowlines_source"], "flowlines"):
                    convert_to_geojson(info["path"], paths["flowlines_source"], "flowlines")
                validate_geojson_output(paths["flowlines_source"], "flowlines")
                downloads["flowlines"] = _refresh_download_size(info)
                break
            except Exception as exc:
                flow_convert_errors.append(f"{Path(str(info.get('path',''))).name}: {type(exc).__name__}: {exc}")
                # convert_to_geojson() ist atomar; eine bestehende valide Datei darf bei Fehlern erhalten bleiben.
        else:
            if not any(a.get("url") == getattr(config, "HYDRO_STATIC_WATERCOURSE_URL", "") for a in attempts):
                fallback = _download(getattr(config, "HYDRO_STATIC_WATERCOURSE_URL", ""), paths, "watercourse", force)
                downloads["watercourse"] = fallback
                if fallback.get("status") != "failed":
                    try:
                        convert_to_geojson(fallback["path"], paths["flowlines_source"], "flowlines")
                        validate_geojson_output(paths["flowlines_source"], "flowlines")
                        downloads["flowlines"] = _refresh_download_size(fallback)
                        flow_convert_errors=[]
                    except Exception as exc:
                        flow_convert_errors.append(f"{Path(str(fallback.get('path',''))).name}: {type(exc).__name__}: {exc}")
            if flow_convert_errors:
                downloads["flowlines"]["status"] = "failed"
                downloads["flowlines"]["error"] = "; ".join(flow_convert_errors)
                warnings.append("flowlines_convert: " + downloads["flowlines"]["error"])

    if any(d.get("status")=="failed" for d in downloads.values() if isinstance(d,dict)) and not errors:
        # Basin-only remains installable, but it must be explicit and never look skipped/successful.
        warnings.append("flowlines_missing")
    if errors:
        return write_status("hydro_static_convert_failed", "Hydro-Static-Konvertierung fehlgeschlagen; Installation läuft weiter.", static_dir, downloads=downloads, errors=errors, warnings=warnings)
    status=build_static_hydro(static_dir, downloads)
    status.setdefault("warnings", []).extend(w for w in warnings if w not in status.get("warnings", []))
    try:
        status["feldkirchen_coverage"] = check_coverage("feldkirchen", static_dir)
    except Exception as exc:
        status.setdefault("warnings", []).append(f"feldkirchen_coverage: {type(exc).__name__}: {exc}")
    if status.get("flowline_count", 0) <= 0 and status.get("basin_count", 0) > 0:
        status["status"] = "flowlines_missing"
        if "flowlines_missing" not in status.setdefault("warnings", []): status["warnings"].append("flowlines_missing")
    elif status.get("status") not in {"ok","hydro_ready","upstream_topology_missing","station_basin_available","station_basin_unavailable","flowlines_missing"}: status["status"]="hydro_static_partial"
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
    p.add_argument("--static-dir", default=None); p.add_argument("--force", action="store_true"); p.add_argument("--status", action="store_true"); p.add_argument("--check-coverage"); p.add_argument("--auto", action="store_true"); p.add_argument("--download-all", action="store_true"); p.add_argument("--download-basins", action="store_true"); p.add_argument("--download-flowlines", action="store_true"); p.add_argument("--build", action="store_true"); p.add_argument("--verify", action="store_true"); p.add_argument("--import-stations"); p.add_argument("--allow-url-import", action="store_true")
    a=p.parse_args(); out=None
    if a.status: out=status(a.static_dir)
    elif a.check_coverage: out=check_coverage(a.check_coverage, a.static_dir)
    elif a.auto: out=auto(a.static_dir, force=a.force)
    elif a.download_all: paths=ensure_static_dirs(a.static_dir); out={"downloads":{"basins":download_basins(a.static_dir, force=a.force),"flowlines":download_flowlines(a.static_dir, force=a.force)}}
    elif a.download_basins: out=download_basins(a.static_dir, force=a.force)
    elif a.download_flowlines: out=download_flowlines(a.static_dir, force=a.force)
    elif a.import_stations: out={"path": import_station_json(a.import_stations, a.static_dir, allow_url_import=a.allow_url_import)}
    elif a.build: out=build_static_hydro(a.static_dir)
    elif a.verify: out=verify(a.static_dir)
    else: out=build_static_hydro(a.static_dir)
    print(json.dumps(out, indent=2, ensure_ascii=False)); return 0
if __name__ == "__main__": raise SystemExit(_main())
