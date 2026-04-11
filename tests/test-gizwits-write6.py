#!/usr/bin/env python3
"""
Round 6: Simple 1-byte attr_flags with correct Motor_Speed bit

From APK schema + round 3 results:
- 1-byte attr_flags WORKS (bits 1,2 both changed device state in round 3)
- Motor_Speed = data point 5 = attr_flags bit 5 = 0x20
- attr_vals byte 0 = packed bools, byte 1 = Motor_Speed

P0 format: [0x01, flags(1B), bools_byte, speed_byte]
"""

import asyncio
import time
from bleak import BleakClient

MDP_MAC = "7725528E-75A8-F1C3-71E6-CEF9A6EDA5EE"
CHAR_UUID = "0000abf7-0000-1000-8000-00805f9b34fb"
P0_START = 12
DEVDATA_START = 25
SPEED_POS = 27


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


async def read_status(client, reasm):
    before = len(reasm.complete_packets)
    sn = int(time.time())
    await client.write_gatt_char(CHAR_UUID,
        build_packet(0x93, sn.to_bytes(4, 'big') + bytes([0x02, 0x00])))
    await asyncio.sleep(3.0)
    for pkt in reasm.complete_packets[before:]:
        if len(pkt) >= 8 and int.from_bytes(pkt[6:8], 'big') == 0x0100:
            if len(pkt) > P0_START + SPEED_POS:
                p0 = pkt[P0_START:]
                dd = p0[DEVDATA_START:]
                return dd[1], dd[2]  # bools, speed
    return None, None


async def send_and_check(client, reasm, desc, p0_data):
    """Send control, verify. Returns new speed or None."""
    print(f"\n  [{desc}]")
    print(f"    P0: {p0_data.hex()}")

    sn = int(time.time())
    payload = sn.to_bytes(4, 'big') + p0_data
    packet = build_packet(0x93, payload)

    await client.write_gatt_char(CHAR_UUID, packet)
    await asyncio.sleep(2.0)

    if not client.is_connected:
        print(f"    DISCONNECTED!")
        return None

    bools, speed = await read_status(client, reasm)
    if speed is not None:
        print(f"    Bools=0x{bools:02x} Speed={speed}%")
        return speed
    print(f"    No status response")
    return None


async def run():
    print("=" * 60)
    print("MDP Control - 1-byte flags with Motor_Speed (bit 5)")
    print("=" * 60)

    reasm = PacketReassembler()

    def handler(sender, data):
        completed = reasm.feed(data)
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
            print("[1] Auth...")
            await client.write_gatt_char(CHAR_UUID, build_packet(0x06, b''))
            await asyncio.sleep(0.5)
            passcode = None
            for pkt in reasm.complete_packets:
                if len(pkt) >= 8 and int.from_bytes(pkt[6:8], 'big') == 0x0007:
                    passcode = pkt[8:]
                    break
            if not passcode:
                print("  No passcode!")
                return
            await client.write_gatt_char(CHAR_UUID, build_packet(0x08, passcode))
            await asyncio.sleep(1.5)

            # Read status
            print("[2] Status...")
            bools, speed = await read_status(client, reasm)
            if speed is None:
                print("  No status!")
                return
            print(f"  Bools=0x{bools:02x} Speed={speed}%")

            # ============================================================
            # TEST A: flag=0x20 (bit5=Motor_Speed), vals=[bools, 80]
            # ============================================================
            s = await send_and_check(client, reasm,
                "A: flag=0x20 + [bools, 80]",
                bytes([0x01, 0x20, bools, 80]))
            if s == 80:
                print("  *** SUCCESS! ***")
                # Restore
                await send_and_check(client, reasm, "Restore",
                    bytes([0x01, 0x20, bools, speed]))
                return

            # ============================================================
            # TEST B: flag=0x20, vals=[80] (speed only, no bools)
            # ============================================================
            if client.is_connected:
                s = await send_and_check(client, reasm,
                    "B: flag=0x20 + [80]",
                    bytes([0x01, 0x20, 80]))
                if s == 80:
                    print("  *** SUCCESS! ***")
                    await send_and_check(client, reasm, "Restore",
                        bytes([0x01, 0x20, speed]))
                    return

            # ============================================================
            # TEST C: flag=0x21 (SwitchON+Motor_Speed), vals=[bools, 80]
            # ============================================================
            if client.is_connected:
                s = await send_and_check(client, reasm,
                    "C: flag=0x21 + [bools, 80]",
                    bytes([0x01, 0x21, bools, 80]))
                if s == 80:
                    print("  *** SUCCESS! ***")
                    await send_and_check(client, reasm, "Restore",
                        bytes([0x01, 0x21, bools, speed]))
                    return

            # ============================================================
            # TEST D: flag=0x20, vals=[bools, 50] (try 50% to be safe)
            # ============================================================
            if client.is_connected:
                s = await send_and_check(client, reasm,
                    "D: flag=0x20 + [bools, 50]",
                    bytes([0x01, 0x20, bools, 50]))
                if s == 50:
                    print("  *** SUCCESS! ***")
                    await send_and_check(client, reasm, "Restore",
                        bytes([0x01, 0x20, bools, speed]))
                    return

            # ============================================================
            # TEST E: Just speed as value (like round 3 D1/D2 worked)
            # flag=0x20, val=[speed_value]
            # Maybe only 1 value byte, not the full attr_vals layout
            # ============================================================
            if client.is_connected:
                s = await send_and_check(client, reasm,
                    "E: flag=0x20 + [50] (single value byte)",
                    bytes([0x01, 0x20, 50]))
                if s == 50:
                    print("  *** SUCCESS! ***")
                    await send_and_check(client, reasm, "Restore",
                        bytes([0x01, 0x20, speed]))
                    return

            # ============================================================
            # TEST F: 2-byte flags with bit 5
            # Maybe device expects 2 flag bytes for >8 DPs
            # ============================================================
            if client.is_connected:
                s = await send_and_check(client, reasm,
                    "F: 2B flags=[0x20,0x00] + [bools, 80]",
                    bytes([0x01, 0x20, 0x00, bools, 80]))
                if s == 80:
                    print("  *** SUCCESS! ***")
                    await send_and_check(client, reasm, "Restore",
                        bytes([0x01, 0x20, 0x00, bools, speed]))
                    return

            # ============================================================
            # TEST G: Try other flag bits for speed
            # Maybe the bit mapping is different than the DP index
            # ============================================================
            if client.is_connected:
                for bit in [3, 4, 6, 7]:
                    if not client.is_connected:
                        break
                    flag = 1 << bit
                    s = await send_and_check(client, reasm,
                        f"G: flag=0x{flag:02x} (bit {bit}) + [bools, 50]",
                        bytes([0x01, flag, bools, 50]))
                    if s == 50:
                        print(f"  *** SUCCESS! Motor_Speed is bit {bit}! ***")
                        await send_and_check(client, reasm, "Restore",
                            bytes([0x01, flag, bools, speed]))
                        return

            if client.is_connected:
                await client.stop_notify(CHAR_UUID)
            print("\n  No format changed speed.")

    except Exception as e:
        print(f"\nError: {e}")
        import traceback
        traceback.print_exc()


if __name__ == "__main__":
    asyncio.run(run())
