"""
Tindeq Progressor BLE tracker
Streams force data over Bluetooth and stores it in PostgreSQL.
"""

import asyncio
import struct
import signal
import sys
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
            print(f"    Enter a whole number.")


def prompt_float(label, default):
    while True:
        val = prompt(label, default)
        try:
            return float(val)
        except ValueError:
            print(f"    Enter a number.")


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
    edge_depth_mm    = prompt_int("Edge depth (mm)", 20)
    target_weight_kg = prompt_float("Target weight (kg)", 0)

    cfg = {
        "exercise_type":    exercise_type,
        "grip_type":        grip_type,
        "edge_depth_mm":    edge_depth_mm,
        "target_weight_kg": target_weight_kg,
        "on_seconds":       None,
        "off_seconds":      None,
        "target_reps":      None,
        "target_sets":      None,
        "target_duration_s": None,
        "target_pull_reps": None,
    }

    if exercise_type == "repeaters":
        print()
        on_off = prompt("On/off seconds", "7/3")
        try:
            on_s, off_s = [int(x.strip()) for x in on_off.split("/")]
        except Exception:
            on_s, off_s = 7, 3
        sets_reps = prompt("Sets/reps", "6/6")
        try:
            sets, reps = [int(x.strip()) for x in sets_reps.split("/")]
        except Exception:
            sets, reps = 6, 6
        cfg.update({"on_seconds": on_s, "off_seconds": off_s,
                    "target_sets": sets, "target_reps": reps})

    elif exercise_type == "max_hang":
        print()
        cfg["target_duration_s"] = prompt_int("Target duration (seconds)", 10)

    elif exercise_type == "recruitment_pull":
        print()
        cfg["target_pull_reps"] = prompt_int("Number of pulls", 5)

    elif exercise_type in ("mvc_test", "rfd_test"):
        pass  # no extra params needed

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
                on_seconds, off_seconds, target_reps, target_sets,
                target_duration_s, target_pull_reps, notes
            ) VALUES (
                %(exercise_type)s, %(grip_type)s, %(edge_depth_mm)s, %(target_weight_kg)s,
                %(on_seconds)s, %(off_seconds)s, %(target_reps)s, %(target_sets)s,
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

    is_baseline = cfg["exercise_type"] in ("mvc_test", "rfd_test")

    if is_baseline:
        session_id = None  # baselines don't create a session row
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
    all_samples = []       # (force_kg, device_ts_us)
    peak_force  = 0.0
    force_history = []     # for RFD calculation

    def handle_notification(sender, data: bytearray):
        nonlocal measurement_count, peak_force

        response_code = data[0]
        if response_code != RESP_WEIGHT_MEASUREMENT:
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

        if not is_baseline and measurement_count % 50 == 0:
            print(f"  {force_kg:.2f} kg  (peak {peak_force:.2f} kg)  sample {measurement_count}", end="\r")

        if is_baseline and measurement_count % 50 == 0:
            print(f"  {force_kg:.2f} kg  (peak {peak_force:.2f} kg)", end="\r")

    async with BleakClient(address) as client:
        print("Connected. Taring scale...")
        await client.write_gatt_char(WRITE_CHAR_UUID, CMD_TARE_SCALE, response=False)
        await asyncio.sleep(0.5)

        print("Starting measurement stream. Press Ctrl+C to stop.\n")
        await client.start_notify(NOTIFY_CHAR_UUID, handle_notification)
        await client.write_gatt_char(WRITE_CHAR_UUID, CMD_START_WEIGHT_MEAS, response=False)

        await stop_event.wait()

        await client.write_gatt_char(WRITE_CHAR_UUID, CMD_STOP_WEIGHT_MEAS, response=False)
        await client.stop_notify(NOTIFY_CHAR_UUID)

    if is_baseline:
        rfd = None
        if cfg["exercise_type"] == "rfd_test" and len(force_history) > 1:
            # RFD = max rate of force increase over any 0.1s window
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
            dt_s = (t1 - t0) / 1_000_000  # microseconds → seconds
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
