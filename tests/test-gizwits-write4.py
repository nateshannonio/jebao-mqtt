#!/usr/bin/env python3
"""
Gizwits P0 Write Test - Round 4 (TARGETED)

BREAKTHROUGH from Round 3:
- D1: P0=[0x01, 0x02, 0x37] -> Speed changed to 30% (flag 0x02 = some data point)
- D2: P0=[0x01, 0x04, 0x37] -> Speed changed to 0%  (flag 0x04 = some data point)

The minimal write format WORKS:
  P0 = action(0x01) + attr_flags(1 byte) + attr_vals(minimal)

But we have the wrong flag-to-datapoint mapping. The speed value 0x37 (55) was
applied to the wrong data point, causing unexpected values.

The bool flags byte from status is 0x11 = 00010001:
  bit 0 = 1 (power ON)
  bit 4 = 1 (unknown)

Data points in the Gizwits scheme:
  - Bools are packed: bits 0-7 of the first byte
  - Each bool is a separate data point
  - Non-bool values follow after

So the data point order might be:
  DP0 = bool bit 0 (power)
  DP1 = bool bit 1 (feed?)
  DP2 = bool bit 2
  DP3 = bool bit 3
  DP4 = bool bit 4 (unknown, currently ON)
  DP5-7 = other bools
  DP8+ = non-bool values (speed would be first non-bool)

attr_flags bit mapping:
  bit 0 -> DP0 (power bool)
  bit 1 -> DP1 (feed bool?)
  bit 2 -> DP2 (another bool?)
  bit 3 -> DP3
  bit 4 -> DP4
  ...
  bit N -> first non-bool (speed?)

In Round 3:
  flags=0x02 (bit 1) set a value to 30 -> this might be feed or another bool
  flags=0x04 (bit 2) set a value to 0  -> this turned something off

For attr_vals with minimal format, each set flag bit needs ONE value in attr_vals.
For bools, the value is 0x00 or 0x01. For uint8, it's the actual value.

So when we sent [0x01, 0x02, 0x37]:
  - bit 1 = 1 data point to write
  - 0x37 (55) was applied to DP1
  - If DP1 is a bool, 55 != 0 = TRUE, but maybe it clipped to something

THIS TEST: Systematically test each flag bit with proper values to map the protocol.
First restore the pump, then probe each data point.
"""

import asyncio
import time
from bleak import BleakClient

MDP_MAC = "7725528E-75A8-F1C3-71E6-CEF9A6EDA5EE"
SERVICE_UUID = "0000abf0-0000-1000-8000-00805f9b34fb"
CHAR_UUID = "0000abf7-0000-1000-8000-00805f9b34fb"

SPEED_POS_IN_P0 = 27


def build_packet(cmd: int, payload: bytes) -> bytes:
    length = 3 + len(payload)
    return bytes([0x00, 0x00, 0x00, 0x03, length, 0x00]) + cmd.to_bytes(2, 'big') + payload


class PacketReassembler:
    def __init__(self):
        self.buffer = bytearray()
        self.expected_len = 0
        self.complete_packets = []

    def feed(self, data: bytes):
        completed = []
        if not self.buffer:
            if len(data) >= 5 and data[:4] == bytes([0x00, 0x00, 0x00, 0x03]):
                self.expected_len = 5 + data[4]
                self.buffer.extend(data)
            else:
                return completed
        else:
            self.buffer.extend(data)

        if len(self.buffer) >= self.expected_len > 0:
            packet = bytes(self.buffer[:self.expected_len])
            completed.append(packet)
            self.complete_packets.append(packet)
            remainder = bytes(self.buffer[self.expected_len:])
            self.buffer = bytearray()
            self.expected_len = 0
            if remainder:
                completed.extend(self.feed(remainder))
        return completed


async def read_full_status(client, reassembler):
    """Read status, return (speed, full_p0, device_data) or (None, None, None)"""
    before = len(reassembler.complete_packets)
    sn = int(time.time())
    await client.write_gatt_char(CHAR_UUID,
        build_packet(0x93, sn.to_bytes(4, 'big') + bytes([0x02, 0x00])))
    await asyncio.sleep(3.0)

    for pkt in reassembler.complete_packets[before:]:
        if len(pkt) >= 8 and int.from_bytes(pkt[6:8], 'big') == 0x0100:
            if len(pkt) > 12 + SPEED_POS_IN_P0:
                p0 = pkt[12:]
                speed = p0[SPEED_POS_IN_P0]
                devdata = p0[25:]
                return speed, p0, devdata
    return None, None, None


