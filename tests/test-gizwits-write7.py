#!/usr/bin/env python3
"""
Round 7: CORRECT format discovered!

Round 6 test A proved the write format has NO attr_flags.
It mirrors the read format exactly:

  Read response:  [0x03, bools, speed, feedtime, autogears, autofeedtime, ...]
  Write command:  [0x01, bools, speed, feedtime, autogears, autofeedtime, ...]

In test A, P0=[0x01, 0x20, 0x21, 0x50] was interpreted as:
  action=0x01, bools=0x20 (SwitchON OFF!), speed=0x21=33→30, feedtime=0x50=80

Byte layout (from APK schema):
  [0] action:      0x01 (write) / 0x03 (status report)
  [1] bools:       bit0=SwitchON, bit1=Mode, bit2=FeedSwitch, bit3=TimerON, bit4-5=AutoMode
  [2] Motor_Speed: uint8 (30-100)
  [3] FeedTime:    uint8
  [4] AutoGears:   uint8
  [5] AutoFeedTime: uint8
  [6-9] YMDData
  [10-13] HMSData
  ...

This test: send [0x01, current_bools, target_speed] to change speed
while preserving all current state.
"""

import asyncio
import time
from bleak import BleakClient

MDP_MAC = "7725528E-75A8-F1C3-71E6-CEF9A6EDA5EE"
CHAR_UUID = "0000abf7-0000-1000-8000-00805f9b34fb"
P0_START = 12
DEVDATA_START = 25


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
    """Returns (bools, speed, feedtime, autogears, full_devdata) or Nones"""
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
                return dd[1], dd[2], dd[3], dd[4], dd
    return None, None, None, None, None


async def send_write(client, reasm, p0_data, desc=""):
    """Send write command, return (bools, speed) after verification"""
    print(f"\n  [{desc}]")
    print(f"    P0: {p0_data.hex()} ({len(p0_data)}B)")

    sn = int(time.time())
    payload = sn.to_bytes(4, 'big') + p0_data
    await client.write_gatt_char(CHAR_UUID, build_packet(0x93, payload))
    await asyncio.sleep(2.0)

    if not client.is_connected:
        print(f"    DISCONNECTED!")
        return None, None

    bools, speed, _, _, _ = await read_status(client, reasm)
    if speed is not None:
        print(f"    Result: Bools=0x{bools:02x} Speed={speed}%")
    return bools, speed


async def run():
    print("=" * 60)
    print("MDP Control - Direct Write (no attr_flags)")
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
            bools, speed, feedtime, autogears, devdata = await read_status(client, reasm)
            if speed is None:
                print("  No status!")
                return
            print(f"  Bools=0x{bools:02x} Speed={speed}% FeedTime={feedtime} AutoGears={autogears}")
            print(f"    SwitchON={bool(bools&1)} FeedSwitch={bool(bools&4)} AutoMode={(bools>>4)&3}")

            # 3 bytes disconnects (round 7), 4 bytes worked in round 6.
            # Round 6 A: [0x01, 0x20, 0x21, 0x50] → changed state
            # So test with 4+ bytes only, starting with safest formats.

            target = 80
            success = False

            # ============================================================
            # TEST 1: [action, bools, speed, feedtime] - 4 bytes
            # ============================================================
            b, s = await send_write(client, reasm,
                bytes([0x01, bools, target, feedtime]),
                f"4B: [0x01, bools=0x{bools:02x}, speed={target}, ft={feedtime}]")
            if s == target:
                print("    *** SUCCESS! ***")
                success = True

            # ============================================================
            # TEST 2: [action, bools, speed, feedtime, autogears, autofeedtime] - 6 bytes
            # ============================================================
            if client.is_connected and not success:
                b, s = await send_write(client, reasm,
                    bytes([0x01, bools, target, feedtime, autogears, devdata[5]]),
                    f"6B: preserve all fields, speed={target}")
                if s == target:
                    print("    *** SUCCESS! ***")
                    success = True

            # ============================================================
            # TEST 3: Full devdata echo with action=0x01 and speed changed
            # ============================================================
            if client.is_connected and not success:
                mod_dd = bytearray(devdata)
                mod_dd[0] = 0x01
                mod_dd[2] = target
                b, s = await send_write(client, reasm,
                    bytes(mod_dd),
                    f"Full devdata ({len(mod_dd)}B), speed={target}")
                if s == target:
                    print("    *** SUCCESS! ***")
                    success = True

            # ============================================================
            # TEST 4: Maybe there IS attr_flags but it's always needed
            # [action, flags=0x20, bools, speed, feedtime] - 5 bytes
            # ============================================================
            if client.is_connected and not success:
                b, s = await send_write(client, reasm,
                    bytes([0x01, 0x20, bools, target, feedtime]),
                    f"5B: flags=0x20 + bools + speed={target} + ft")
                if s == target:
                    print("    *** SUCCESS! ***")
                    success = True

            # ============================================================
            # TEST 5: flags=0x21 (SwitchON+Motor_Speed), bools, speed, feedtime
            # ============================================================
            if client.is_connected and not success:
                b, s = await send_write(client, reasm,
                    bytes([0x01, 0x21, bools, target, feedtime]),
                    f"5B: flags=0x21 + bools + speed={target} + ft")
                if s == target:
                    print("    *** SUCCESS! ***")
                    success = True

            # ============================================================
            # TEST 6: Try speed=50 in case 80 is the issue
            # ============================================================
            if client.is_connected and not success:
                b, s = await send_write(client, reasm,
                    bytes([0x01, bools, 50, feedtime]),
                    f"4B: speed=50")
                if s == 50:
                    print("    *** SUCCESS with 50! ***")
                    success = True
                    target = 50

            # ============================================================
            # RESTORE if we changed anything
            # ============================================================
            if client.is_connected and success and s != speed:
                print(f"\n  Restoring speed to {speed}%...")
                await send_write(client, reasm,
                    bytes([0x01, bools, speed, feedtime]),
                    f"Restore to {speed}%")

            if client.is_connected:
                await client.stop_notify(CHAR_UUID)

            # Final assessment
            print("\n" + "=" * 60)
            if s is not None and s in [80, 50]:
                print("SPEED CONTROL WORKING!")
            else:
                print("Speed didn't change to target value.")

    except Exception as e:
        print(f"\nError: {e}")
        import traceback
        traceback.print_exc()


if __name__ == "__main__":
    asyncio.run(run())
