#!/usr/bin/env python3
"""
Gizwits P0 Write Test - Round 5 (DEFINITIVE)

From APK decompilation we now have the EXACT data point schema:

P0 attr_vals byte layout:
  Byte 0 (packed bools + enum):
    bit 0: SwitchON (DP 0)
    bit 1: Mode (DP 1)
    bit 2: FeedSwitch (DP 2)
    bit 3: TimerON (DP 3)
    bits 4-5: AutoMode (DP 4, 2-bit enum)
  Byte 1: Motor_Speed (DP 5, uint8, 0-100)
  Byte 2: FeedTime (DP 6, uint8)
  Byte 3: AutoGears (DP 7, uint8)
  Byte 4: AutoFeedTime (DP 8, uint8)
  Bytes 5-8: YMDData (DP 9, 4 bytes)
  Bytes 9-12: HMSData (DP 10, 4 bytes)
  Bytes 13+: AutoTime00-47 (6 bytes each)
  Byte 301: Fault flags (DPs 59-65)

attr_flags: 1 bit per data point (66 DPs = 9 bytes)
  bit 0 = SwitchON
  bit 1 = Mode
  bit 2 = FeedSwitch
  bit 3 = TimerON
  bit 4 = AutoMode
  bit 5 = Motor_Speed  <-- THIS IS WHAT WE NEED
  bit 6 = FeedTime
  bit 7 = AutoGears
  ...

Write format: action(0x01) + attr_flags(9 bytes) + attr_vals(302 bytes)

For setting speed, we need:
  attr_flags = [0x20, 0,0,0,0,0,0,0,0]  (bit 5 = Motor_Speed)
  attr_vals = [current_bools, speed, 0,0,...] (speed at byte 1)
"""

import asyncio
import time
from bleak import BleakClient

MDP_MAC = "7725528E-75A8-F1C3-71E6-CEF9A6EDA5EE"
CHAR_UUID = "0000abf7-0000-1000-8000-00805f9b34fb"

# Data point bit positions in attr_flags
DP_SWITCHON = 0
DP_MODE = 1
DP_FEEDSWITCH = 2
DP_TIMERON = 3
DP_AUTOMODE = 4
DP_MOTOR_SPEED = 5
DP_FEEDTIME = 6
DP_AUTOGEARS = 7

# Byte positions in attr_vals
BYTE_BOOLS = 0       # Packed bools + enum
BYTE_SPEED = 1       # Motor_Speed
BYTE_FEEDTIME = 2    # FeedTime
BYTE_AUTOGEARS = 3   # AutoGears

NUM_FLAG_BYTES = 9    # ceil(66/8)
TOTAL_ATTRVALS = 302  # Full attr_vals size

# Status response positions
P0_START = 12         # P0 starts at byte 12 of response packet
DEVDATA_START = 25    # Device data starts at P0[25]
SPEED_POS = 27        # Speed at P0[27] = devdata[2] = action(1) + bools(1) + speed


