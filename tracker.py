"""
Tindeq Progressor BLE tracker
Streams force data over Bluetooth and stores it in PostgreSQL.
"""

import asyncio
import struct
import signal
import subprocess
from datetime import datetime

import psycopg2
from bleak import BleakScanner, BleakClient
from dotenv import load_dotenv
import os

load_dotenv()

# ── Tindeq Progressor BLE constants ──────────────────────────────────────────

PROGRESSOR_SERVICE_UUID = "7e4e1701-1ea6-40c9-9dcc-13d34ffead57"
WRITE_CHAR_UUID         = "7e4e1703-1ea6-40c9-9dcc-13d34ffead57"
NOTIFY_CHAR_UUID        = "7e4e1702-1ea6-40c9-9dcc-13d34ffead57"

CMD_TARE_SCALE          = bytes([0x64])
CMD_START_WEIGHT_MEAS   = bytes([0x65])
CMD_STOP_WEIGHT_MEAS    = bytes([0x66])

RESP_WEIGHT_MEASUREMENT = 0x01

# ── Audio ─────────────────────────────────────────────────────────────────────

def say(text):
    """Fire a macOS text-to-speech cue without blocking."""
    subprocess.Popen(["say", text], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)


async def countdown(seconds):
    """Speak a countdown for the last N seconds of a phase."""
    for i in range(seconds, 0, -1):
        say(str(i))
        await asyncio.sleep(1)


async def run_timer(cfg, stop_event):
    """
    Run audio cues for repeaters and max hang sessions.
    Runs concurrently with the BLE measurement stream.
    """
    on_s       = cfg.get("on_seconds") or 7
    off_s      = cfg.get("off_seconds") or 3
    sets       = cfg.get("target_sets") or 1
    reps       = cfg.get("target_reps") or 1
    set_rest_s = cfg.get("set_rest_s") or 180

    # 3-second lead-in before the first hang
    say("Starting in")
    await countdown(3)

    for set_num in range(1, sets + 1):
        if stop_event.is_set():
            return

        for rep_num in range(1, reps + 1):
            if stop_event.is_set():
                return

            # ── Hang phase ────────────────────────────────────────────────
            say("Hang")

            if on_s > 3:
                await asyncio.sleep(on_s - 3)
                if stop_event.is_set():
                    return
                await countdown(3)
            else:
                await asyncio.sleep(on_s)

            # ── Rest phase (between reps) ─────────────────────────────────
            if rep_num < reps:
                say("Rest")
                if off_s > 3:
                    await asyncio.sleep(off_s - 3)
                    if stop_event.is_set():
                        return
                    await countdown(3)
                else:
                    await asyncio.sleep(off_s)

        # ── Set complete ──────────────────────────────────────────────────
        if set_num < sets:
            say(f"Set {set_num} complete. Rest.")

            # Announce at 60s, 30s, 10s remaining
            checkpoints = [60, 30, 10]
            elapsed = 0
            for cp in checkpoints:
                wait = set_rest_s - elapsed - cp
                if wait > 0:
                    await asyncio.sleep(wait)
                    if stop_event.is_set():
                        return
                    say(f"{cp} seconds")
                    elapsed = set_rest_s - cp

            remaining = set_rest_s - elapsed
            if remaining > 3:
                await asyncio.sleep(remaining - 3)
                if stop_event.is_set():
                    return
            await countdown(3)

    say("Session complete")


# ── Prompt helpers ────────────────────────────────────────────────────────────

def prompt(label, default):
    """Prompt with a default value — Enter accepts the default."""
    val = input(f"  {label} [{default}]: ").strip()
    return val if val else str(default)


def prompt_int(label, default):
    while True:
        val = prompt(label, default)
        try:
            return int(val)
        except ValueError:
            print("    Enter a whole number.")


def prompt_float(label, default):
    while True:
        val = prompt(label, default)
        try:
            return float(val)
        except ValueError:
            print("    Enter a number.")


def prompt_choice(label, options, default_index=0):
    """Display a numbered list and return the chosen key."""
    print(f"\n  {label}:")
    for i, (_, display) in enumerate(options, 1):
        marker = " [default]" if i - 1 == default_index else ""
        print(f"    {i}. {display}{marker}")
    while True:
        val = input(f"  Select [1-{len(options)}] or Enter for default: ").strip()
        if not val:
            return options[default_index][0]
        try:
            idx = int(val) - 1
            if 0 <= idx < len(options):
                return options[idx][0]
        except ValueError:
            pass
        print(f"    Enter a number between 1 and {len(options)}.")


