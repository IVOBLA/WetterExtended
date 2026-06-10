# Debug-Analyse `wetterextended_debug_latest_last24h.zip` vs. `main`

- **Analysezeitraum:** 2026-06-09 09:30 UTC → 2026-06-10 09:30 UTC (24 h)
- **Quelle:** Branch `debug-export-latest`, Export von Commit `aa74709` (= `main` HEAD)
- **Host:** KI-PI · Python 3.11.2 · 2.511 Dateien / 140 MB
- **Tests im Export:** `install_pytest.log` → **165 passed** ✅

---

## 1. Zusammenfassung

Das System läuft im Analysezeitraum grundsätzlich stabil (ruhiges Wetter, 0 detektierte
Zellen). Die Kerndienste (Radar-Download, TAWES, CAPE, Cloud-Height-TIFF, Blitz, FTP-Upload)
arbeiten fehlerfrei. Es wurden **vier Auffälligkeiten** identifiziert, davon eine bereits
am 2026-06-10 06:52 UTC behoben:

| # | Befund | Schwere | Status |
|---|--------|---------|--------|
| F1 | GeoSphere Nowcast: 122 × HTTP 400 (88 % aller Nowcast-Calls) | Hoch | 96 % behoben (B116/`ffx`), Reststelle offen |
| F2 | EUMETView WMS GetCapabilities: leerer/abgeschnittener Body → `ParseError` | Mittel | offen, aber durch Fallback abgefangen |
| F3 | nginx 502 „connect() failed (111: Connection refused)" – 244 × | Niedrig | nur Restart-Fenster |
| F4 | nginx Rate-Limit (`zone wetter_api`, excess ~30) | Niedrig | offen, kosmetisch |
| F5 | GeoSphere-400-**Response-Body wird nicht persistiert** (`response_body=null`) | Mittel (Diagnose) | offen |

---

## 2. Fehleranalyse im Detail

### F1 — GeoSphere Nowcast: 122 × HTTP 400 von 139 Calls

**Statusverteilung `geosphere_nowcast`:** 17 × 200, **122 × 400**.

Zwei Ursachen identifiziert:

