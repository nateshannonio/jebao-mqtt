#!/usr/bin/env python3
"""
Round 9: Key findings from response analysis

36-byte ACK has flag byte = 0x01 (position 5 in packet)
183-byte response has flag byte = 0x02
Our writes always used flag byte = 0x00

Also: 183B payload starts with [0x91, 0x04, 0x11, 0x4B, ...]
  0x04 = Gizwits action "device status push"
  0x11 = current bools, 0x4B = current speed (75%)
  So this is the device reporting its state AFTER our write (unchanged)

The 0x91 might be a sequence/flag byte within the payload.

THEORY: The outer packet flag byte matters!
  flag=0x00: normal/read
  flag=0x01: write?

This test tries writes with flag=0x01 in the outer packet header.
"""

import asyncio
import time
from bleak import BleakClient

MDP_MAC = "7725528E-75A8-F1C3-71E6-CEF9A6EDA5EE"
CHAR_UUID = "0000abf7-0000-1000-8000-00805f9b34fb"
P0_START = 12
DEVDATA_START = 25


def build_packet(cmd: int, payload: bytes, flags: int = 0x00) -> bytes:
    length = 3 + len(payload)
    return bytes([0x00, 0x00, 0x00, 0x03, length, flags]) + cmd.to_bytes(2, 'big') + payload


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


def hexdump(data, prefix="    ", max_bytes=64):
    for i in range(0, min(len(data), max_bytes), 16):
        chunk = data[i:i+16]
        h = ' '.join(f'{b:02x}' for b in chunk)
        a = ''.join(chr(b) if 32 <= b <= 126 else '.' for b in chunk)
        print(f"{prefix}{i:04x}: {h:<48} | {a}")


async def read_status(client, reasm):
    before = len(reasm.complete_packets)
    sn = int(time.time())
    await client.write_gatt_char(CHAR_UUID,
        build_packet(0x93, sn.to_bytes(4, 'big') + bytes([0x02, 0x00])))
    await asyncio.sleep(3.0)
    for pkt in reasm.complete_packets[before:]:
        if len(pkt) >= 8 and int.from_bytes(pkt[6:8], 'big') == 0x0100:
            p0 = pkt[P0_START:]
            dd = p0[DEVDATA_START:]
            if len(dd) >= 6:
                return dd[1], dd[2], dd  # bools, speed, full devdata
    return None, None, None


async def send_and_check(client, reasm, desc, cmd_code, p0, pkt_flags=0x00):
    print(f"\n  [{desc}]")
    print(f"    cmd=0x{cmd_code:04x} pkt_flags=0x{pkt_flags:02x}")
    print(f"    P0 ({len(p0)}B): {p0[:16].hex()}{'...' if len(p0) > 16 else ''}")

    sn = int(time.time())
    payload = sn.to_bytes(4, 'big') + p0
    packet = build_packet(cmd_code, payload, flags=pkt_flags)

    before = len(reasm.complete_packets)
    await client.write_gatt_char(CHAR_UUID, packet)
    await asyncio.sleep(3.0)

    if not client.is_connected:
        print(f"    DISCONNECTED!")
        return None

    # Show all responses
    for pkt in reasm.complete_packets[before:]:
        if len(pkt) >= 8:
            cmd = int.from_bytes(pkt[6:8], 'big')
            print(f"    <- cmd=0x{cmd:04x} ({len(pkt)}B) flags=0x{pkt[5]:02x}")

    # Verify speed
    bools, speed, _ = await read_status(client, reasm)
    if speed is not None:
        print(f"    Verify: Bools=0x{bools:02x} Speed={speed}%")
    return speed


