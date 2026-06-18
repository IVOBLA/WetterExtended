# 1C — IR-Vorläufer-Semantik

Eine **IR-Vorläuferzelle** ist in WetterExtended eine potenzielle neue konvektive Zelle, die aus der bestehenden IR108-CB-Detektion stammt und noch nicht durch ein Radarobjekt bestätigt wurde. 1C vereinheitlicht ausschließlich die Semantik und das Payload-Modell dieser bestehenden IR-Tracks; es erzeugt keinen neuen Kartenlayer, keine parallele Objektklasse und keine zusätzliche Markierung aktiver Radarzellen.

## Abgrenzung zu 1L

1C vergibt bewusst noch keine globale `cell_id`. Diese stabile Zell-Lineage-ID folgt erst mit 1L.1. Die 1C-Felder sind dafür vorbereitet, damit 1L später auf eindeutige Zustands-, Wachstums- und Deduplizierungsinformationen aufbauen kann.

## Anzeige- und Deduplizierungsregel

Radar-gematchte IR-Tracks bleiben im Payload erlaubt, werden aber nicht separat als IR-Vorläufer angezeigt. Die Karte zeigt IR-Vorläufer nur dann über den bestehenden CB-/IR-Mechanismus an, wenn der Track nicht radarbestätigt ist, `ir_only_precursor == 1.0` gilt und `display_as_precursor` nicht `false` ist.

## Semantikfelder

- `_type`: Einheitlicher Payload-Typ für IR-Tracks. Für 1C ist der Wert `ir_precursor_cell`.
- `status`: Fachlicher Zustand des IR-Tracks. `ir_precursor` bedeutet potenzielle neue Zelle; `radar_confirmed` bedeutet, dass der IR-Track einem Radarobjekt zugeordnet wurde.
- `radar_confirmed`: Boolescher Deduplizierungsanker. `true` verhindert die separate IR-Vorläuferdarstellung.
- `is_potential_new_cell`: `true` nur für nicht radarbestätigte IR-Vorläufer.
- `display_as_precursor`: Explizite Frontend-Regel. `false` bei radarbestätigten Tracks.
- `ir_only_precursor`: Rückwärtskompatibler numerischer Schalter. `1.0` steht für reinen IR-Vorläufer, `0.0` für radarbestätigt oder nicht separat anzuzeigen.
- `area_growth_km2_per_min`: Flächenwachstum auf Basis der bestehenden Näherung `area_px * 9.0`.
- `cloud_height_trend_m_per_min`: Trend der Wolkenobergrenze in Metern pro Minute.

## CB-only-Regel

CB-only bleibt verbindlich: Nur IR-Cluster aus der bestehenden konvektiven IR-Detektion gelten als IR-Vorläufer. Cirren, Anvil-Reste und Frontbewölkung sollen nicht als neue Zellen gezählt werden. Deshalb tragen IR-Vorläufer `cb_candidate = true` und `cb_only_reason = "ir108_cold_top_and_met_filter"`.
