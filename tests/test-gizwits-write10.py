#!/usr/bin/env python3
"""
Round 10: Product key prefix + proper Gizwits P0

B1 from round 9 got a proper ACK when we included the product key prefix:
  payload = sn(4B) + [0x00, 0x16] + product_key(22B) + P0

This matches controlDeviceWithDid from the APK.

Now we need the correct P0 format AFTER the product key:
  P0 = action(0x01) + attr_flags(9B) + attr_vals(173B)

attr_vals = device data bytes WITHOUT the action byte (173 bytes from status response).
"""

import asyncio
import time
from bleak import BleakClient

MDP_MAC = "7725528E-75A8-F1C3-71E6-CEF9A6EDA5EE"
CHAR_UUID = "0000abf7-0000-1000-8000-00805f9b34fb"
P0_START = 12
DEVDATA_START = 25
PRODUCT_KEY = b'nBdiUnCvuxLP1SQAUmy6mq'
DID_HEADER = bytes([0x00, len(PRODUCT_KEY)]) + PRODUCT_KEY  # 24 bytes


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
            p0 = pkt[P0_START:]
            dd = p0[DEVDATA_START:]
            if len(dd) >= 6:
                return dd[1], dd[2], dd
    return None, None, None


async def send_write(client, reasm, desc, p0_after_did, use_did=True):
    """Send write with optional DID prefix. Returns new speed or None."""
    print(f"\n  [{desc}]")

    if use_did:
        full_p0 = DID_HEADER + p0_after_did
    else:
        full_p0 = p0_after_did

    print(f"    DID: {'yes' if use_did else 'no'}")
    print(f"    P0 after DID ({len(p0_after_did)}B): {p0_after_did[:20].hex()}{'...' if len(p0_after_did) > 20 else ''}")

    sn = int(time.time())
    payload = sn.to_bytes(4, 'big') + full_p0
    packet = build_packet(0x93, payload)

    before = len(reasm.complete_packets)
    await client.write_gatt_char(CHAR_UUID, packet)
    await asyncio.sleep(3.0)

    if not client.is_connected:
        print(f"    DISCONNECTED!")
        return None

    # Show responses
    for pkt in reasm.complete_packets[before:]:
        if len(pkt) >= 8:
            cmd = int.from_bytes(pkt[6:8], 'big')
            print(f"    <- 0x{cmd:04x} ({len(pkt)}B)")

    # Verify
    bools, speed, _ = await read_status(client, reasm)
    if speed is not None:
        print(f"    Result: Bools=0x{bools:02x} Speed={speed}%")
    return speed


def make_flags(*bits):
    """Make 9-byte attr_flags with given bits set"""
    f = bytearray(9)
    for b in bits:
        f[b // 8] |= (1 << (b % 8))
    return bytes(f)


async def run():
    print("=" * 60)
    print("MDP - Product Key + Gizwits P0 Format")
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

            # attr_vals = device data without action byte
            attr_vals = bytearray(devdata[1:])  # 173 bytes
            target = 50

            # ============================================================
            # A: DID + action(0x01) + 9B attr_flags + 173B attr_vals
            # Full Gizwits write format
            # ============================================================
            print("\n=== A: DID + full Gizwits P0 ===")

            # A1: flags bit 5 (Motor_Speed), speed=50
            mod_vals = bytearray(attr_vals)
            mod_vals[1] = target  # byte 1 = Motor_Speed
            p0 = bytes([0x01]) + make_flags(5) + bytes(mod_vals)
            s = await send_write(client, reasm,
                f"A1: DID + 0x01 + flags(bit5) + vals ({len(p0)}B)", p0)
            if s == target:
                print("    *** SUCCESS! ***")
                # Restore
                mod_vals[1] = speed
                p0r = bytes([0x01]) + make_flags(5) + bytes(mod_vals)
                await send_write(client, reasm, "Restore", p0r)
                return

            # A2: flags bits 0+5 (SwitchON + Motor_Speed)
            if client.is_connected:
                mod_vals = bytearray(attr_vals)
                mod_vals[1] = target
                p0 = bytes([0x01]) + make_flags(0, 5) + bytes(mod_vals)
                s = await send_write(client, reasm,
                    f"A2: DID + flags(bit0+5) + vals ({len(p0)}B)", p0)
                if s == target:
                    print("    *** SUCCESS! ***")
                    return

            # A3: flags=all_ff (write everything)
            if client.is_connected:
                mod_vals = bytearray(attr_vals)
                mod_vals[1] = target
                p0 = bytes([0x01]) + bytes([0xFF] * 9) + bytes(mod_vals)
                s = await send_write(client, reasm,
                    f"A3: DID + flags=0xFF*9 + vals ({len(p0)}B)", p0)
                if s == target:
                    print("    *** SUCCESS! ***")
                    return

            # ============================================================
            # B: DID + just device data with action=0x01 (no flags)
            # Maybe the Gizwits "compact" format without flags
            # ============================================================
            if client.is_connected:
                print("\n=== B: DID + device data (no flags) ===")

                # B1: Full devdata with action=0x01
                mod_dd = bytearray(devdata)
                mod_dd[0] = 0x01
                mod_dd[2] = target
                s = await send_write(client, reasm,
                    f"B1: DID + full devdata action=0x01 ({len(mod_dd)}B)", bytes(mod_dd))
                if s == target:
                    print("    *** SUCCESS! ***")
                    return

                # B2: Short devdata [0x01, bools, speed, feedtime, autogears, autofeedtime]
                if client.is_connected:
                    p0 = bytes([0x01, bools, target, devdata[3], devdata[4], devdata[5]])
                    s = await send_write(client, reasm,
                        f"B2: DID + short devdata ({len(p0)}B)", p0)
                    if s == target:
                        print("    *** SUCCESS! ***")
                        return

            # ============================================================
            # C: DID + action + attr_vals WITHOUT flags
            # Maybe: action(0x01) + attr_vals(173B)
            # ============================================================
            if client.is_connected:
                print("\n=== C: DID + action + attr_vals (no flags) ===")
                mod_vals = bytearray(attr_vals)
                mod_vals[1] = target
                p0 = bytes([0x01]) + bytes(mod_vals)
                s = await send_write(client, reasm,
                    f"C1: DID + 0x01 + attr_vals ({len(p0)}B)", p0)
                if s == target:
                    print("    *** SUCCESS! ***")
                    return

            # ============================================================
            # D: WITHOUT DID but with 9-byte flags (for comparison)
            # ============================================================
            if client.is_connected:
                print("\n=== D: No DID, 9B flags ===")
                mod_vals = bytearray(attr_vals)
                mod_vals[1] = target
                p0 = bytes([0x01]) + make_flags(5) + bytes(mod_vals)
                s = await send_write(client, reasm,
                    f"D1: NO DID + flags(bit5) + vals ({len(p0)}B)", p0, use_did=False)
                if s == target:
                    print("    *** SUCCESS! ***")
                    return

            if client.is_connected:
                bools, speed, _ = await read_status(client, reasm)
                print(f"\n  Final: Bools=0x{bools:02x} Speed={speed}%")
                await client.stop_notify(CHAR_UUID)

            print("\n  No format changed speed.")

    except Exception as e:
        print(f"\nError: {e}")
        import traceback
        traceback.print_exc()


if __name__ == "__main__":
    asyncio.run(run())
