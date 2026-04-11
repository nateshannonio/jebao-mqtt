#!/usr/bin/env python3
"""
Gizwits P0 Write Test - Round 2

Round 1 findings:
- Status response (cmd 0x0100) is 211 bytes, P0 is 199 bytes
- P0 has a product key prefix: [0xd1, 0x00, 0x16, <22-byte key>, <device data...>]
- Product key: "nBdiUnCvuxLP1SQAUmy6mq" (22 bytes at P0[3:25])
- Device data starts at P0[25], speed is at P0[27] (offset 2 in device data)
- All round 1 formats sent the full P0 including product key - all got ACKed but no effect
- cmd 0x0093 with action 0x01 does NOT control the pump

Round 2 theories:
1. Write should use only the device data portion (strip product key prefix)
2. Write might use cmd 0x0090 (WiFi equivalent) instead of 0x0093
3. Write might go to a different BLE characteristic
4. The device data area has its own internal structure we need to match
5. Maybe cmd 0x0062 (received after login) hints at a different protocol
"""

import asyncio
import time
from bleak import BleakClient

MDP_MAC = "7725528E-75A8-F1C3-71E6-CEF9A6EDA5EE"
SERVICE_UUID = "0000abf0-0000-1000-8000-00805f9b34fb"
CHAR_UUID = "0000abf7-0000-1000-8000-00805f9b34fb"

TARGET_SPEED = 55
SPEED_POS_IN_P0 = 27  # Position within the full P0
DEVICE_DATA_START = 25  # Where actual device data begins (after product key)
SPEED_POS_IN_DEVDATA = 2  # Position within device data section


def build_packet(cmd: int, payload: bytes) -> bytes:
    """Build Gizwits BLE packet"""
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
                length_field = data[4]
                self.expected_len = 5 + length_field
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


def hexdump(data: bytes, prefix: str = "  ", max_bytes: int = 80):
    for i in range(0, min(len(data), max_bytes), 16):
        chunk = data[i:i+16]
        hex_str = ' '.join(f'{b:02x}' for b in chunk)
        ascii_str = ''.join(chr(b) if 32 <= b <= 126 else '.' for b in chunk)
        print(f"{prefix}{i:04x}: {hex_str:<48} | {ascii_str}")
    if len(data) > max_bytes:
        print(f"{prefix}... ({len(data) - max_bytes} more bytes)")


