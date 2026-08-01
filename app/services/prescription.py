"""Capture setup carried by a planned hangboard item.

A planned item may store a `prescription`: the same vocabulary the capture page
and /api/capture/start already speak (exercise, grip, hand, edge, protocol
numbers). That lets a planned session on the calendar be opened straight into
capture with every field filled in.

Only the fields that matter for the chosen exercise are kept, so what the
calendar shows and what capture prefills can never drift apart. Baseline tests
reuse `target_sets` for attempts and `set_rest_s` for rest between them, exactly
as the capture form does.
"""

from app.constants import (
    BASELINE_EXERCISES, EXERCISE_OPTIONS, GRIP_OPTIONS, HAND_OPTIONS,
    TIMER_EXERCISES,
)

EXERCISE_VALUES = [v for v, _ in EXERCISE_OPTIONS]
GRIP_VALUES = [v for v, _ in GRIP_OPTIONS]
HAND_VALUES = [v for v, _ in HAND_OPTIONS]

EXERCISE_LABELS = dict(EXERCISE_OPTIONS)
GRIP_LABELS = dict(GRIP_OPTIONS)


def _num(raw, key, lo, hi, cast=int):
    value = raw.get(key)
    if value is None or value == "":
        return None
    try:
        value = cast(value)
    except (TypeError, ValueError):
        return None
    return value if lo <= value <= hi else None


def _choice(raw, key, allowed, default):
    value = raw.get(key)
    return value if value in allowed else default


def parse(raw):
    """Normalize a form/dict into a prescription, or None if there isn't one.

    Unparsable or out-of-range numbers are dropped rather than rejected — a
    prescription is a convenience, and capture falls back to its own defaults
    for anything missing.
    """
    if not raw:
        return None
    exercise = raw.get("exercise_type")
    if exercise not in EXERCISE_VALUES:
        return None

    rx = {
        "exercise_type": exercise,
        "grip_type": _choice(raw, "grip_type", GRIP_VALUES, "half_crimp"),
        "hand": _choice(raw, "hand", HAND_VALUES, "right"),
        "edge_depth_mm": _num(raw, "edge_depth_mm", 4, 60) or 20,
    }
    if exercise in TIMER_EXERCISES:
        fields = {
            "on_seconds": (1, 600), "off_seconds": (0, 600),
            "target_sets": (1, 20), "target_reps": (1, 30),
            "set_rest_s": (0, 1800),
        }
    elif exercise in BASELINE_EXERCISES:
        fields = {"target_sets": (1, 10), "set_rest_s": (0, 1800)}
    else:
        fields = {}
    for key, (lo, hi) in fields.items():
        value = _num(raw, key, lo, hi)
        if value is not None:
            rx[key] = value
    if exercise == "repeaters":
        weight = _num(raw, "target_weight_kg", 0, 200, float)
        if weight:
            rx["target_weight_kg"] = weight

    notes = (raw.get("notes") or "").strip()
    if notes:
        rx["notes"] = notes
    return rx


def summary(rx):
    """One-line human description, e.g. "Max Hang · Half Crimp · 20mm · 3×3 · 7/53s"."""
    if not rx:
        return ""
    parts = [
        EXERCISE_LABELS.get(rx["exercise_type"], rx["exercise_type"]),
        GRIP_LABELS.get(rx.get("grip_type"), rx.get("grip_type")),
        f"{rx.get('edge_depth_mm')}mm",
        rx.get("hand"),
    ]
    if rx["exercise_type"] in BASELINE_EXERCISES:
        if rx.get("target_sets"):
            parts.append(f"{rx['target_sets']} attempts")
    elif rx.get("target_sets") and rx.get("target_reps"):
        parts.append(f"{rx['target_sets']}×{rx['target_reps']}")
    if rx.get("on_seconds") is not None and rx.get("off_seconds") is not None:
        parts.append(f"{rx['on_seconds']}/{rx['off_seconds']}s")
    if rx.get("set_rest_s") is not None:
        parts.append(f"rest {rx['set_rest_s']}s")
    if rx.get("target_weight_kg"):
        parts.append(f"target {rx['target_weight_kg']:g} kg")
    return " · ".join(str(p) for p in parts if p)