EXERCISE_OPTIONS = [
    ("repeaters",         "Repeaters"),
    ("max_hang",          "Max Hang"),
    ("recruitment_pull",  "Recruitment Pull"),
    ("mvc_test",          "MVC Baseline Test"),
    ("rfd_test",          "RFD Baseline Test"),
    ("min_edge",          "Min Edge"),
]

GRIP_OPTIONS = [
    ("half_crimp", "Half Crimp"),
    ("full_crimp", "Full Crimp"),
    ("open_hand",  "Open Hand"),
    ("pinch",      "Pinch"),
]

# ── Session config ────────────────────────────────────────────────────────────

def get_session_config():
    """Interactively build session configuration from user input."""
    print("\n── Session Setup ─────────────────────────────────────────────")

    exercise_type = prompt_choice("Exercise", EXERCISE_OPTIONS, default_index=0)
    grip_type     = prompt_choice("Grip", GRIP_OPTIONS, default_index=0)

    print()
    edge_depth_mm = prompt_int("Edge depth (mm)", 20)

    cfg = {
        "exercise_type":     exercise_type,
        "grip_type":         grip_type,
        "edge_depth_mm":     edge_depth_mm,
        "target_weight_kg":  0,
        "on_seconds":        None,
        "off_seconds":       None,
        "target_reps":       None,
        "target_sets":       None,
        "set_rest_s":        180,
        "target_duration_s": None,
        "target_pull_reps":  None,
    }

    if exercise_type == "repeaters":
        cfg["target_weight_kg"] = prompt_float("Target weight (kg)", 0)

    if exercise_type in ("repeaters", "max_hang"):
        print()
        on_off = prompt("On/off seconds", "7/3" if exercise_type == "repeaters" else "7/53")
        try:
            on_s, off_s = [int(x.strip()) for x in on_off.split("/")]
        except Exception:
            on_s, off_s = (7, 3) if exercise_type == "repeaters" else (7, 53)

        sets_reps = prompt("Sets/reps", "6/6" if exercise_type == "repeaters" else "3/3")
        try:
            sets, reps = [int(x.strip()) for x in sets_reps.split("/")]
        except Exception:
            sets, reps = (6, 6) if exercise_type == "repeaters" else (3, 3)

        cfg["set_rest_s"] = prompt_int("Set rest (seconds)", 180)
        cfg.update({"on_seconds": on_s, "off_seconds": off_s,
                    "target_sets": sets, "target_reps": reps})

    elif exercise_type == "recruitment_pull":
        print()
        cfg["target_pull_reps"] = prompt_int("Number of pulls", 5)

    elif exercise_type in ("mvc_test", "rfd_test"):
        pass

    notes = input("\n  Notes (Enter to skip): ").strip() or None
    cfg["notes"] = notes

    print("──────────────────────────────────────────────────────────────\n")
    return cfg


# ── Database ──────────────────────────────────────────────────────────────────

def get_db_connection():
    return psycopg2.connect(
        host=os.getenv("DB_HOST", "localhost"),
        port=int(os.getenv("DB_PORT", 5432)),
        dbname=os.getenv("DB_NAME", "tindeq"),
        user=os.getenv("DB_USER", "postgres"),
        password=os.getenv("DB_PASSWORD", ""),
    )


def create_session(conn, cfg):
    with conn.cursor() as cur:
        cur.execute(
            """
            INSERT INTO sessions (
                exercise_type, grip_type, edge_depth_mm, target_weight_kg,
                on_seconds, off_seconds, target_reps, target_sets, set_rest_s,
                target_duration_s, target_pull_reps, notes
            ) VALUES (
                %(exercise_type)s, %(grip_type)s, %(edge_depth_mm)s, %(target_weight_kg)s,
                %(on_seconds)s, %(off_seconds)s, %(target_reps)s, %(target_sets)s, %(set_rest_s)s,
                %(target_duration_s)s, %(target_pull_reps)s, %(notes)s
            ) RETURNING id
            """,
            cfg
        )
        session_id = cur.fetchone()[0]
    conn.commit()
    return session_id


