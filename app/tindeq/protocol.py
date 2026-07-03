"""Tindeq Progressor BLE protocol — UUIDs, commands, and frame parsing."""

import struct

from bleak import BleakScanner

PROGRESSOR_SERVICE_UUID = "7e4e1701-1ea6-40c9-9dcc-13d34ffead57"
WRITE_CHAR_UUID         = "7e4e1703-1ea6-40c9-9dcc-13d34ffead57"
NOTIFY_CHAR_UUID        = "7e4e1702-1ea6-40c9-9dcc-13d34ffead57"

CMD_TARE_SCALE          = bytes([0x64])
CMD_START_WEIGHT_MEAS   = bytes([0x65])
CMD_STOP_WEIGHT_MEAS    = bytes([0x66])

RESP_WEIGHT_MEASUREMENT = 0x01


def parse_weight_frame(data: bytearray) -> list[tuple[float, int]]:
    """Parse a weight-measurement notification into (force_kg, device_ts_us) samples.

    Returns an empty list for non-weight frames.
    """
    if not data or data[0] != RESP_WEIGHT_MEASUREMENT:
        return []
    num_samples = (len(data) - 2) // 8
    samples = []
    for i in range(num_samples):
        force_kg, device_ts_us = struct.unpack_from("<fI", data, offset=2 + i * 8)
        samples.append((force_kg, device_ts_us))
    return samples


async def find_progressor(timeout: float = 10.0):
    """Scan for a Tindeq Progressor; returns the bleak device or None."""
    devices = await BleakScanner.discover(
        timeout=timeout, service_uuids=[PROGRESSOR_SERVICE_UUID]
    )
    return devices[0] if devices else None
