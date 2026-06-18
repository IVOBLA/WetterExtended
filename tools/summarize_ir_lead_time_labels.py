#!/usr/bin/env python3
"""Kleine Offline-Zusammenfassung fuer 1L.4 IR-Lead-Time-Labels."""
from __future__ import annotations

import json
from collections import Counter
from pathlib import Path
from statistics import median

PATH = Path("train_data/cell_lineage/ir_lead_time_labels.jsonl")
FEATURES = ("bt_min_k", "bt_trend_k_per_min", "cloud_height_m", "area_growth_km2_per_min", "cape", "li", "core_ratio")


def percentile(vals: list[float], q: float) -> float | None:
    if not vals:
        return None
    vals = sorted(vals)
    return vals[min(len(vals) - 1, int(round(q * (len(vals) - 1))))]


def main() -> int:
    pos = neg = 0
    lead: list[float] = []
    reasons: Counter[str] = Counter()
    feature_counts: Counter[str] = Counter()
    if PATH.exists():
        for line in PATH.read_text(encoding="utf-8").splitlines():
            try:
                obj = json.loads(line)
            except Exception:
                continue
            if int(obj.get("became_radar_cell", 0) or 0) == 1:
                pos += 1
                if obj.get("lead_time_min") is not None:
                    try:
                        lead.append(float(obj["lead_time_min"]))
                    except Exception:
                        pass
            if int(obj.get("ended_without_radar", 0) or 0) == 1:
                neg += 1
                if obj.get("negative_reason"):
                    reasons[str(obj["negative_reason"])] += 1
            for key in FEATURES:
                if obj.get(key) is not None:
                    feature_counts[key] += 1
    print(f"file: {PATH}")
    print(f"positive: {pos}")
    print(f"negative: {neg}")
    print(f"median_lead_time_min: {median(lead) if lead else None}")
    print(f"p90_lead_time_min: {percentile(lead, 0.9)}")
    print(f"negative_reasons: {dict(reasons.most_common(5))}")
    print(f"top_features: {dict(feature_counts.most_common(10))}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
