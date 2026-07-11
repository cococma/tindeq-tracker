"""Climbing grade parsing → (grade_system, grade_rank) for sorting/charting."""

V_SCALE = {"VB": -1, **{f"V{i}": i for i in range(18)}}

FRENCH_SPORT = [
    "3a", "3b", "3c", "4a", "4b", "4c", "5a", "5b", "5c",
    "6a", "6a+", "6b", "6b+", "6c", "6c+",
    "7a", "7a+", "7b", "7b+", "7c", "7c+",
    "8a", "8a+", "8b", "8b+", "8c", "8c+",
    "9a", "9a+", "9b", "9b+", "9c",
]
FRENCH_RANK = {g: i for i, g in enumerate(FRENCH_SPORT)}


def parse_grade(grade: str):
    """Return (grade_system, grade_rank); rank is None for unrecognized grades."""
    g = grade.strip()
    upper = g.upper()
    if upper in V_SCALE:
        return "v_scale", V_SCALE[upper]
    lower = g.lower()
    if lower in FRENCH_RANK:
        return "french", FRENCH_RANK[lower]
    return "other", None