def encode_length(n: int) -> bytes:
    """Gizwits variable-length encoding (from APK getLength method)"""
    if n < 128:
        return bytes([n])
    remainder = n % 128
    return bytes([remainder + 128]) + encode_length((n - remainder) // 128)


def build_packet(cmd: int, payload: bytes) -> bytes:
    # length covers: flag(1) + cmd(2) + payload
    length = 3 + len(payload)
    length_bytes = encode_length(length)
    return bytes([0x00, 0x00, 0x00, 0x03]) + length_bytes + bytes([0x00]) + cmd.to_bytes(2, 'big') + payload


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


def make_attr_flags(*dp_bits):
    """Create 9-byte attr_flags with specified data point bits set"""
    flags = bytearray(NUM_FLAG_BYTES)
    for bit in dp_bits:
        flags[bit // 8] |= (1 << (bit % 8))
    return bytes(flags)


def make_attr_vals(bool_byte=0x01, speed=50, feedtime=0, autogears=0, autofeedtime=0):
    """Create attr_vals with specified values, rest zeroed"""
    vals = bytearray(TOTAL_ATTRVALS)
    vals[BYTE_BOOLS] = bool_byte
    vals[BYTE_SPEED] = speed
    vals[BYTE_FEEDTIME] = feedtime
    vals[BYTE_AUTOGEARS] = autogears
    return bytes(vals)


async def run():
    print("=" * 60)
    print("DEFINITIVE MDP Control Test (from APK schema)")
    print("=" * 60)

    reassembler = PacketReassembler()

    def handler(sender, data):
        completed = reassembler.feed(data)
        for pkt in completed:
            if len(pkt) >= 8:
                cmd = int.from_bytes(pkt[6:8], 'big')
                tags = {0x0094: "ACK", 0x0100: "STATUS", 0x0007: "PASS",
                        0x0009: "LOGIN", 0x0062: "DEV"}
                print(f"  <- {tags.get(cmd, f'0x{cmd:04x}')} ({len(pkt)}B)")

    try:
        async with BleakClient(MDP_MAC) as client:
            await client.start_notify(CHAR_UUID, handler)

            # Auth
            print("[1] Auth...")
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
            print("  OK")

            # Read status
            print("\n[2] Reading status...")
            before = len(reassembler.complete_packets)
            sn = int(time.time())
            await client.write_gatt_char(CHAR_UUID,
                build_packet(0x93, sn.to_bytes(4, 'big') + bytes([0x02, 0x00])))
            await asyncio.sleep(3.0)

            status = None
            for pkt in reassembler.complete_packets[before:]:
                if len(pkt) >= 8 and int.from_bytes(pkt[6:8], 'big') == 0x0100:
                    status = pkt
                    break

            if not status or len(status) < P0_START + SPEED_POS + 1:
                print("  No status!")
                return

            p0 = status[P0_START:]
            devdata = p0[DEVDATA_START:]
            current_action = devdata[0]
            current_bools = devdata[1]
            current_speed = devdata[2]  # = p0[27]

            print(f"  Action: 0x{current_action:02x}")
            print(f"  Bools:  0x{current_bools:02x} = {current_bools:08b}")
            print(f"    SwitchON:   {bool(current_bools & 0x01)}")
            print(f"    Mode:       {bool(current_bools & 0x02)}")
            print(f"    FeedSwitch: {bool(current_bools & 0x04)}")
            print(f"    TimerON:    {bool(current_bools & 0x08)}")
            print(f"    AutoMode:   {(current_bools >> 4) & 0x03}")
            print(f"  Speed:  {current_speed}%")
            print(f"  FeedTime: {devdata[3]}")
            print(f"  AutoGears: {devdata[4]}")

            # ============================================================
            # TEST: Set Motor_Speed using the correct schema
            # ============================================================
            print("\n[3] Setting Motor_Speed to 80%...")

            # attr_flags: bit 5 (Motor_Speed) set
            flags = make_attr_flags(DP_MOTOR_SPEED)
            # attr_vals: keep current bools, set speed to 80
            vals = make_attr_vals(bool_byte=current_bools, speed=80)
            # P0 = action(0x01) + flags(9B) + vals(302B)
            p0_write = bytes([0x01]) + flags + vals

            sn = int(time.time())
            payload = sn.to_bytes(4, 'big') + p0_write
            packet = build_packet(0x93, payload)

            print(f"  P0: action=0x01 flags={flags.hex()} vals[0:5]={vals[:5].hex()}")
            print(f"  Total P0 size: {len(p0_write)}B")
            await client.write_gatt_char(CHAR_UUID, packet)
            await asyncio.sleep(2.0)

            if not client.is_connected:
                print("  DISCONNECTED!")
                return

            # Verify
            print("  Verifying...")
            new_speed = -1
            before = len(reassembler.complete_packets)
            sn = int(time.time())
            await client.write_gatt_char(CHAR_UUID,
                build_packet(0x93, sn.to_bytes(4, 'big') + bytes([0x02, 0x00])))
            await asyncio.sleep(3.0)

            for pkt in reassembler.complete_packets[before:]:
                if len(pkt) >= 8 and int.from_bytes(pkt[6:8], 'big') == 0x0100:
                    new_speed = pkt[P0_START + SPEED_POS]
                    new_bools = pkt[P0_START + DEVDATA_START + 1]
                    if new_speed == 80:
                        print(f"  *** SUCCESS! Speed = {new_speed}% ***")
                    else:
                        print(f"  Speed = {new_speed}% (expected 80)")
                    print(f"  Bools = 0x{new_bools:02x}")
                    break

            # ============================================================
            # TEST: Minimal attr_vals (just 5 bytes instead of 302)
            # ============================================================
            if client.is_connected and new_speed != 80:
                print("\n[3b] Retry with minimal attr_vals (5 bytes)...")
                flags = make_attr_flags(DP_MOTOR_SPEED)
                # Just send bytes 0-4 of attr_vals (bools + speed + feedtime + autogears + autofeedtime)
                short_vals = bytes([current_bools, 80, devdata[3], devdata[4], devdata[5]])
                p0_write = bytes([0x01]) + flags + short_vals

                sn = int(time.time())
                await client.write_gatt_char(CHAR_UUID,
                    build_packet(0x93, sn.to_bytes(4, 'big') + p0_write))
                await asyncio.sleep(2.0)

                if client.is_connected:
                    before = len(reassembler.complete_packets)
                    sn = int(time.time())
                    await client.write_gatt_char(CHAR_UUID,
                        build_packet(0x93, sn.to_bytes(4, 'big') + bytes([0x02, 0x00])))
                    await asyncio.sleep(3.0)
                    for pkt in reassembler.complete_packets[before:]:
                        if len(pkt) >= 8 and int.from_bytes(pkt[6:8], 'big') == 0x0100:
                            s = pkt[P0_START + SPEED_POS]
                            print(f"  Speed={s}% (target 80)")
                            if s == 80:
                                print(f"  *** SUCCESS with minimal attr_vals! ***")
                            break
                else:
                    print("  DISCONNECTED with minimal")

            # ============================================================
            # TEST: Even more minimal - just 2 bytes (bools + speed)
            # ============================================================
            if client.is_connected and new_speed != 80:
                print("\n[3c] Retry with 2-byte attr_vals...")
                flags = make_attr_flags(DP_MOTOR_SPEED)
                p0_write = bytes([0x01]) + flags + bytes([current_bools, 80])

                sn = int(time.time())
                await client.write_gatt_char(CHAR_UUID,
                    build_packet(0x93, sn.to_bytes(4, 'big') + p0_write))
                await asyncio.sleep(2.0)

                if client.is_connected:
                    before = len(reassembler.complete_packets)
                    sn = int(time.time())
                    await client.write_gatt_char(CHAR_UUID,
                        build_packet(0x93, sn.to_bytes(4, 'big') + bytes([0x02, 0x00])))
                    await asyncio.sleep(3.0)
                    for pkt in reassembler.complete_packets[before:]:
                        if len(pkt) >= 8 and int.from_bytes(pkt[6:8], 'big') == 0x0100:
                            s = pkt[P0_START + SPEED_POS]
                            print(f"  Speed={s}% (target 80)")
                            if s == 80:
                                print(f"  *** SUCCESS with 2-byte attr_vals! ***")
                            break

            # ============================================================
            # TEST: Power ON + Speed 50
            # ============================================================
            if client.is_connected:
                print("\n[4] Power ON + Speed 50%...")
                flags = make_attr_flags(DP_SWITCHON, DP_MOTOR_SPEED)
                vals = make_attr_vals(bool_byte=0x01, speed=50)  # SwitchON=1
                p0_write = bytes([0x01]) + flags + vals

                sn = int(time.time())
                await client.write_gatt_char(CHAR_UUID,
                    build_packet(0x93, sn.to_bytes(4, 'big') + p0_write))
                await asyncio.sleep(2.0)

                if client.is_connected:
                    before = len(reassembler.complete_packets)
                    sn = int(time.time())
                    await client.write_gatt_char(CHAR_UUID,
                        build_packet(0x93, sn.to_bytes(4, 'big') + bytes([0x02, 0x00])))
                    await asyncio.sleep(3.0)
                    for pkt in reassembler.complete_packets[before:]:
                        if len(pkt) >= 8 and int.from_bytes(pkt[6:8], 'big') == 0x0100:
                            s = pkt[P0_START + SPEED_POS]
                            b = pkt[P0_START + DEVDATA_START + 1]
                            print(f"  Speed={s}%, Bools=0x{b:02x}, SwitchON={bool(b&1)}")
                            break

            # ============================================================
            # RESTORE: Set back to original speed
            # ============================================================
            if client.is_connected and current_speed > 0:
                print(f"\n[5] Restoring speed to {current_speed}%...")
                flags = make_attr_flags(DP_SWITCHON, DP_MOTOR_SPEED)
                vals = make_attr_vals(bool_byte=current_bools, speed=current_speed)
                p0_write = bytes([0x01]) + flags + vals

                sn = int(time.time())
                await client.write_gatt_char(CHAR_UUID,
                    build_packet(0x93, sn.to_bytes(4, 'big') + p0_write))
                await asyncio.sleep(2.0)

                if client.is_connected:
                    before = len(reassembler.complete_packets)
                    sn = int(time.time())
                    await client.write_gatt_char(CHAR_UUID,
                        build_packet(0x93, sn.to_bytes(4, 'big') + bytes([0x02, 0x00])))
                    await asyncio.sleep(3.0)
                    for pkt in reassembler.complete_packets[before:]:
                        if len(pkt) >= 8 and int.from_bytes(pkt[6:8], 'big') == 0x0100:
                            s = pkt[P0_START + SPEED_POS]
                            print(f"  Restored to {s}%")
                            break

            if client.is_connected:
                await client.stop_notify(CHAR_UUID)

    except Exception as e:
        print(f"\nError: {e}")
        import traceback
        traceback.print_exc()


if __name__ == "__main__":
    asyncio.run(run())