async def send_control(client, reassembler, attr_flags: bytes, attr_vals: bytes):
    """Send a control command. Returns new (speed, bool_flags, devdata) or None."""
    p0 = bytes([0x01]) + attr_flags + attr_vals
    sn = int(time.time())
    payload = sn.to_bytes(4, 'big') + p0
    packet = build_packet(0x93, payload)

    print(f"    TX P0: {p0.hex()}")
    await client.write_gatt_char(CHAR_UUID, packet)
    await asyncio.sleep(1.5)

    if not client.is_connected:
        print(f"    DISCONNECTED!")
        return None

    speed, p0_new, devdata = await read_full_status(client, reassembler)
    return speed, p0_new, devdata


async def run_tests():
    print("=" * 70)
    print("Gizwits P0 Write Test - Round 4 (TARGETED)")
    print("=" * 70)

    reassembler = PacketReassembler()

    def handler(sender, data):
        completed = reassembler.feed(data)
        for pkt in completed:
            if len(pkt) >= 8:
                cmd = int.from_bytes(pkt[6:8], 'big')
                tags = {0x0094: "ACK", 0x0100: "STATUS", 0x0007: "PASS",
                        0x0009: "LOGIN", 0x0062: "DEV"}
                print(f"    <- {tags.get(cmd, f'0x{cmd:04x}')} ({len(pkt)}B)")

    try:
        async with BleakClient(MDP_MAC) as client:
            await client.start_notify(CHAR_UUID, handler)

            # Auth
            print("[1] Authenticating...")
            await client.write_gatt_char(CHAR_UUID, build_packet(0x06, b''))
            await asyncio.sleep(0.5)

            passcode = None
            for pkt in reassembler.complete_packets:
                if len(pkt) >= 8 and int.from_bytes(pkt[6:8], 'big') == 0x0007:
                    passcode = pkt[8:]
                    break
            if not passcode:
                print("  No passcode!")
                return

            await client.write_gatt_char(CHAR_UUID, build_packet(0x08, passcode))
            await asyncio.sleep(1.5)
            print("  Authenticated")

            # Read initial status
            print("\n[2] Reading initial status...")
            speed, p0, devdata = await read_full_status(client, reassembler)
            if speed is None:
                print("  No status!")
                return

            bool_flags = devdata[1]  # 0x11
            print(f"  Speed: {speed}%")
            print(f"  Bool flags: 0x{bool_flags:02x} = {bool_flags:08b}")
            print(f"  Device data[0:10]: {devdata[:10].hex()}")

            # ============================================================
            # PHASE 1: Restore pump if it's at 0%
            # ============================================================
            if speed == 0:
                print("\n[2.5] Pump at 0%! Trying to restore...")
                # Try flag 0x01 (bit 0 = power?) with value 0x01 (ON)
                result = await send_control(client, reassembler,
                    bytes([0x01]), bytes([0x01]))
                if result:
                    speed, p0, devdata = result
                    print(f"  After power ON: speed={speed}%, flags=0x{devdata[1]:02x}")

            # ============================================================
            # PHASE 2: Map each flag bit to its data point
            # ============================================================
            # Strategy: For each flag bit, send a known value and see
            # which field in the status response changes.

            print("\n[3] Mapping flag bits to data points...")
            print("    For each bit, we send a value and check what changed.\n")

            # First, capture baseline
            speed_baseline, p0_baseline, dd_baseline = await read_full_status(client, reassembler)
            if speed_baseline is None:
                print("  Can't get baseline!")
                return
            print(f"  Baseline: speed={speed_baseline}%, flags=0x{dd_baseline[1]:02x}")
            print(f"  Baseline devdata: {dd_baseline[:10].hex()}")

            # Test each bit
            for bit in range(8):
                if not client.is_connected:
                    print(f"\n  DISCONNECTED at bit {bit}!")
                    break

                flag = bytes([1 << bit])
                # For bool data points, send 0x01 (true)
                # For uint8 data points, send a distinctive value
                test_val = 80  # Use 80% - safe speed value, distinctive in status

                print(f"\n  --- Bit {bit} (flag=0x{flag[0]:02x}) with value {test_val} ---")

                result = await send_control(client, reassembler, flag, bytes([test_val]))

                if result is None:
                    print(f"    Disconnected!")
                    break

                new_speed, new_p0, new_dd = result
                print(f"    Result: speed={new_speed}%")
                print(f"    Bool flags: 0x{new_dd[1]:02x} = {new_dd[1]:08b}")
                print(f"    Devdata[0:10]: {new_dd[:10].hex()}")

                # Compare with baseline to find what changed
                changes = []
                for j in range(min(len(dd_baseline), len(new_dd))):
                    if dd_baseline[j] != new_dd[j]:
                        changes.append((j, dd_baseline[j], new_dd[j]))

                if changes:
                    print(f"    CHANGES detected:")
                    for pos, old, new in changes:
                        print(f"      devdata[{pos}]: 0x{old:02x} -> 0x{new:02x} ({old} -> {new})")

                        if new == test_val:
                            print(f"      *** FLAG BIT {bit} -> devdata[{pos}] (value applied!) ***")
                            if pos == 2:  # speed position in devdata
                                print(f"      *** THIS IS THE SPEED CONTROL! ***")
                else:
                    print(f"    No changes detected")

                # Update baseline for next test
                dd_baseline = new_dd
                speed_baseline = new_speed

                await asyncio.sleep(0.5)

            # ============================================================
            # PHASE 3: Try multi-value writes
            # ============================================================
            if client.is_connected:
                print(f"\n[4] Testing multi-flag writes...")
                print(f"  Current speed: {speed_baseline}%")

                # Try combining power (bit 0) + speed control
                # If bit N controls speed, try: flags = 0x01 | (1<<N), vals = [power, speed]
                # The attr_vals order matches the flag bit order

                # Based on round 3: bit0=power, bit1=feed, bit2=speed
                # attr_vals has one value per set bit, in bit order
                tests = [
                    # Power ON + speed 50%
                    ("flags=0x05 (power+speed), vals=[0x01, 50]",
                        bytes([0x05]), bytes([0x01, 50])),
                    # Power ON + speed 80%
                    ("flags=0x05 (power+speed), vals=[0x01, 80]",
                        bytes([0x05]), bytes([0x01, 80])),
                    # Power ON + feed OFF + speed 50%
                    ("flags=0x07 (power+feed+speed), vals=[0x01, 0x00, 50]",
                        bytes([0x07]), bytes([0x01, 0x00, 50])),
                    # Just speed 80%
                    ("flags=0x04 (speed only), vals=[80]",
                        bytes([0x04]), bytes([80])),
                    # Just speed 50%
                    ("flags=0x04 (speed only), vals=[50]",
                        bytes([0x04]), bytes([50])),
                    # Power ON only
                    ("flags=0x01 (power only), vals=[0x01]",
                        bytes([0x01]), bytes([0x01])),
                ]

                for desc, flags, vals in tests:
                    if not client.is_connected:
                        break
                    print(f"\n  {desc}")
                    result = await send_control(client, reassembler, flags, vals)
                    if result:
                        s, _, dd = result
                        print(f"    Result: speed={s}%, flags=0x{dd[1]:02x}")
                        if s == 75:
                            print(f"    *** RESTORED TO 75%! ***")

            if client.is_connected:
                # Final status
                print(f"\n[5] Final status...")
                speed, p0, devdata = await read_full_status(client, reassembler)
                if speed is not None:
                    print(f"  Speed: {speed}%")
                    print(f"  Bool flags: 0x{devdata[1]:02x}")
                    print(f"  Devdata[0:15]: {devdata[:15].hex()}")

                await client.stop_notify(CHAR_UUID)

    except Exception as e:
        print(f"\nError: {e}")
        import traceback
        traceback.print_exc()


if __name__ == "__main__":
    asyncio.run(run_tests())