async def run_tests():
    print("=" * 70)
    print("Gizwits P0 Write Test - Round 2")
    print("=" * 70)
    print(f"Target speed: {TARGET_SPEED}%")
    print()

    reassembler = PacketReassembler()
    responses = []
    all_chars = []  # Store discovered characteristics

    def handler(sender, data):
        responses.append(data)
        completed = reassembler.feed(data)
        for pkt in completed:
            if len(pkt) >= 8:
                cmd = int.from_bytes(pkt[6:8], 'big')
                if cmd == 0x0094:
                    print(f"    <- ACK")
                elif cmd == 0x0100:
                    print(f"    <- Status (0x0100), {len(pkt)}B")
                elif cmd == 0x0091:
                    print(f"    <- ACK (0x0091 - WiFi-style)")
                else:
                    print(f"    <- CMD 0x{cmd:04x}, {len(pkt)}B")

    try:
        async with BleakClient(MDP_MAC) as client:
            # ============================================================
            # Phase 0: Enumerate all services and characteristics
            # ============================================================
            print("[0] Enumerating BLE services and characteristics...")
            for service in client.services:
                print(f"  Service: {service.uuid}")
                for char in service.characteristics:
                    props = ', '.join(char.properties)
                    print(f"    Char: {char.uuid} [{props}]")
                    all_chars.append((service.uuid, char.uuid, char.properties))
                    for desc in char.descriptors:
                        print(f"      Desc: {desc.uuid}")

            # ============================================================
            # Phase 1: Connect, authenticate, read status
            # ============================================================
            print(f"\n[1] Authenticating...")
            await client.start_notify(CHAR_UUID, handler)

            # Get passcode
            await client.write_gatt_char(CHAR_UUID, build_packet(0x06, b''))
            await asyncio.sleep(0.5)

            if not responses:
                print("  No passcode response!")
                return

            passcode = None
            for pkt in reassembler.complete_packets:
                if len(pkt) >= 8 and int.from_bytes(pkt[6:8], 'big') == 0x0007:
                    passcode = pkt[8:]
                    break

            if not passcode:
                print("  No passcode found!")
                return

            print(f"  Passcode: {passcode.hex()}")
            await client.write_gatt_char(CHAR_UUID, build_packet(0x08, passcode))
            await asyncio.sleep(1.0)
            print("  Authenticated")

            # Read status
            print(f"\n[2] Reading status...")
            before = len(reassembler.complete_packets)
            cmd_sn = int(time.time())
            await client.write_gatt_char(CHAR_UUID,
                build_packet(0x93, cmd_sn.to_bytes(4, 'big') + bytes([0x02, 0x00])))
            await asyncio.sleep(3.0)

            status_pkt = None
            for pkt in reassembler.complete_packets[before:]:
                if len(pkt) >= 8 and int.from_bytes(pkt[6:8], 'big') == 0x0100:
                    status_pkt = pkt
                    break

            if not status_pkt or len(status_pkt) <= 12 + SPEED_POS_IN_P0:
                print("  No valid status response!")
                return

            full_p0 = status_pkt[12:]
            current_speed = full_p0[SPEED_POS_IN_P0]
            device_data = full_p0[DEVICE_DATA_START:]

            print(f"  Current speed: {current_speed}%")
            print(f"  Full P0 ({len(full_p0)}B):")
            hexdump(full_p0)
            print(f"  Device data ({len(device_data)}B, starting at P0[{DEVICE_DATA_START}]):")
            hexdump(device_data, max_bytes=48)

            if current_speed == TARGET_SPEED:
                print(f"\n  WARNING: Already at {TARGET_SPEED}%! Change TARGET_SPEED.")
                return

            # ============================================================
            # Phase 2: Test write formats
            # ============================================================
            test_formats = []

            # ----------------------------------------------------------
            # Theory 1: Write device data only (strip product key prefix)
            # ----------------------------------------------------------
            # Speed is at offset 2 in device data
            mod_devdata = bytearray(device_data)
            mod_devdata[SPEED_POS_IN_DEVDATA] = TARGET_SPEED

            # 1a: action 0x01 + device data only
            test_formats.append(("1a: 0x01 + device_data_only", 0x93,
                bytes([0x01]) + bytes(mod_devdata)))

            # 1b: action 0x01 + 1-byte flags + device data only
            for flags in [0x04, 0x20, 0xFF]:
                test_formats.append((f"1b: 0x01 + flags=0x{flags:02x} + devdata_only", 0x93,
                    bytes([0x01, flags]) + bytes(mod_devdata)))

            # 1c: Just device data (no action byte)
            test_formats.append(("1c: raw device_data (no action)", 0x93,
                bytes(mod_devdata)))

            # ----------------------------------------------------------
            # Theory 2: cmd 0x0090 (WiFi LAN protocol equivalent)
            # ----------------------------------------------------------
            # 2a: cmd 0x0090 + full P0 with action=0x01
            mod_full = bytearray(full_p0)
            mod_full[0] = 0x01
            mod_full[SPEED_POS_IN_P0] = TARGET_SPEED
            test_formats.append(("2a: cmd=0x0090 + full_p0 action=0x01", 0x0090,
                bytes(mod_full)))

            # 2b: cmd 0x0090 + device data with action
            test_formats.append(("2b: cmd=0x0090 + 0x01 + devdata", 0x0090,
                bytes([0x01]) + bytes(mod_devdata)))

            # 2c: cmd 0x0090 + simple speed
            test_formats.append(("2c: cmd=0x0090 + action + flag + speed", 0x0090,
                bytes([0x01, 0x04, TARGET_SPEED])))

            # ----------------------------------------------------------
            # Theory 3: The 0x0062 command is the control channel
            # ----------------------------------------------------------
            test_formats.append(("3a: cmd=0x0062 + action + speed", 0x0062,
                bytes([0x01, TARGET_SPEED])))
            test_formats.append(("3b: cmd=0x0062 + devdata", 0x0062,
                bytes(mod_devdata)))

            # ----------------------------------------------------------
            # Theory 4: Device data has internal Gizwits structure
            # ----------------------------------------------------------
            # Looking at device data bytes:
            #   [0]=0x03  [1]=0x11  [2]=speed  [3]=0x0a  [4]=0x1e
            # 0x03 might be flags_length, 0x11 might be packed bools
            # Let's try treating [0] as action and [1] as flags
            mod_dd = bytearray(device_data)
            mod_dd[0] = 0x01  # Change action from 0x03 to 0x01 (write)
            mod_dd[SPEED_POS_IN_DEVDATA] = TARGET_SPEED
            test_formats.append(("4a: devdata with [0]=0x01 (write action)", 0x93,
                bytes(mod_dd)))

            # Maybe [0:2] is a header: [action=0x01, flags=0x11, speed, ...]
            test_formats.append(("4b: 0x01 + 0x11 + speed (minimal devdata style)", 0x93,
                bytes([0x01, 0x11, TARGET_SPEED])))

            # Maybe flags 0x11 means bits 0 and 4 set
            test_formats.append(("4c: 0x01 + 0x11 + speed + rest of devdata", 0x93,
                bytes([0x01, 0x11, TARGET_SPEED]) + bytes(device_data[3:])))

            # ----------------------------------------------------------
            # Theory 5: Need the full P0 header but with write action byte
            #            embedded in the device data section
            # ----------------------------------------------------------
            mod_full2 = bytearray(full_p0)
            mod_full2[DEVICE_DATA_START] = 0x01  # Change devdata[0] from 0x03 to 0x01
            mod_full2[SPEED_POS_IN_P0] = TARGET_SPEED
            test_formats.append(("5a: full P0, devdata[0]=0x01 (write)", 0x93,
                bytes(mod_full2)))

            # Same but keep P0[0] as 0x01 too
            mod_full3 = bytearray(mod_full2)
            mod_full3[0] = 0x01
            test_formats.append(("5b: full P0, both [0]=0x01 and devdata[0]=0x01", 0x93,
                bytes(mod_full3)))

            # ----------------------------------------------------------
            # Theory 6: P0[0] = 0xd1 is a version/type, write uses 0xd0 or similar
            # ----------------------------------------------------------
            for action_byte in [0xd0, 0xc1, 0x01, 0x11]:
                mod = bytearray(full_p0)
                mod[0] = action_byte
                mod[SPEED_POS_IN_P0] = TARGET_SPEED
                test_formats.append((f"6: full P0 with [0]=0x{action_byte:02x}", 0x93,
                    bytes(mod)))

            # ----------------------------------------------------------
            # Theory 7: cmd 0x0093 without cmd_sn prefix
            # (maybe cmd_sn is only for reads, writes send P0 directly)
            # ----------------------------------------------------------
            # We'll handle this specially below

            # ============================================================
            # Run tests
            # ============================================================
            print(f"\n[3] Testing {len(test_formats)} write formats...\n")

            def send_and_verify():
                pass  # placeholder

            for i, (desc, cmd_code, p0_data) in enumerate(test_formats):
                if not client.is_connected:
                    print(f"\n  DISCONNECTED at test {i}. Stopping.")
                    break

                print(f"  --- Test {i+1}/{len(test_formats)}: {desc} ---")
                print(f"      P0 ({len(p0_data)}B): {p0_data[:24].hex()}{'...' if len(p0_data) > 24 else ''}")

                # Build packet with cmd_sn
                sn = (int(time.time()) + i).to_bytes(4, 'big')
                payload = sn + p0_data
                packet = build_packet(cmd_code, payload)

                try:
                    await client.write_gatt_char(CHAR_UUID, packet)
                except Exception as e:
                    print(f"      SEND ERROR: {e}")
                    continue

                await asyncio.sleep(1.5)

                if not client.is_connected:
                    print(f"      DISCONNECTED! Unsafe format.")
                    break

                # Verify
                before = len(reassembler.complete_packets)
                sn2 = int(time.time()).to_bytes(4, 'big')
                await client.write_gatt_char(CHAR_UUID,
                    build_packet(0x93, sn2 + bytes([0x02, 0x00])))
                await asyncio.sleep(2.5)

                new_speed = None
                for pkt in reassembler.complete_packets[before:]:
                    if len(pkt) >= 8 and int.from_bytes(pkt[6:8], 'big') == 0x0100:
                        if len(pkt) > 12 + SPEED_POS_IN_P0:
                            new_speed = pkt[12 + SPEED_POS_IN_P0]
                            break

                if new_speed is not None:
                    if new_speed == TARGET_SPEED:
                        print(f"      *** SUCCESS! Speed changed to {new_speed}% ***")
                        print(f"      *** WORKING: {desc} ***")
                        print(f"      *** cmd=0x{cmd_code:04x}, P0={p0_data.hex()} ***")
                        await client.stop_notify(CHAR_UUID)
                        return
                    else:
                        print(f"      Speed still {new_speed}%")
                else:
                    print(f"      Could not verify (no status response)")

                await asyncio.sleep(0.3)

            # ----------------------------------------------------------
            # Theory 7: Send WITHOUT cmd_sn prefix
            # ----------------------------------------------------------
            if client.is_connected:
                print(f"\n  --- Theory 7: Commands WITHOUT cmd_sn ---")
                no_sn_tests = [
                    ("7a: no_sn + 0x01 + devdata", 0x93,
                        bytes([0x01]) + bytes(mod_devdata)),
                    ("7b: no_sn + devdata_with_write_action", 0x93,
                        bytes(mod_dd)),
                    ("7c: no_sn + 0x01 + 0x11 + speed", 0x93,
                        bytes([0x01, 0x11, TARGET_SPEED])),
                ]

                for desc, cmd_code, p0_data in no_sn_tests:
                    if not client.is_connected:
                        break

                    print(f"  --- {desc} ---")
                    print(f"      P0 ({len(p0_data)}B): {p0_data[:24].hex()}")

                    # Send WITHOUT cmd_sn
                    packet = build_packet(cmd_code, p0_data)

                    try:
                        await client.write_gatt_char(CHAR_UUID, packet)
                    except Exception as e:
                        print(f"      SEND ERROR: {e}")
                        continue

                    await asyncio.sleep(1.5)

                    if not client.is_connected:
                        print(f"      DISCONNECTED!")
                        break

                    # Verify
                    before = len(reassembler.complete_packets)
                    sn = int(time.time()).to_bytes(4, 'big')
                    await client.write_gatt_char(CHAR_UUID,
                        build_packet(0x93, sn + bytes([0x02, 0x00])))
                    await asyncio.sleep(2.5)

                    for pkt in reassembler.complete_packets[before:]:
                        if len(pkt) >= 8 and int.from_bytes(pkt[6:8], 'big') == 0x0100:
                            if len(pkt) > 12 + SPEED_POS_IN_P0:
                                new_speed = pkt[12 + SPEED_POS_IN_P0]
                                if new_speed == TARGET_SPEED:
                                    print(f"      *** SUCCESS! ***")
                                    await client.stop_notify(CHAR_UUID)
                                    return
                                else:
                                    print(f"      Speed still {new_speed}%")
                                break

            # ----------------------------------------------------------
            # Theory 8: Try writing to OTHER characteristics
            # ----------------------------------------------------------
            if client.is_connected:
                print(f"\n  --- Theory 8: Other writable characteristics ---")
                writable_chars = [
                    (svc, char, props) for svc, char, props in all_chars
                    if ('write' in props or 'write-without-response' in props)
                    and char != CHAR_UUID
                ]
                if writable_chars:
                    for svc, char_uuid, props in writable_chars:
                        print(f"  Trying char {char_uuid} [{', '.join(props)}]")
                        test_payload = bytes([0x01, 0x11, TARGET_SPEED])
                        try:
                            await client.write_gatt_char(char_uuid, test_payload)
                            print(f"      Written!")
                            await asyncio.sleep(2.0)

                            # Verify on main char
                            before = len(reassembler.complete_packets)
                            sn = int(time.time()).to_bytes(4, 'big')
                            await client.write_gatt_char(CHAR_UUID,
                                build_packet(0x93, sn + bytes([0x02, 0x00])))
                            await asyncio.sleep(2.5)

                            for pkt in reassembler.complete_packets[before:]:
                                if len(pkt) >= 8 and int.from_bytes(pkt[6:8], 'big') == 0x0100:
                                    if len(pkt) > 12 + SPEED_POS_IN_P0:
                                        new_speed = pkt[12 + SPEED_POS_IN_P0]
                                        if new_speed == TARGET_SPEED:
                                            print(f"      *** SUCCESS on {char_uuid}! ***")
                                            await client.stop_notify(CHAR_UUID)
                                            return
                                        else:
                                            print(f"      Speed still {new_speed}%")
                                        break
                        except Exception as e:
                            print(f"      Error: {e}")
                else:
                    print(f"  No other writable characteristics found")

            print(f"\n[4] No format worked.")
            await client.stop_notify(CHAR_UUID)

    except Exception as e:
        print(f"Error: {e}")
        import traceback
        traceback.print_exc()

    print("\n" + "=" * 70)
    print("ROUND 2 RESULTS")
    print("=" * 70)
    print("No write format changed the pump speed.")
    print("Recommend pivoting to WiFi protocol (test-mdp-wifi.py)")


if __name__ == "__main__":
    asyncio.run(run_tests())
