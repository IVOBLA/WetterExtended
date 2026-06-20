# WetterExtended — Berechnungs- und Verfahrensdokumentation (`logic.md`)

Referenz gemäß `zieldefinition.txt`. Pro Verfahren: Kurzbeschreibung, **Code-Stelle**,
**Quelle** (Originalpublikation/Doku) und **operationelle Verwendung** (etablierte
Organisation). Vollständige Linkliste in Abschnitt 13.

## 1. Koordinaten- und Einheiten-Invarianten

- **UPSCALE_FACTOR** (config.py): definiert das Koordinatensystem ALLER JSON-Daten;
  niemals zur Laufzeit überschreibbar.
- `vx/vy` = ORIGINAL-px/Frame; Konturen/Radarbilder = skalierte px.
- Geschwindigkeits-Invariante (config.py `speed_kmh_from_px`):
  `PX_TO_KMH == (1/UPSCALE_FACTOR)/(FRAME_INTERVAL_MIN/60)` → 4.0 km/h pro px/Frame.
- Zeitbasis stets aus echten Frame-Timestamps (`_actual_frame_min`), nominaler
  Fallback `FRAME_INTERVAL_MIN=5` (B115).

## 2. Zellerkennung (object_tracking.py)

- HSV-Farbsegmentierung + Konturextraktion (OpenCV); `area`, `eccentricity`,
  `core_ratio` (Kern-Anteil).
- **Verfahren/Quelle:** Schwellwert-/größenbasierte Sturmdefinition wie in **TITAN**
  (Dixon & Wiener 1993) und adaptive Schwellwertdetektion wie in **TRT** (Hering et
  al. 2004).
- **Operationell:** NCAR (TITAN), MeteoSwiss (TRT).

## 3. Kalman-Filter (object_tracking.py)

- Zustand `[x,y,vx,vy]`, Messung `[x,y]`; `predict()`/`update()`; Geschwindigkeits-
  Clamp (`MAX_CELL_SPEED_KMH`, `MAX_SPEED_CHANGE_PER_CYCLE_KMH`).
- **Quelle:** Kalman (1960); Implementierung **filterpy** (R. Labbe).
- **Verwendung:** Standardverfahren der Zustands-/Objektverfolgung (Luft-/Raumfahrt,
  Radar-Tracking, u. a. NWS/NSSL-Trackingsysteme).

## 4. Tracking / Zuordnung, Merge & Split (object_tracking.py)

- Mehrstufiges Matching über geografische Konturüberlappung; Lineage
  `new|continued|merged|split`.
- **Merge (B117):** vereinigte Zelle erbt die ID des dominanten Parents (größte
  alte Fläche) inkl. Kalman/History; `merge_discontinuity=1` markiert den Frame.
- **Quelle/Verwendung:** geografische-Überlappungs- und Centroid-Verfahren mit
  expliziter Merge/Split-Behandlung wie in **TRT** (MeteoSwiss, operationell seit
  2003) und **TITAN/ETITAN** (NCAR; Han et al. 2009).

## 5. Bewegungsfeld / Optischer Fluss (optical_flow_features.py)

- Dichtes **Lucas-Kanade**-Feld via **pysteps** `dense_lucaskanade` zwischen zwei
  Radarbildern.
- **P-M01:** `of_vx/of_vy` = Flächenmittel des Feldes über das Zellpolygon (nur
  gültige Pixel); `of_available=0` wenn kein gültiger Vektor; `of_divergence` =
  mittlere Felddivergenz (Konvergenz = negativ = Intensivierungsindikator).
- **Quelle:** Lucas & Kanade (1981); pysteps (Pulkkinen et al. 2019, GMD).
- **Operationell:** pysteps wird von **MeteoSwiss** und **FMI** (Finnland) sowie in
  der internationalen Nowcasting-Community eingesetzt.

## 6. Bewegungsvorhersage (prediction.py)

- ML-primär (sofern Modelle), sonst kinematischer Fallback (`_append_kinematic`).
- **Geschwindigkeitsquelle, Priorität:**
  1. **P-M02 — optischer Fluss** (`of_available=1`): Forecast-v = `of_vx/of_vy /
     frame_min`. Entspricht der **TRT-„gewichteten Zellverschiebungs-
     Geschwindigkeit"** (Hering et al. 2004) bzw. der **ETITAN**-Kombination aus
     Kreuzkorrelations-/Bewegungsfeld und Centroid (Han et al. 2009) — feldbasiert,
     robust gegen Merge-Schwerpunktsprünge.
  2. EWMA über History-`vx/vy` (α=`KINEMATIC_EWMA_ALPHA`).
  3. Kalman (`kalman_only`) für sehr junge Zellen.
