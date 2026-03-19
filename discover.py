"""
Connects to the Progressor and prints all services and characteristics.
Run this to find the correct UUIDs.
"""
import asyncio
from bleak import BleakScanner, BleakClient

PROGRESSOR_SERVICE_UUID = "7e4e1701-1ea6-40c9-9dcc-13d34ffead57"

async def main():
    print("Scanning...")
    devices = await BleakScanner.discover(timeout=10.0, service_uuids=[PROGRESSOR_SERVICE_UUID])
    if not devices:
        print("No Progressor found.")
        return

    device = devices[0]
    print(f"Found: {device.name} ({device.address})\n")

    async with BleakClient(device.address) as client:
        for service in client.services:
            print(f"Service: {service.uuid}")
            for char in service.characteristics:
                print(f"  Characteristic: {char.uuid}")
                print(f"    Properties: {', '.join(char.properties)}")
                print(f"    Handle: {char.handle}")
            print()

asyncio.run(main())
