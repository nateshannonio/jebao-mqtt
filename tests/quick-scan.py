#!/usr/bin/env python3
"""Quick BLE scan to find the pump"""

import asyncio
from bleak import BleakScanner

async def scan():
    print("🔍 Scanning for BLE devices...")
    devices = await BleakScanner.discover(timeout=10.0)
    
    print(f"Found {len(devices)} devices:")
    for device in devices:
        print(f"  {device.address} - {device.name}")
        if "jebao" in (device.name or "").lower():
            print(f"    🎯 FOUND JEBAO DEVICE!")

if __name__ == "__main__":
    asyncio.run(scan())