- **B166 — Merge/Split-Glättung:** Bei `merge_discontinuity`/`is_merged`/`is_split` wird der
  jüngste (diskontinuierliche) History-Eintrag aus der kinematischen v-Mittelung ausgeschlossen
  (nur wenn danach ≥ 2 Frames bleiben), damit der Schwerpunktsprung die Vor-Merge-Bewegung nicht
  verfälscht (`kinematic_source` erhält `+mguard`). Der optische Fluss bleibt unbeeinflusst.
- Geo-only-Fallback (B117); Train=Inference via Kinematic-First-`path_*` (B108).
- **Operationell:** feldbasierte Extrapolation ist Kern operationeller Systeme
  (MeteoSwiss TRT; pysteps-Advektions-/LINDA-Nowcasts).

## 7. Tendenz: Intensität & Größe (object_tracking.py, prediction.py)

- `trend` (core_ratio) und `size_trend` (relative Flächenänderung).
- **P-M03 (merge-bewusst):** Vergleich gegen flächengewichtetes Parent-Kernmittel
  (`_merge_prev_core`) bzw. Summe der Parent-Flächen (`_merge_prev_area`).
- `_classify_tendency`: mit ML aus `delta_core_ratio_pred`/`delta_area_pred`; sonst
  kinematisch; **of_divergence**-Tie-Breaker bei neutraler Tendenz.
- **Quelle/Verwendung:** Lebenszyklus-/Attributzeitreihen je Zelle wie in TITAN/TRT;
  Intensitätsänderung als Nowcasting-Größe (vgl. COALITION-3, MeteoSwiss).

## 8. Orts-Treffer (locations_check.py)

Polygon-basiert; vier Treffertypen (Priorität current > slow > forecast/growth):

1. **current** — aktuelles Polygon ≤ Radius (Horizont 0).
2. **slow_approach** — `min_speed ≤ speed ≤ slow_max`; wachstums-projiziertes
   Polygon vs. Radius × `slow_radius_factor`.
3. **forecast** — `speed > slow_max`; Forecast-Polygon vs. Radius.
4. **P-M05 growth_approach** — stationäre, wachsende Zelle: wachstums-projiziertes
   Polygon (Zentrum ortsfest) vs. Radius → Vorwarnung bei reiner Flächenausdehnung.
- Wachstumsprojektion `_forecast_polygon_at_h` (richtungsabhängige Skalierung mit
  `_directional_growth_rates`, gedeckelt ±0.3 km/min).
- **Survival/Decay (P-T06):** exponentieller Zerfall (`CELL_DECAY_HALF_LIFE_MIN`),
  Unterdrückung unter `CELL_SURVIVAL_MIN_FRAC`; **Stale (P-T09):** `radar_age_min ≥
  horizon`.