def close_session(conn, session_id):
    with conn.cursor() as cur:
        cur.execute("UPDATE sessions SET ended_at = NOW() WHERE id = %s", (session_id,))
    conn.commit()


def save_baseline(conn, cfg, peak_force_kg, rfd_kg_per_s=None):
    with conn.cursor() as cur:
        cur.execute(
            """
            INSERT INTO baseline_tests (
                test_type, grip_type, edge_depth_mm,
                peak_force_kg, rfd_kg_per_s, peak_force_rfd_kg, notes
            ) VALUES (%s, %s, %s, %s, %s, %s, %s)
            """,
            (
                cfg["exercise_type"],
                cfg["grip_type"],
                cfg["edge_depth_mm"],
                peak_force_kg,
                rfd_kg_per_s,
                peak_force_kg if rfd_kg_per_s else None,
                cfg.get("notes"),
            )
        )
    conn.commit()


def insert_measurements_batch(conn, session_id, samples):
    """Insert a batch of (force_kg, device_ts_us) tuples."""
    with conn.cursor() as cur:
        cur.executemany(
            """
            INSERT INTO measurements (session_id, recorded_at, force_kg, device_ts_us)
            VALUES (%s, NOW(), %s, %s)
            """,
            [(session_id, force, ts) for force, ts in samples]
        )
    conn.commit()


# ── Exercise descriptions ─────────────────────────────────────────────────────

EXERCISE_DESCRIPTIONS = {
    "repeaters": (
        "REPEATERS\n"
        "  Hang for {on_s}s, rest {off_s}s — repeat for {reps} reps per set.\n"
        "  Complete {sets} sets with {set_rest_s}s rest between sets.\n"
        "  Focus on consistent force output across all reps."
    ),
    "max_hang": (
        "MAX HANG\n"
        "  Hang as hard as you can for {on_s}s, rest {off_s}s — repeat for {reps} reps per set.\n"
        "  Complete {sets} sets with {set_rest_s}s rest between sets.\n"
        "  Aim for maximum force — pull through the entire hang."
    ),
    "recruitment_pull": (
        "RECRUITMENT PULL\n"
        "  Pull as hard and fast as possible for 1-2 seconds — {pulls} total pulls.\n"
        "  Rest fully between each pull (2-3 mins).\n"
        "  Focus on explosive onset — maximum RFD, not sustained force."
    ),
    "mvc_test": (
        "MVC BASELINE TEST\n"
        "  Build to maximum force and hold for 3-5 seconds.\n"
        "  This is your strength ceiling — pull as hard as you can.\n"
        "  Press Ctrl+C when done."
    ),
    "rfd_test": (
        "RFD BASELINE TEST\n"
        "  Pull as explosively as possible — peak force in the shortest time.\n"
        "  Hold briefly at peak, then release.\n"
        "  Press Ctrl+C when done."
    ),
    "force_test": (
        "FORCE TEST\n"
        "  Pull however you like — no protocol, no timer.\n"
        "  Nothing is saved. Press Ctrl+C when done."
    ),
}


def print_exercise_brief(cfg):
    ex   = cfg["exercise_type"]
    tmpl = EXERCISE_DESCRIPTIONS.get(ex, "Press Ctrl+C to stop when done.")
    desc = tmpl.format(
        on_s     = cfg.get("on_seconds") or "?",
        off_s    = cfg.get("off_seconds") or "?",
        reps     = cfg.get("target_reps") or "?",
        sets     = cfg.get("target_sets") or "?",
        set_rest_s = cfg.get("set_rest_s") or 180,
        pulls    = cfg.get("target_pull_reps") or "?",
    )
    print("\n──────────────────────────────────────────────────────────────")
    for line in desc.splitlines():
        print(f"  {line}")
    print("──────────────────────────────────────────────────────────────")
    input("\n  Press Enter to start...\n")


# ── BLE ───────────────────────────────────────────────────────────────────────

async def find_progressor():
    print("Scanning for Tindeq Progressor...")
    devices = await BleakScanner.discover(timeout=10.0, service_uuids=[PROGRESSOR_SERVICE_UUID])
    if not devices:
        raise RuntimeError("No Tindeq Progressor found. Make sure it is powered on and nearby.")
    device = devices[0]
    print(f"Found: {device.name} ({device.address})")
    return device.address


