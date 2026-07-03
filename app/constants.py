"""Shared exercise / grip / hand vocabulary — single source of truth.

Options are (value, label) tuples; value is what gets stored in the DB.
"""

EXERCISE_OPTIONS = [
    ("repeaters",        "Repeaters"),
    ("max_hang",         "Max Hang"),
    ("recruitment_pull", "Recruitment Pull"),
    ("mvc_test",         "MVC Baseline Test"),
    ("rfd_test",         "RFD Baseline Test"),
    ("min_edge",         "Min Edge"),
    ("force_test",       "Force Test"),
]

GRIP_OPTIONS = [
    ("half_crimp", "Half Crimp"),
    ("full_crimp", "Full Crimp"),
    ("open_hand",  "Open Hand"),
    ("pinch",      "Pinch"),
]

HAND_OPTIONS = [
    ("right", "Right hand"),
    ("left",  "Left hand"),
    ("both",  "Both hands (two sessions, one per hand)"),
]

# Baseline tests are saved to baseline_tests instead of sessions/measurements.
BASELINE_EXERCISES = ("mvc_test", "rfd_test")

# Exercises driven by the on/off/sets/reps timer.
TIMER_EXERCISES = ("repeaters", "max_hang")

# Default protocol parameters per timer exercise: (on/off seconds, sets/reps).
EXERCISE_DEFAULTS = {
    "repeaters": {"on_off": (7, 3),  "sets_reps": (6, 6)},
    "max_hang":  {"on_off": (7, 53), "sets_reps": (3, 3)},
}

EXERCISE_DESCRIPTIONS = {
    "repeaters": (
        "REPEATERS\n"
        "Hang for {on_s}s, rest {off_s}s — repeat for {reps} reps per set.\n"
        "Complete {sets} sets with {set_rest_s}s rest between sets.\n"
        "Focus on consistent force output across all reps."
    ),
    "max_hang": (
        "MAX HANG\n"
        "Hang as hard as you can for {on_s}s, rest {off_s}s — repeat for {reps} reps per set.\n"
        "Complete {sets} sets with {set_rest_s}s rest between sets.\n"
        "Aim for maximum force — pull through the entire hang."
    ),
    "recruitment_pull": (
        "RECRUITMENT PULL\n"
        "Pull as hard and fast as possible for 1-2 seconds — {pulls} total pulls.\n"
        "Rest fully between each pull (2-3 mins).\n"
        "Focus on explosive onset — maximum RFD, not sustained force."
    ),
    "mvc_test": (
        "MVC BASELINE TEST\n"
        "Build to maximum force and hold for 3-5 seconds.\n"
        "This is your strength ceiling — pull as hard as you can."
    ),
    "rfd_test": (
        "RFD BASELINE TEST\n"
        "Pull as explosively as possible — peak force in the shortest time.\n"
        "Hold briefly at peak, then release."
    ),
    "force_test": (
        "FORCE TEST\n"
        "Pull however you like — no protocol, no timer.\n"
        "Nothing is saved."
    ),
}