- **Quelle/Verwendung:** richtungsabhängiges Wachstum/Extrapolation der Zellkontur
  ist TRT-Konzept (Hering et al. 2004, „extrapolating cells contours"); orografische
  Triggerung bei stationären Alpenzellen ebenfalls TRT-Motiv. `growth_approach` ist
  eine projekteigene Erweiterung auf Basis dieser Konzepte.

## 9. Warnlogik (main.py, email_notifier.py, whatsapp_notifier.py)

- Warnung wenn frühester Treffer-Horizont ≤ `WARN_MAX_HORIZON_MIN` oder current;
  Pipeline hit_type-agnostisch. Kinematik: 2-Frame-Bestätigung.
- WhatsApp sendet ausschließlich Warnungen (Design B108); E-Mail auch Entwarnung.

## 10. ML-Pipeline (dataset_builder.py, intensity_regression.py, model_training.py)

- Positions-Modelle: LightGBM je Horizont, optional **LSTM/ConvLSTM**; Feature-Count-
  Gate (B123/B116).
- Intensitäts-/Größen-Regressoren: `delta_core_ratio`, `delta_area_pct`.
- **P-M04 (Label-Masking):** Samples mit `merge_discontinuity=1` (Jetzt-/Ziel-Frame)
  vom Δ-Label- und `intensified`-Training ausgeschlossen.
- **Quelle/Verwendung:** **LightGBM** (Ke et al. 2017, Microsoft); **ConvLSTM** (Shi
  et al. 2015, Hong Kong Observatory); generative Radar-Nowcasts **DGMR** (Ravuri et
  al. 2021, DeepMind & UK Met Office); XGBoost-Schweregrad **COALITION-3**
  (MeteoSwiss).

## 11. Phase B — Hailo (HAILO_INTEGRATION.md)

- Geplant: U-Net/ConvLSTM-Radar-Nowcasting auf Hailo-8; optischer Fluss als
  Zusatzeingang. Details/Status: `docs/HAILO_INTEGRATION.md`.

## 12. Externe Datenquellen — Intervalle & Request-Sparsamkeit

- ARSO INCA (5 min), Open-Meteo icon_d2/global, GeoSphere AROME/TAWES/Nowcast,
  EUMETView MSG IR108 (15 min), Blitzortung (1 min). Cache-TTL je Quelle
  (`API_CACHE_TTL_SECONDS`); Retry/Circuit-Breaker (`http_retry.py`).

## 13. Quellen & operationelle Verwendung (Linkliste)

- **Kalman-Filter:** Kalman, R. E. (1960), *A New Approach to Linear Filtering and
  Prediction Problems*, doi:10.1115/1.3662552. Implementierung: filterpy —
  https://github.com/rlabbe/filterpy ·
  https://github.com/rlabbe/Kalman-and-Bayesian-Filters-in-Python
- **TITAN:** Dixon & Wiener (1993), *J. Atmos. Oceanic Technol.* 10(6):785–797 —
  https://journals.ametsoc.org/view/journals/atot/10/6/1520-0426_1993_010_0785_ttitaa_2_0_co_2.xml
  · NCAR: https://impacts.ucar.edu/en/publications/titan-thunderstorm-identification-tracking-analysis-and-nowcastin/
- **ETITAN:** Han et al. (2009), *Enhanced TITAN*, *J. Atmos. Oceanic Technol.*
  26(4):719–732, doi:10.1175/2008JTECHA1153.1 — https://doi.org/10.1175/2008JTECHA1153.1
- **TRT (Thunderstorms Radar Tracking):** MeteoSwiss (operationell seit 2003) —
  https://www.meteoswiss.admin.ch/about-us/research-and-cooperation/projects/en/2002/trt.html
  · Hering et al. (2004), ERAD, *Nowcasting thunderstorms in the Alpine region using
  a radar based adaptive thresholding scheme*.
- **pysteps:** Pulkkinen et al. (2019), *Geosci. Model Dev.* 12(10):4185–4219,
  doi:10.5194/gmd-12-4185-2019 — https://gmd.copernicus.org/articles/12/4185/2019/ ·
  Doku: https://pysteps.readthedocs.io/ (eingesetzt u. a. von MeteoSwiss, FMI).
- **T-DaTing (pysteps-Zelltracking, an TRT angelehnt):** Feldmann et al. (2021), in
  pysteps implementiert — https://pysteps.readthedocs.io/
- **Lucas-Kanade (optischer Fluss):** Lucas & Kanade (1981), Proc. IJCAI, *An
  Iterative Image Registration Technique*; in pysteps als `dense_lucaskanade`.
- **ConvLSTM:** Shi et al. (2015), NeurIPS, arXiv:1506.04214 —
  https://arxiv.org/abs/1506.04214 (entwickelt mit dem Hong Kong Observatory).
- **DGMR (Deep Generative Models of Rainfall):** Ravuri et al. (2021), *Nature*
  597:672–677, doi:10.1038/s41586-021-03854-z (DeepMind & UK Met Office).
- **LightGBM:** Ke et al. (2017), NeurIPS (Microsoft) —
  https://github.com/microsoft/LightGBM
- **COALITION-3 (XGBoost-Gewitterschwere):** MeteoSwiss-Forschung, TRT-Rang-Nowcast.

> Hinweis: Survival/Decay (P-T06), Stale-Kennzeichnung (P-T09) und
> `growth_approach` (P-M05) sind projekteigene Erweiterungen, methodisch angelehnt an
> die TRT-Lebenszyklus-/Extrapolationskonzepte (Hering et al. 2004).

## Hydro-Impact-Logik

Pegel-Attribution erfolgt **nicht radiusbasiert**. Der „nächste Pegel“ ist fachlich falsch, weil räumliche Nähe keine hydrologische Verbindung beweist: Niederschlag kann neben dem relevanten Gewässer, in einem anderen Teileinzugsgebiet oder unterhalb der Messstelle liegen. Eine Zelle wird deshalb nur berücksichtigt, wenn ihr Polygon das **oberliegende Einzugsgebiet** einer Station schneidet und anschließend ein plausibler hydrologischer **Zeitversatz** angewendet wird. Ergebnisse heißen stets **plausibler Zusammenhang**; sie sind keine Kausalitätsbehauptung, **keine amtliche Hochwasserwarnung** und kein Ersatz für geprüfte amtliche Endwerte. Live-Hydro-Rohdaten sind Live-Indikatoren und keine qualitätsgesicherten amtlichen Endwerte.

### Hydro-Impact Produktionsregeln

Produktive Hydro-Impacts werden ausschließlich für Stationen erzeugt, deren statischer Index `impact_eligible=true` meldet. Dieses Flag darf nur gesetzt werden, wenn lokale Upstream-Topologie (`upstream_catchment_ids`) vorhanden ist und daraus ein geometrisch vereinigtes oberliegendes Einzugsgebiet (`station_catchment`) erzeugt wurde. `impact_eligible=false` bedeutet, dass WetterExtended für diese Station keinen belastbaren automatischen Hydro-Impact ableiten darf; die Station kann weiterhin angezeigt oder diagnostisch ausgewertet werden.

`station_basin` allein genügt nicht, weil es nicht zwingend das gesamte oberliegende Einzugsgebiet beschreibt und ohne vollständige Upstream-Kette eine hydrologisch falsche Zuordnung begünstigen kann. Flowline-Snapping ist nur Diagnosemetadatum: Es zeigt geometrische Nähe zu einer Gewässerlinie, beweist aber keine Lage oberhalb der Station, keine vollständige Fließverbindung und keine passende Reisezeit.

Zellpolygon und oberliegendes Einzugsgebiet müssen sich schneiden; zusätzlich werden Mindestfläche, Zellanteil, Dauer, relevante Intensität, Zeitversatz und Verifikationsschwellen ausgewertet. Fehlen lokale statische Daten, Upstream-Topologie oder Shapely/GEOS, bleibt das System lauffähig und setzt Gründe wie `hydro_static_missing` oder `hydro_geometry_unavailable`, erzeugt aber keinen produktiven Hydro-Impact. Ein Bounding-Box-Fallback darf nur Diagnosezwecken dienen.

### Konservative Entscheidung bei fehlender Upstream-Topologie

Wenn die Upstream-Topologie fehlt, kann das System nicht sicher unterscheiden, ob Niederschlag oberhalb, neben oder unterhalb der Messstelle gefallen ist. Ein Impact würde dann Genauigkeit vortäuschen, die die statischen Daten nicht hergeben. WetterExtended erzeugt deshalb konservativ lieber keinen Hydro-Impact als eine scheinbar präzise, aber nicht abgesicherte Pegel-Attribution.

### Persistente Hydro-Verifikation

`pending` bedeutet, dass das Zeitfenster noch läuft oder die Verifikation aussteht. `confirmed` bedeutet nur, dass eine Pegel-/Abflussänderung plausibel ins Zeitfenster und zu den Schwellen passt; es ist kein Kausalitätsbeweis. `rejected` bedeutet, dass aus den verfügbaren Rohdaten kein belastbarer Zusammenhang ableitbar ist. `ambiguous` bedeutet eine uneindeutige Lage, etwa wegen Messlücken, konkurrierender Zellen im selben oberliegenden Einzugsgebiet, unklarer Reaktion oder unzureichender Datenqualität.

Historische Hydro-Impact-JSONL-Dateien bleiben unverändert als Audit-Log erhalten. Der aktuelle Verifikationszustand wird über `hydro_impact_state.json` überlagert, sodass alte bestätigte, abgelehnte oder mehrdeutige Events nicht erneut als pending geladen werden. Pending-Events werden aus allen Hydro-JSONL-Dateien geladen; `latest_hydro_impacts.json` ist nur Anzeige-/Cache-Datei. Messlücken größer als `HYDRO_VERIFY_MAX_GAP_MIN` führen zu `ambiguous`; konkurrierende Zellen im selben oberliegenden Einzugsgebiet erhalten den Reason `competing_cells_same_catchment` und werden nicht hart einer Einzelzelle zugeschrieben.

### Hydro-Konfiguration

Konfigurierbar sind `HYDRO_ENABLED`, `HYDRO_API_TTL_SECONDS`, `HYDRO_MIN_OVERLAP_AREA_KM2`, `HYDRO_MIN_OVERLAP_RATIO_CELL`, `HYDRO_MIN_DURATION_MIN`, `HYDRO_RELEVANT_INTENSITIES`, `HYDRO_DEFAULT_LAG_MIN`, `HYDRO_LAG_WINDOW_MIN`, `HYDRO_VERIFY_MIN_DELTA_Q_M3S`, `HYDRO_VERIFY_MIN_DELTA_W_CM`, `HYDRO_VERIFY_MIN_RELATIVE_DELTA_PCT`, `HYDRO_VERIFY_MAX_GAP_MIN` und `HYDRO_STATION_OVERRIDES`. Runtime-Overrides ersetzen nicht die fachliche Anforderung an `impact_eligible=true`.