async def run():
    print("=" * 60)
    print("MDP - Flag Byte & Format Testing")
    print("=" * 60)

    reasm = PacketReassembler()
    def handler(sender, data):
        reasm.feed(data)

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

            # Status
            print("\n[2] Status...")
            bools, speed, devdata = await read_status(client, reasm)
            if speed is None:
                print("  No status!")
                return
            print(f"  Bools=0x{bools:02x} Speed={speed}%")

            target = 50

            # ============================================================
            # Group A: flag=0x01 in outer packet (matching ACK format)
            # ============================================================
            print("\n=== Group A: Outer packet flag=0x01 ===")

            # A1: flag=0x01, simple [action, bools, speed, feedtime]
            s = await send_and_check(client, reasm,
                "A1: pkt_flag=0x01, P0=[0x01, bools, 50, ft]",
                0x93, bytes([0x01, bools, target, devdata[3]]), pkt_flags=0x01)
            if s == target:
                print("    *** SUCCESS! ***")
                await send_and_check(client, reasm, "Restore", 0x93,
                    bytes([0x01, bools, speed, devdata[3]]), pkt_flags=0x01)
                return

            # A2: flag=0x01, 6 bytes
            if client.is_connected:
                s = await send_and_check(client, reasm,
                    "A2: pkt_flag=0x01, 6B",
                    0x93, bytes([0x01, bools, target, devdata[3], devdata[4], devdata[5]]),
                    pkt_flags=0x01)
                if s == target:
                    print("    *** SUCCESS! ***")
                    return

            # A3: flag=0x01, full devdata
            if client.is_connected:
                mod = bytearray(devdata)
                mod[0] = 0x01
                mod[2] = target
                s = await send_and_check(client, reasm,
                    f"A3: pkt_flag=0x01, full devdata ({len(mod)}B)",
                    0x93, bytes(mod), pkt_flags=0x01)
                if s == target:
                    print("    *** SUCCESS! ***")
                    return

            # ============================================================
            # Group B: Include product key in P0 (like the ACK does)
            # The ACK payload has: sn + [0x00, 0x16, product_key(22B)]
            # Maybe writes need the product key prefix too?
            # ============================================================
            if client.is_connected:
                print("\n=== Group B: Include product key prefix ===")
                product_key = b'nBdiUnCvuxLP1SQAUmy6mq'
                pk_prefix = bytes([0x00, 0x16]) + product_key  # 24 bytes

                # B1: prefix + [action, bools, speed, feedtime]
                p0 = pk_prefix + bytes([0x01, bools, target, devdata[3]])
                s = await send_and_check(client, reasm,
                    "B1: product_key + [0x01, bools, 50, ft]",
                    0x93, p0)
                if s == target:
                    print("    *** SUCCESS! ***")
                    return

                # B2: prefix + full devdata (action=0x01)
                if client.is_connected:
                    mod = bytearray(devdata)
                    mod[0] = 0x01
                    mod[2] = target
                    p0 = pk_prefix + bytes(mod)
                    s = await send_and_check(client, reasm,
                        f"B2: product_key + full devdata ({len(p0)}B)",
                        0x93, p0)
                    if s == target:
                        print("    *** SUCCESS! ***")
                        return

                # B3: with pkt_flag=0x01
                if client.is_connected:
                    p0 = pk_prefix + bytes([0x01, bools, target, devdata[3]])
                    s = await send_and_check(client, reasm,
                        "B3: pkt_flag=0x01 + product_key + P0",
                        0x93, p0, pkt_flags=0x01)
                    if s == target:
                        print("    *** SUCCESS! ***")
                        return

            # ============================================================
            # Group C: The 183B response starts with [0x91, 0x04, ...]
            # Maybe 0x91 is relevant. Also try action=0x04
            # ============================================================
            if client.is_connected:
                print("\n=== Group C: Alternative action bytes ===")

                for action in [0x04, 0x05, 0x91]:
                    if not client.is_connected:
                        break
                    p0 = bytes([action, bools, target, devdata[3]])
                    s = await send_and_check(client, reasm,
                        f"C: action=0x{action:02x}, [bools, 50, ft]",
                        0x93, p0)
                    if s == target:
                        print(f"    *** SUCCESS with action=0x{action:02x}! ***")
                        return

            # ============================================================
            # Group D: cmd 0x0090 with flag=0x01
            # ============================================================
            if client.is_connected:
                print("\n=== Group D: cmd 0x0090 with flag=0x01 ===")
                p0 = bytes([0x01, bools, target, devdata[3]])
                s = await send_and_check(client, reasm,
                    "D1: 0x0090 flag=0x01",
                    0x0090, p0, pkt_flags=0x01)
                if s == target:
                    print("    *** SUCCESS! ***")
                    return

            # ============================================================
            # Group E: Maybe the DID (device ID) format is required
            # controlDeviceWithDid: sn + [0x00, did_len] + did + p0
            # The product key might BE the DID
            # ============================================================
            if client.is_connected:
                print("\n=== Group E: With DID prefix (controlDeviceWithDid format) ===")
                did = product_key  # 22 bytes
                did_header = bytes([0x00, len(did)]) + did
                p0_data = bytes([0x01, bools, target, devdata[3]])

                # The APK builds: sn + [0x00, did_len] + did + p0
                # But sn is already added by send_and_check, so we just prepend did_header to p0
                combined = did_header + p0_data
                s = await send_and_check(client, reasm,
                    f"E1: DID + P0 ({len(combined)}B)",
                    0x93, combined)
                if s == target:
                    print("    *** SUCCESS! ***")
                    return

                # E2: with flag=0x01
                if client.is_connected:
                    s = await send_and_check(client, reasm,
                        f"E2: DID + P0, flag=0x01",
                        0x93, combined, pkt_flags=0x01)
                    if s == target:
                        print("    *** SUCCESS! ***")
                        return

            if client.is_connected:
                # Final status
                bools, speed, _ = await read_status(client, reasm)
                if speed is not None:
                    print(f"\n  Final: Bools=0x{bools:02x} Speed={speed}%")
                await client.stop_notify(CHAR_UUID)

            print("\n" + "=" * 60)
            print("No format changed speed.")

    except Exception as e:
        print(f"\nError: {e}")
        import traceback
        traceback.print_exc()


if __name__ == "__main__":
    asyncio.run(run())
