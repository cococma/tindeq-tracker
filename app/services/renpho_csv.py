"""Renpho CSV export importer.

The Renpho app's CSV export headers vary by app version and locale, so we
match normalized header tokens rather than exact strings. Values in lb are
converted to kg.
"""

import csv
import io
import re
from datetime import datetime

LB_TO_KG = 0.45359237

# (predicate on normalized header) -> metric code. First match wins;
# order matters (e.g. "muscle mass" before bare "muscle").
HEADER_RULES = [
    (lambda h: "time" in h or "date" in h, "_timestamp"),
    (lambda h: "fatfree" in h or "fat free" in h, "fat_free_mass_kg"),
    (lambda h: "subcutaneous" in h, "subcutaneous_fat_pct"),
    (lambda h: "visceral" in h, "visceral_fat"),
    (lambda h: "bodyfat" in h or "body fat" in h or "fat(" in h, "body_fat_pct"),
    (lambda h: "muscle mass" in h or "musclemass" in h, "muscle_mass_kg"),
    (lambda h: "skeletal" in h, "skeletal_muscle_pct"),
    (lambda h: "bone" in h, "bone_mass_kg"),
    (lambda h: "water" in h, "water_pct"),
    (lambda h: "protein" in h, "protein_pct"),
    (lambda h: "bmr" in h or "metabolism" in h, "bmr_kcal"),
    (lambda h: "metabolic age" in h or "body age" in h, "metabolic_age"),
    (lambda h: "bmi" in h, "bmi"),
    (lambda h: "weight" in h, "weight_kg"),
]

TIMESTAMP_FORMATS = [
    "%Y-%m-%d %H:%M:%S",
    "%Y/%m/%d %H:%M:%S",
    "%d/%m/%Y %H:%M:%S",
    "%m/%d/%Y %H:%M:%S",
    "%Y-%m-%d %H:%M",
    "%Y-%m-%d",
    "%b %d, %Y %I:%M:%S %p",
]


def _normalize(header: str) -> str:
    return re.sub(r"\s+", " ", header.strip().lower().replace("-", " ").replace("_", " "))


def _map_headers(headers):
    mapping = {}
    for i, header in enumerate(headers):
        h = _normalize(header)
        for predicate, metric in HEADER_RULES:
            if predicate(h):
                mapping[i] = (metric, "lb" in h)
                break
    return mapping


def _parse_ts(value: str):
    v = value.strip()
    for fmt in TIMESTAMP_FORMATS:
        try:
            return datetime.strptime(v, fmt)
        except ValueError:
            continue
    return None


def parse_renpho_csv(text: str, source: str = "renpho_csv"):
    """Parse CSV text → (rows for repos.metrics.insert_metrics, skipped_count)."""
    reader = csv.reader(io.StringIO(text))
    try:
        headers = next(reader)
    except StopIteration:
        return [], 0

    mapping = _map_headers(headers)
    ts_cols = [i for i, (m, _) in mapping.items() if m == "_timestamp"]
    if not ts_cols:
        raise ValueError(f"No timestamp column recognized in headers: {headers}")
    ts_col = ts_cols[0]

    rows, skipped = [], 0
    for record in reader:
        if len(record) <= ts_col:
            continue
        ts = _parse_ts(record[ts_col])
        if ts is None:
            skipped += 1
            continue
        for i, (metric, is_lb) in mapping.items():
            if metric == "_timestamp" or i >= len(record):
                continue
            raw = record[i].strip().replace("%", "")
            if not raw:
                continue
            try:
                value = float(raw)
            except ValueError:
                continue
            if is_lb:
                value *= LB_TO_KG
            rows.append({
                "source": source,
                "metric": metric,
                "value": round(value, 3),
                "recorded_at": ts,
                "metadata": None,
            })
    return rows, skipped
