"""
Tindeq Progressor BLE tracker
Streams force data over Bluetooth and stores it in PostgreSQL.
"""

import asyncio
import struct
import signal
import sys
from datetime import datetime, timezone

import psycopg2
from bleak import BleakScanner, BleakClient
from dotenv import load_dotenv
import os

load_dotenv()

# ── Tindeq Progressor BLE constants ──────────────────────────────────────────

PROGRESSOR_SERVICE_UUID = "7e4e1701-1ea6-40c9-9dcc-13d34ffead57"
WRITE_CHAR_UUID         = "7e4e1702-1ea6-40c9-9dcc-13d34ffead57"
NOTIFY_CHAR_UUID        = "7e4e1703-1ea6-40c9-9dcc-13d34ffead57"

CMD_TARE_SCALE          = bytes([0x64])
CMD_START_WEIGHT_MEAS   = bytes([0x65])
CMD_STOP_WEIGHT_MEAS    = bytes([0x66])

RESP_WEIGHT_MEASUREMENT = 0x01

# ── Database ──────────────────────────────────────────────────────────────────

def get_db_connection():
    return psycopg2.connect(
        host=os.getenv("DB_HOST", "localhost"),
        port=int(os.getenv("DB_PORT", 5432)),
        dbname=os.getenv("DB_NAME", "tindeq"),
        user=os.getenv("DB_USER", "postgres"),
        password=os.getenv("DB_PASSWORD", ""),
    )


def create_session(conn, notes=None):
    with conn.cursor() as cur:
        cur.execute(
            "INSERT INTO sessions (notes) VALUES (%s) RETURNING id",
            (notes,)
        )
        session_id = cur.fetchone()[0]
    conn.commit()
    return session_id


def close_session(conn, session_id):
    with conn.cursor() as cur:
        cur.execute(
            "UPDATE sessions SET ended_at = NOW() WHERE id = %s",
            (session_id,)
        )
    conn.commit()


def insert_measurement(conn, session_id, force_kg, device_ts_us):
    with conn.cursor() as cur:
        cur.execute(
            """
            INSERT INTO measurements (session_id, recorded_at, force_kg, device_ts_us)
            VALUES (%s, %s, %s, %s)
            """,
            (session_id, datetime.now(timezone.utc), force_kg, device_ts_us)
        )
    conn.commit()

# ── BLE ───────────────────────────────────────────────────────────────────────

async def find_progressor():
    """Scan for a Tindeq Progressor and return its address."""
    print("Scanning for Tindeq Progressor...")
    devices = await BleakScanner.discover(timeout=10.0, service_uuids=[PROGRESSOR_SERVICE_UUID])
    if not devices:
        raise RuntimeError("No Tindeq Progressor found. Make sure it is powered on and nearby.")
    device = devices[0]
    print(f"Found: {device.name} ({device.address})")
    return device.address


async def run_session(notes=None):
    conn = get_db_connection()
    session_id = create_session(conn, notes)
    print(f"Session {session_id} started.")

    address = await find_progressor()

    # Used to signal a clean stop (Ctrl+C)
    stop_event = asyncio.Event()

    def on_signal(*_):
        print("\nStopping measurement...")
        stop_event.set()

    signal.signal(signal.SIGINT, on_signal)

    measurement_count = 0

    def handle_notification(sender, data: bytearray):
        nonlocal measurement_count

        response_code = data[0]
        if response_code != RESP_WEIGHT_MEASUREMENT:
            return  # ignore non-measurement packets (battery, ack, etc.)

        # Unpack: float32 force (kg) + uint32 device timestamp (microseconds)
        force_kg, device_ts_us = struct.unpack_from("<fI", data, offset=1)

        insert_measurement(conn, session_id, force_kg, device_ts_us)
        measurement_count += 1

        # Print a live readout every 10 samples (~8x/sec)
        if measurement_count % 10 == 0:
            print(f"  {force_kg:.2f} kg  (sample {measurement_count})", end="\r")

    async with BleakClient(address) as client:
        print("Connected. Taring scale...")
        await client.write_gatt_char(WRITE_CHAR_UUID, CMD_TARE_SCALE, response=True)
        await asyncio.sleep(0.5)

        print("Starting measurement stream. Press Ctrl+C to stop.")
        await client.start_notify(NOTIFY_CHAR_UUID, handle_notification)
        await client.write_gatt_char(WRITE_CHAR_UUID, CMD_START_WEIGHT_MEAS, response=True)

        await stop_event.wait()

        await client.write_gatt_char(WRITE_CHAR_UUID, CMD_STOP_WEIGHT_MEAS, response=True)
        await client.stop_notify(NOTIFY_CHAR_UUID)

    close_session(conn, session_id)
    conn.close()
    print(f"\nSession {session_id} saved — {measurement_count} measurements recorded.")


# ── Entry point ───────────────────────────────────────────────────────────────

if __name__ == "__main__":
    notes = input("Session notes (press Enter to skip): ").strip() or None
    asyncio.run(run_session(notes))
