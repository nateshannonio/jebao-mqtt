#!/usr/bin/env python3
"""
Round 8: Capture and decode the 183-byte response.

The device sends 183-byte "0x0000" packets after our writes.
183 = action(1) + flags(9) + attr_vals(173). This might be the device
telling us the correct write format.

Also: the 36-byte ACK is unusual (was 9 bytes before). Let's decode both.

This test:
1. Reads status
2. Sends a minimal write that we know triggers the 183B response
3. Captures and hex-dumps the 183B response
4. Uses the captured format to construct the next write
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


def hexdump(data, prefix="    "):
    for i in range(0, min(len(data), 96), 16):
        chunk = data[i:i+16]
        h = ' '.join(f'{b:02x}' for b in chunk)
        a = ''.join(chr(b) if 32 <= b <= 126 else '.' for b in chunk)
        print(f"{prefix}{i:04x}: {h:<48} | {a}")
    if len(data) > 96:
        print(f"{prefix}... ({len(data)-96} more bytes)")


async def run():
    print("=" * 60)
    print("MDP - Capture & Decode Response Format")
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
            print("  OK")

            # Read status
            print("\n[2] Status...")
            before = len(reasm.complete_packets)
            sn = int(time.time())
            await client.write_gatt_char(CHAR_UUID,
                build_packet(0x93, sn.to_bytes(4, 'big') + bytes([0x02, 0x00])))
            await asyncio.sleep(3.0)

            status_pkt = None
            for pkt in reasm.complete_packets[before:]:
                if len(pkt) >= 8 and int.from_bytes(pkt[6:8], 'big') == 0x0100:
                    status_pkt = pkt
                    break
            if not status_pkt:
                print("  No status!")
                return

            p0 = status_pkt[P0_START:]
            dd = p0[DEVDATA_START:]
            print(f"  Bools=0x{dd[1]:02x} Speed={dd[2]}%")
            bools = dd[1]
            speed = dd[2]

            # ============================================================
            # SEND A WRITE and capture ALL responses in detail
            # ============================================================
            print("\n[3] Sending write to capture response format...")
            print("  Command: [0x01, bools, speed=50, feedtime=10]")

            before = len(reasm.complete_packets)
            sn = int(time.time())
            p0_write = bytes([0x01, bools, 50, 10])
            await client.write_gatt_char(CHAR_UUID,
                build_packet(0x93, sn.to_bytes(4, 'big') + p0_write))
            await asyncio.sleep(5.0)

            print(f"\n  Responses received ({len(reasm.complete_packets) - before}):")
            for i, pkt in enumerate(reasm.complete_packets[before:]):
                cmd = int.from_bytes(pkt[6:8], 'big') if len(pkt) >= 8 else 0
                print(f"\n  --- Response {i+1}: cmd=0x{cmd:04x}, {len(pkt)} bytes ---")
                hexdump(pkt)

                # Parse payload
                if len(pkt) > 8:
                    payload = pkt[8:]
                    print(f"    Payload ({len(payload)}B):")
                    hexdump(payload, prefix="      ")

                    # If this is the 36-byte ACK (cmd 0x0094)
                    if cmd == 0x0094 and len(pkt) > 12:
                        ack_sn = int.from_bytes(payload[:4], 'big')
                        ack_p0 = payload[4:]
                        print(f"    ACK sn={ack_sn}")
                        print(f"    ACK P0 ({len(ack_p0)}B): {ack_p0.hex()}")
                        if len(ack_p0) >= 2:
                            print(f"    ACK P0[0] (action?): 0x{ack_p0[0]:02x}")
                            print(f"    ACK P0[1] (bools?):  0x{ack_p0[1]:02x}")
                            if len(ack_p0) >= 3:
                                print(f"    ACK P0[2] (speed?):  {ack_p0[2]}")

            # ============================================================
            # Also read status to see current state
            # ============================================================
            if client.is_connected:
                print("\n[4] Reading status after write...")
                before2 = len(reasm.complete_packets)
                sn = int(time.time())
                await client.write_gatt_char(CHAR_UUID,
                    build_packet(0x93, sn.to_bytes(4, 'big') + bytes([0x02, 0x00])))
                await asyncio.sleep(3.0)

                for pkt in reasm.complete_packets[before2:]:
                    if len(pkt) >= 8 and int.from_bytes(pkt[6:8], 'big') == 0x0100:
                        p0 = pkt[P0_START:]
                        dd = p0[DEVDATA_START:]
                        print(f"  Bools=0x{dd[1]:02x} Speed={dd[2]}%")
                        print(f"  DevData[0:10]: {dd[:10].hex()}")
                        break

                await client.stop_notify(CHAR_UUID)

    except Exception as e:
        print(f"\nError: {e}")
        import traceback
        traceback.print_exc()


if __name__ == "__main__":
    asyncio.run(run())