1. **`ffx`-Parameter (96 % der Fehler).** 117 der 122 400er enthalten `parameters=ffx`.
   Der Datensatz `nowcast-v1-15min-1km` kennt `ffx` nicht (GeoSphere antwortet
   „Parameters {'ffx'} do not exist"). **Bereits behoben** in Commit `95a37f7`
   („Fix GeoSphere nowcast ffx parameter", 2026-06-10 06:52 UTC, B116) — `_PARAMS = "rr,ff"`.
   Regressionstest `test_b116_gust_kmh_ignores_nowcast_ffx_field` ist grün.

2. **Reststelle nach dem Fix (5 × 400).** Alle fünf Post-Fix-400er betreffen **exakt eine
   Koordinate: `47.128, 15.055`** (Oststeiermark). Sie liegt **innerhalb** der konfigurierten
   Bbox-Schranke (`45.6–49.38 °N, 8.2–17.64 °E` in `fetch_geosphere_nowcast.py`), wird vom
   GeoSphere-Nowcast-Raster aber konsistent abgelehnt (8/8 Calls = 400). Benachbarte
   Fixpunkte (`47.147,14.632` → 14×200, `47.121,14.352` → 9×200) funktionieren einwandfrei.
   Die Bbox-Schranke ist also **zu grob**, um diese Zelle herauszufiltern.

**Wichtig:** Der eigentliche 400-Grund lässt sich aus dem Export **nicht** verifizieren,
weil `response_body=null` geloggt wird (siehe F5). Der String-Body wird zwar via
`debug_log("[NOWCAST] 400-Body: …")` ausgegeben, aber nicht in `external_responses/…json`
persistiert.

---

### F2 — EUMETView WMS GetCapabilities: `ParseError: unclosed token: line 1, column 0`

`api_health.jsonl` und `eumetview_debug.jsonl` zeigen:
- 8/8 `capabilities_response` mit `target_layer_found=false`
- 1 × `reason=exception-ParseError` („unclosed token: line 1, column 0")
- `http-200`, aber Layer `msg_fes:ir108` nicht gefunden

**Befund:** Der Parser-Code in `cloud_height_from_eumetview.py` ist **korrekt** — beim
Test gegen einen vollständig gespeicherten Capabilities-Body (248 KB, `…02-04-11…`) wird
der Layer gefunden und der Timestamp `2026-06-10T01:45:00Z` korrekt extrahiert.

Der Fehler tritt nur auf, wenn `r.ok==True`, der Body aber **leer oder abgeschnitten**
ankommt → `ET.fromstring(r.content)` wirft „unclosed token: line 1, column 0" (= leerer
Inhalt) bzw. findet den Layer nicht (= Teil-Body). Cloud-Height funktioniert trotzdem,
weil ein Fallback-Timestamp (auf 15-min-Raster gerundet) greift — d. h. degradiert auf
„geratenen" statt „bestätigt verfügbaren" Zeitstempel.

Zusatzrisiko: Der Body beginnt mit `<!DOCTYPE WMT_MS_Capabilities SYSTEM "https://…">`
(externe DTD-Referenz).

---

### F3 — nginx 502: `connect() failed (111: Connection refused) while connecting to upstream`

244 Treffer, **alle** im Fenster 2026-06-10 09–11 UTC (192/34/18) — also rund um den
Service-Neustart/Redeploy (ffx-Fix-Deploy 06:52, Scheduler-Restart 09:18). Das Flask-Backend
(`127.0.0.1:5000`) war während des Restarts kurz nicht erreichbar, nginx liefert 502 an das
Frontend. **Kein Dauer-Crash**, nur Restart-bedingt.

---

### F4 — nginx Rate-Limit `limiting requests … by zone "wetter_api"`

Einige Bursts mit `excess: ~30`. Das Frontend pollt `/api/objects` + `/api/logs` ~alle 25 s;
in Kombination mit `/api/health`, `/api/forecast`, `/api/risk_grid` etc. werden kurzzeitig
Limits gerissen. Kosmetisch, kein Funktionsverlust.

---

### F5 — Diagnose-Lücke: GeoSphere-400-Body wird nicht persistiert

In `fetch_geosphere_nowcast.py` (except-Zweig) wird bei Fehlern nur
`log_api_call(..., error=str(_exc))` aufgerufen — **ohne** `response_text`. Ergebnis:
`response_body=null` in allen `external_responses/geosphere_nowcast/*_400_*.json`. Dadurch
ist die exakte 400-Ursache (Parameter? Koordinate außerhalb Domäne? Forecast-Fenster?) aus
dem Export-ZIP nicht rekonstruierbar — man muss raten. Das gleiche gilt für `_parse_nowcast_single`.

---

## 3. Claude-Code-Prompts (copy-paste-fertig)

### Prompt A — Reststelle Nowcast 400 (Koordinate 47.128,15.055) + Auto-Blacklist

```
In fetch_geosphere_nowcast.py liefert die GeoSphere-Nowcast-API für einzelne Koordinaten
konsistent HTTP 400, obwohl sie innerhalb der konfigurierten Bbox (45.6–49.38°N, 8.2–17.64°E)
liegen — nachgewiesen für 47.128,15.055 (8/8 Calls = 400), während Nachbarpunkte 47.147,14.632
und 47.121,14.352 zuverlässig 200 liefern.

Implementiere eine selbstlernende Negativ-Liste für dauerhaft 400-liefernde Koordinaten:
1. Führe einen persistenten Cache (z.B. train_data/evaluation/nowcast_blacklist.json) mit
   gerundeten (lat,lon)-Schlüsseln und einem Fehlerzähler + last_seen-Timestamp.
2. Erhöhe den Zähler bei jedem 400 für eine Einzelkoordinate; ab N>=3 aufeinanderfolgenden
   400ern wird die Koordinate für T (z.B. 24h) übersprungen (kein API-Call, Default-Werte).
3. Bei einem späteren erfolgreichen 200 wird der Eintrag zurückgesetzt (Domäne kann sich ändern).
4. Schreibe Unit-Tests: (a) Koordinate wird nach 3×400 geblacklistet, (b) 200 setzt zurück,
   (c) geblacklistete Koordinate erzeugt keinen HTTP-Call.
Halte den bestehenden Bbox-Check als ersten, billigen Filter bei. Deutschsprachige
Kommentare/Log-Strings im Stil der Datei (Bxxx-Präfix).
```

### Prompt B — 400-Response-Body persistieren (Diagnose-Lücke F5)

```
In fetch_geosphere_nowcast.py werden 400-Antworten der GeoSphere-API ohne Response-Body
geloggt (response_body=null in external_responses/...json), wodurch die Fehlerursache aus
dem Debug-Export nicht rekonstruierbar ist.

Ändere den except-Zweig von assign_nowcast_to_objects und _parse_nowcast_single so, dass
log_api_call zusätzlich response_text=<gekürzter Body, max 400 Zeichen> und den
content-type des Fehler-Responses übergibt — analog zum Erfolgspfad. Nutze den bereits
ermittelten _err_resp.text. Stelle sicher, dass kein zweiter HTTP-Call entsteht und keine
Exception geworfen wird, wenn .text fehlt. Ergänze einen Test, der prüft, dass bei einem
gemockten 400 der Body im log_api_call-Aufruf landet.
```

### Prompt C — EUMETView GetCapabilities robust gegen leeren/abgeschnittenen Body (F2)

```
In cloud_height_from_eumetview.py wirft ET.fromstring(r.content) sporadisch
"ParseError: unclosed token: line 1, column 0", weil die WMS-GetCapabilities-Antwort trotz
HTTP 200 gelegentlich leer oder abgeschnitten ankommt; target_layer_found ist dann false.

Härte die Capabilities-Verarbeitung:
1. Vor ET.fromstring prüfen, ob r.content nicht leer ist und plausibel endet
   (enthält "</WMT_MS_Capabilities>" bzw. ">"); sonst als Soft-Fail behandeln.
2. Bei leerem/zu kurzem Body oder ParseError bis zu 2× via http_retry.retry_get neu laden,
   bevor auf den gerundeten Fallback-Timestamp zurückgefallen wird.
3. ParseError sauber fangen und in eumetview_debug.jsonl mit reason und body-Länge loggen
   (raw_extent_text_preview = erste 180 Zeichen).
4. Optional: ET-Parser mit deaktivierter externer DTD-Auflösung verwenden.
Der bestehende Fallback (gerundeter 15-min-Timestamp) bleibt als letzte Stufe erhalten.
Ergänze Tests: leerer Body -> Fallback ohne Exception; vollständiger Body -> Layer+Timestamp
korrekt (Fixture aus dem 248KB-Capabilities-Body).
```

### Prompt D — nginx 502 bei Service-Restart vermeiden (F3)

```
Beim Neustart von wetterprojekt-admin.service liefert nginx kurzzeitig 502
(connect() failed (111: Connection refused)). Mache Restarts für das Frontend transparent:
1. In der nginx-Konfiguration für den /api-Upstream proxy_next_upstream + retry/timeout
   so setzen, dass kurze Backend-Ausfälle abgefangen werden; optional eine kleine
   Warte-/Retry-Schleife.
2. systemd: Health-Gate ergänzen, sodass nginx erst nach erfolgreichem /api/health-Check
   des Backends Traffic durchlässt (ExecStartPost-Curl-Probe oder systemd-Ordering).
Dokumentiere die Änderung in docs/.
```

---

## 4. Verbesserungsvorschläge (über Fehlerbehebung hinaus)

1. **Nowcast-Domäne präzisieren statt Rechteck-Bbox.** Statt der groben Rechteck-Bbox eine
   genauere Maske des realen `nowcast-v1-15min-1km`-Rasters hinterlegen (z. B. Polygon der
   INCA-Austria-Domäne) — verhindert 400er an Randkoordinaten wie 47.128,15.055 *vor* dem Call.

2. **Bulk-Request-Robustheit.** Ein einziges ungültiges `lat_lon` lässt GeoSphere die ganze
   Bulk-Antwort mit 400 verwerfen. Bei Bulk-400 die Koordinaten halbieren und binär eingrenzen
   (oder Einzelabfragen) statt pauschalem Default für alle — so liefern die gültigen Punkte
   weiterhin Werte.

3. **`api_call_counts.jsonl` rotieren.** Die Datei ist bereits 2,5 MB. Log-Rotation/Aggregation
   einführen, damit sie nicht unbegrenzt wächst (und das Debug-ZIP aufbläht).

4. **Frontend-Polling entkoppeln.** `/api/objects` und `/api/logs` werden im 25-s-Takt parallel
   gepollt und reißen gelegentlich das nginx-Rate-Limit. ETag/Conditional-Requests oder
   moderat höheres `zone wetter_api`-Limit / Burst reduzieren die 503/limiting-Events.

5. **Health-Check-Sonde aus dem Nowcast nehmen.** Der API-Health-Check probt eine feste
   Koordinate gegen den Nowcast-Endpunkt — schlug hier wegen `ffx` mit 400 fehl und
   verfälschte den Health-Status. Health-Probe auf einen stabilen, parameterminimalen Call
   umstellen (`rr` an einer garantiert in-Domäne-Koordinate).

6. **„KML Datei fehlt für Georeferenzierung"** beim Erststart: harmlos (selbstheilend nach
   Radar-Download), aber als WARN statt DEBUG hochstufen wäre irreführend — als DEBUG belassen
   oder Erststart-Sonderfall stumm schalten.

---

## 5. Was gesund ist (kein Handlungsbedarf)

- `arso_radar` (203×200 / 172×304), `blitz` (176×200), `geosphere_tawes` (101×200),
  `geosphere_cape` (37×200), `open_meteo` (1480×200) — alle stabil.
- Cloud-Height-Pipeline: TIFF-Download, BT→Höhe-Umrechnung, IR-Cluster-Detektion laufen.
- FTP-Uploads (overlay.png, forecast.kmz, movement.gif, latest_objects.json) erfolgreich.
- Scheduler, CPU-Monitor, Admin-Panel, Debug-Export-Branch-Push: fehlerfrei.
- Test-Suite: 165 passed.