async def run_session(cfg):
    conn = get_db_connection()

    is_baseline  = cfg["exercise_type"] in ("mvc_test", "rfd_test")
    use_timer    = cfg["exercise_type"] in ("repeaters", "max_hang")

    if is_baseline:
        session_id = None
    else:
        session_id = create_session(conn, cfg)
        print(f"Session {session_id} started  [{cfg['exercise_type']} | {cfg['grip_type']} | {cfg['edge_depth_mm']}mm]")

    address = await find_progressor()

    stop_event = asyncio.Event()

    def on_signal(*_):
        print("\nStopping measurement...")
        stop_event.set()

    signal.signal(signal.SIGINT, on_signal)

    measurement_count = 0
    all_samples   = []
    peak_force    = 0.0
    force_history = []

    def handle_notification(sender, data: bytearray):
        nonlocal measurement_count, peak_force

        if data[0] != RESP_WEIGHT_MEASUREMENT:
            return

        num_samples = (len(data) - 2) // 8
        batch = []
        for i in range(num_samples):
            offset = 2 + i * 8
            force_kg, device_ts_us = struct.unpack_from("<fI", data, offset=offset)
            batch.append((force_kg, device_ts_us))
            force_history.append((force_kg, device_ts_us))
            if force_kg > peak_force:
                peak_force = force_kg
            measurement_count += 1

        all_samples.extend(batch)

        if measurement_count % 50 == 0:
            print(f"  {force_kg:.2f} kg  (peak {peak_force:.2f} kg)  sample {measurement_count}", end="\r")

    async with BleakClient(address) as client:
        print("Connected. Taring scale...")
        await client.write_gatt_char(WRITE_CHAR_UUID, CMD_TARE_SCALE, response=False)
        await asyncio.sleep(0.5)

        print_exercise_brief(cfg)
        print("Recording... Press Ctrl+C to stop.\n")
        await client.start_notify(NOTIFY_CHAR_UUID, handle_notification)
        await client.write_gatt_char(WRITE_CHAR_UUID, CMD_START_WEIGHT_MEAS, response=False)

        if use_timer:
            timer_task = asyncio.create_task(run_timer(cfg, stop_event))
            await stop_event.wait()
            timer_task.cancel()
        else:
            await stop_event.wait()

        await client.write_gatt_char(WRITE_CHAR_UUID, CMD_STOP_WEIGHT_MEAS, response=False)
        await client.stop_notify(NOTIFY_CHAR_UUID)

    if is_baseline:
        rfd = None
        if cfg["exercise_type"] == "rfd_test" and len(force_history) > 1:
            rfd = _calculate_rfd(force_history)
        save_baseline(conn, cfg, peak_force, rfd_kg_per_s=rfd)
        if cfg["exercise_type"] == "mvc_test":
            print(f"\nMVC Test saved — Peak force: {peak_force:.2f} kg")
        else:
            print(f"\nRFD Test saved — Peak force: {peak_force:.2f} kg  |  RFD: {rfd:.1f} kg/s" if rfd else f"\nRFD Test saved — Peak force: {peak_force:.2f} kg")
    else:
        if all_samples:
            insert_measurements_batch(conn, session_id, all_samples)
        close_session(conn, session_id)
        print(f"\nSession {session_id} saved — {measurement_count} measurements  |  Peak: {peak_force:.2f} kg")

    conn.close()


def _calculate_rfd(force_history):
    """Calculate max RFD (kg/s) over any 100ms window in the recording."""
    best_rfd = 0.0
    n = len(force_history)
    for i in range(n):
        f0, t0 = force_history[i]
        for j in range(i + 1, n):
            f1, t1 = force_history[j]
            dt_s = (t1 - t0) / 1_000_000
            if dt_s <= 0:
                continue
            if dt_s > 0.1:
                break
            rfd = (f1 - f0) / dt_s
            if rfd > best_rfd:
                best_rfd = rfd
    return best_rfd


# ── Entry point ───────────────────────────────────────────────────────────────

if __name__ == "__main__":
    cfg = get_session_config()
    asyncio.run(run_session(cfg))
