#!/usr/bin/env python3
"""
Jebao Pump BLE Scanner

Scans for Jebao/Gizwits BLE devices and displays their MAC addresses.
Jebao pumps advertise as "XPG-GAgent-XXXX" using the Gizwits BLE module.

Usage:
    python3 scan.py              # Quick 10-second scan
    python3 scan.py --duration 30  # Longer scan
    python3 scan.py --all          # Show ALL BLE devices
"""

import asyncio
import argparse
from bleak import BleakScanner

# Gizwits BLE service UUID used by Jebao pumps
GIZWITS_SERVICE_UUID = "0000abf0-0000-1000-8000-00805f9b34fb"

# Name patterns for Jebao devices
JEBAO_PATTERNS = ["XPG-GAgent", "XPG_GAgent", "Jebao", "Gizwits"]


def is_jebao(name: str, service_uuids: list) -> bool:
    """Check if a device is a Jebao pump"""
    if name:
        for pattern in JEBAO_PATTERNS:
            if pattern.lower() in name.lower():
                return True
    if GIZWITS_SERVICE_UUID.lower() in [u.lower() for u in service_uuids]:
        return True
    return False


async def scan(duration: int, show_all: bool):
    print(f"Scanning for {'all BLE devices' if show_all else 'Jebao pumps'}... ({duration}s)")
    print("Make sure pumps are powered on and not connected to the Jebao app.\n")

    devices = await BleakScanner.discover(
        timeout=duration,
        return_adv=True
    )

    jebao_found = []
    other_found = []

    for address, (device, adv_data) in devices.items():
        name = adv_data.local_name or device.name or ""
        uuids = [str(u) for u in (adv_data.service_uuids or [])]
        rssi = adv_data.rssi

        if is_jebao(name, uuids):
            jebao_found.append((address, name, rssi, uuids))
        else:
            other_found.append((address, name, rssi))

    # Print Jebao devices
    if jebao_found:
        print("=" * 60)
        print(f"  JEBAO PUMPS FOUND: {len(jebao_found)}")
        print("=" * 60)
        for addr, name, rssi, uuids in sorted(jebao_found, key=lambda x: x[2], reverse=True):
            print(f"\n  MAC:    {addr}")
            print(f"  Name:   {name}")
            print(f"  Signal: {rssi} dBm", end="")
            if rssi > -60:
                print("  (strong)")
            elif rssi > -80:
                print("  (good)")
            else:
                print("  (weak - move closer)")

        print("\n" + "-" * 60)
        print("\nAdd to your config.yaml:")
        print()
        print("pumps:")
        for i, (addr, name, rssi, uuids) in enumerate(jebao_found, 1):
            suffix = addr.replace(":", "")[-4:].upper()
            print(f'  - name: "Wavemaker {i}"')
            print(f'    mac: "{addr}"')
            if i < len(jebao_found):
                print()
    else:
        print("=" * 60)
        print("  NO JEBAO PUMPS FOUND")
        print("=" * 60)
        print()
        print("Troubleshooting:")
        print("  1. Is the pump powered on?")
        print("  2. Is the BLE LED blinking on the pump controller?")
        print("  3. Close the Jebao app - only one BLE connection at a time")
        print("  4. Move closer to the pump")
        print("  5. Try a longer scan: python3 scan.py --duration 30")
        print("  6. Try showing all devices: python3 scan.py --all")

    # Print other devices if requested
    if show_all and other_found:
        print(f"\n\nOther BLE devices ({len(other_found)}):")
        print("-" * 60)
        for addr, name, rssi in sorted(other_found, key=lambda x: x[2], reverse=True):
            display_name = name if name else "(unnamed)"
            print(f"  {addr}  {rssi:>4} dBm  {display_name}")

    print()


def main():
    parser = argparse.ArgumentParser(description="Scan for Jebao BLE pumps")
    parser.add_argument(
        "--duration", "-d",
        type=int,
        default=10,
        help="Scan duration in seconds (default: 10)"
    )
    parser.add_argument(
        "--all", "-a",
        action="store_true",
        help="Show all BLE devices, not just Jebao"
    )
    args = parser.parse_args()

    asyncio.run(scan(args.duration, args.all))


if __name__ == "__main__":
    main()