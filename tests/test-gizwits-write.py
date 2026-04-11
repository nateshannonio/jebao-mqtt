#!/usr/bin/env python3
"""
Test Gizwits P0 write format for MDP pump control.

Key insight: Previous tests sent tiny 2-3 byte P0 payloads, but the Gizwits
protocol requires: action(1B) + attr_flags(NB) + attr_vals(NB)

The attr_vals section must match the device's data point layout — the same
layout we see in the 328-byte status response from action 0x02.

Speed is at position 27 in the status payload. We need to figure out:
1. How many bytes is attr_flags?
2. Which bit in attr_flags corresponds to speed?
3. Does attr_vals need to be the full layout or just the relevant portion?

This script:
- Reads the full status response
- Modifies speed in the captured layout
- Sends it back with action 0x01 and various attr_flags formats
- Verifies by re-reading status after each attempt
"""

import asyncio
import time
from bleak import BleakClient

MDP_MAC = "7725528E-75A8-F1C3-71E6-CEF9A6EDA5EE"
SERVICE_UUID = "0000abf0-0000-1000-8000-00805f9b34fb"
CHAR_UUID = "0000abf7-0000-1000-8000-00805f9b34fb"

SPEED_POS = 27  # Position of speed in the status payload (P0 data after action byte)

# Target speed for testing - pick something obviously different from current
TARGET_SPEED = 55


def build_packet(cmd: int, payload: bytes) -> bytes:
    """Build Gizwits BLE packet"""
    length = 3 + len(payload)
    return bytes([0x00, 0x00, 0x00, 0x03, length, 0x00]) + cmd.to_bytes(2, 'big') + payload


def hexdump(data: bytes, prefix: str = "  ", max_bytes: int = 64):
    """Print hex dump of data"""
    for i in range(0, min(len(data), max_bytes), 16):
        chunk = data[i:i+16]
        hex_str = ' '.join(f'{b:02x}' for b in chunk)
        ascii_str = ''.join(chr(b) if 32 <= b <= 126 else '.' for b in chunk)
        print(f"{prefix}{i:04x}: {hex_str:<48} | {ascii_str}")
    if len(data) > max_bytes:
        print(f"{prefix}... ({len(data) - max_bytes} more bytes)")


class PacketReassembler:
    """Reassemble fragmented BLE notifications into complete Gizwits packets.

    BLE has a 20-byte MTU, so large responses (like the 200+ byte status)
    arrive as multiple notifications that need to be concatenated.
    """

    def __init__(self):
        self.buffer = bytearray()
        self.expected_len = 0
        self.complete_packets = []

    def feed(self, data: bytes):
        """Feed a BLE notification. Returns list of newly completed packets."""
        completed = []

        if not self.buffer:
            # Starting a new packet - parse header
            if len(data) >= 5 and data[:4] == bytes([0x00, 0x00, 0x00, 0x03]):
                length_field = data[4]
                # Total packet = 4 (header) + 1 (length) + length_field bytes
                self.expected_len = 5 + length_field
                self.buffer.extend(data)
            else:
                # Continuation of previous packet (no header)
                # This shouldn't happen if buffer is empty, but handle it
                return completed
        else:
            # Continuation fragment
            self.buffer.extend(data)

        # Check if we have a complete packet
        if len(self.buffer) >= self.expected_len > 0:
            packet = bytes(self.buffer[:self.expected_len])
            completed.append(packet)
            self.complete_packets.append(packet)
            # Reset for next packet
            remainder = bytes(self.buffer[self.expected_len:])
            self.buffer = bytearray()
            self.expected_len = 0
            # If there's leftover data, it's the start of a new packet
            if remainder:
                completed.extend(self.feed(remainder))

        return completed


async def authenticate(client, responses):
    """Authenticate with the pump, return True on success"""
    get_pass = build_packet(0x06, b'')
    await client.write_gatt_char(CHAR_UUID, get_pass)
    await asyncio.sleep(0.5)

    if not responses:
        print("  No passcode response received")
        return False

    resp = responses[-1]
    if len(resp) <= 8:
        print("  Passcode response too short")
        return False

    passcode = resp[8:]
    print(f"  Passcode: {passcode.hex()}")

    login = build_packet(0x08, passcode)
    await client.write_gatt_char(CHAR_UUID, login)
    await asyncio.sleep(1.0)
    print("  Auth complete")
    return True


async def read_status(client, reassembler, wait=2.0):
    """Read full status. Returns the reassembled status packet or None."""
    before_count = len(reassembler.complete_packets)
    cmd_sn = int(time.time())
    status_cmd = build_packet(0x93, cmd_sn.to_bytes(4, 'big') + bytes([0x02, 0x00]))
    await client.write_gatt_char(CHAR_UUID, status_cmd)

    await asyncio.sleep(wait)

    # Find the status response (cmd 0x0100) in newly completed packets
    for pkt in reassembler.complete_packets[before_count:]:
        if len(pkt) >= 8:
            cmd = int.from_bytes(pkt[6:8], 'big')
            if cmd == 0x0100 and len(pkt) > 12:
                return pkt
    return None


def extract_speed(status_response: bytes) -> int:
    """Extract speed from a full reassembled status response packet"""
    if status_response and len(status_response) > 12 + SPEED_POS:
        # P0 starts at byte 12, speed is at SPEED_POS within P0
        return status_response[12 + SPEED_POS]
    return -1


async def run_tests():
    print("=" * 70)
    print("Gizwits P0 Write Format Test for MDP-5000")
    print("=" * 70)
    print(f"Target: Change speed to {TARGET_SPEED}%")
    print(f"Speed position in status payload: byte {SPEED_POS}")
    print()

    responses = []  # raw BLE notifications
    reassembler = PacketReassembler()

    def handler(sender, data):
        responses.append(data)
        completed = reassembler.feed(data)
        for pkt in completed:
            if len(pkt) >= 8:
                cmd = int.from_bytes(pkt[6:8], 'big')
                if cmd == 0x0094:
                    print(f"    <- ACK (0x0094)")
                elif cmd == 0x0100:
                    print(f"    <- Status response (0x0100), {len(pkt)} bytes (reassembled)")
                elif cmd == 0x0093:
                    print(f"    <- P0 update (0x0093), {len(pkt)} bytes")
                elif cmd == 0x0007:
                    print(f"    <- Passcode response")
                elif cmd == 0x0009:
                    status = "OK" if len(pkt) > 8 and pkt[8] == 0x00 else "FAIL"
                    print(f"    <- Login response: {status}")
                else:
                    print(f"    <- CMD 0x{cmd:04x}, {len(pkt)} bytes")

    try:
        async with BleakClient(MDP_MAC) as client:
            print("[1] Connecting and authenticating...")
            await client.start_notify(CHAR_UUID, handler)

            if not await authenticate(client, responses):
                print("Authentication failed!")
                return

            # Step 2: Read current status
            print("\n[2] Reading current status...")
            status_response = await read_status(client, reassembler)

            if not status_response:
                print("  Failed to get status response!")
                return

            current_speed = extract_speed(status_response)
            print(f"  Current speed: {current_speed}%")

            # Extract P0 data (everything after the 12-byte header)
            full_p0 = status_response[12:]
            print(f"  P0 length: {len(full_p0)} bytes")
            print(f"  P0 first 48 bytes:")
            hexdump(full_p0, max_bytes=48)

            if current_speed == TARGET_SPEED:
                print(f"\n  WARNING: Pump already at {TARGET_SPEED}%!")
                print(f"  Change TARGET_SPEED in script to a different value.")
                return

            # ============================================================
            # Test formats - each tries a different P0 write structure
            # ============================================================
            test_formats = []

            # --- Format A: Echo back the full status with action changed ---
            # Theory: The status response IS the data point layout.
            # Change action from whatever it is to 0x01 (write), modify speed.
            modified_p0 = bytearray(full_p0)
            modified_p0[0] = 0x01  # Change action to "write"
            modified_p0[SPEED_POS] = TARGET_SPEED
            test_formats.append((
                "A: Full status echo-back with action=0x01",
                bytes(modified_p0)
            ))

            # --- Format B: action 0x01 + 1-byte attr_flags + full attr_vals ---
            # Theory: attr_flags is 1 byte, attr_vals mirrors the status layout
            # Speed is at position 27, so it might be data point 5 (bit 5 = 0x20)
            attr_vals = bytearray(full_p0[1:])  # Skip original action byte
            attr_vals[SPEED_POS - 1] = TARGET_SPEED  # -1 because we stripped action
            for flags_bit in [0x20, 0x04, 0x08, 0x10, 0x40, 0x80, 0xFF]:
                test_formats.append((
                    f"B: 0x01 + flags=0x{flags_bit:02x} + full attr_vals ({len(attr_vals)}B)",
                    bytes([0x01, flags_bit]) + bytes(attr_vals)
                ))

            # --- Format C: action 0x01 + 2-byte attr_flags + full attr_vals ---
            # Theory: attr_flags might be 2 bytes for larger data point schemas
            for hi, lo in [(0x00, 0x20), (0x00, 0x04), (0x08, 0x00), (0xFF, 0xFF)]:
                test_formats.append((
                    f"C: 0x01 + flags=0x{hi:02x}{lo:02x} + full attr_vals",
                    bytes([0x01, hi, lo]) + bytes(attr_vals)
                ))

            # --- Format D: action 0x01 + 4-byte attr_flags + full attr_vals ---
            # Theory: 4-byte flags for lots of data points
            for flags in [
                bytes([0x00, 0x00, 0x00, 0x20]),
                bytes([0x00, 0x00, 0x08, 0x00]),
                bytes([0xFF, 0xFF, 0xFF, 0xFF]),
            ]:
                test_formats.append((
                    f"D: 0x01 + 4B flags={flags.hex()} + full attr_vals",
                    bytes([0x01]) + flags + bytes(attr_vals)
                ))

            # --- Format E: Minimal writes - just speed byte at position ---
            # Theory: Maybe attr_vals doesn't need the full layout, just
            # offset-based writes?
            test_formats.append((
                "E: 0x01 + byte_offset(27) + value",
                bytes([0x01, SPEED_POS, TARGET_SPEED])
            ))

            # --- Format F: Status echo without cmd_sn in outer packet ---
            # Theory: Maybe the P0 data should be sent raw without the
            # 4-byte command serial number prefix
            # (This changes the outer packet structure, not P0)

            # --- Format G: Try action 0x03/0x04 (device->app actions repurposed) ---
            for action in [0x03, 0x04, 0x05]:
                modified = bytearray(full_p0)
                modified[0] = action
                modified[SPEED_POS] = TARGET_SPEED
                test_formats.append((
                    f"G: Full echo with action=0x{action:02x}",
                    bytes(modified)
                ))

            # --- Format H: Write using the DMP-style attribute format ---
            # Theory: Maybe MDP also uses the 11-byte DMP format?
            # DMP: p0[0]=0x11(write), p0[7]=type, p0[8]=attr_hi, p0[9]=attr_lo, p0[10]=value
            dmp_p0 = bytearray(11)
            dmp_p0[0] = 0x11  # DMP write action
            # Try different attribute addresses for speed
            for attr_hi, attr_lo in [(0x00, 0x05), (0x00, 0x1B), (0x80, 0x00), (0x00, 0x20)]:
                dmp = bytearray(dmp_p0)
                dmp[7] = 0x00  # type
                dmp[8] = attr_hi
                dmp[9] = attr_lo
                dmp[10] = TARGET_SPEED
                test_formats.append((
                    f"H: DMP-style 0x11 + attr=0x{attr_hi:02x}{attr_lo:02x} + speed",
                    bytes(dmp)
                ))

            # --- Format I: Raw P0 with just action + speed at exact offset ---
            # Pad attr_vals to put speed at position 27
            padded = bytearray(SPEED_POS + 1)
            padded[0] = 0x01  # action
            padded[SPEED_POS] = TARGET_SPEED
            test_formats.append((
                f"I: 0x01 + zeros + speed at pos {SPEED_POS} ({len(padded)}B total)",
                bytes(padded)
            ))

            # --- Format J: flags (from status) + modified speed ---
            # Use the bytes before speed position as flags/header
            # and just modify speed
            prefix = bytearray(full_p0[:SPEED_POS + 1])
            prefix[0] = 0x01  # change action
            prefix[SPEED_POS] = TARGET_SPEED
            test_formats.append((
                f"J: First {SPEED_POS+1} bytes of status with action=0x01, speed changed",
                bytes(prefix)
            ))

            # Run each test format
            print(f"\n[3] Testing {len(test_formats)} write formats...")
            print(f"    Will read status after each to check if speed changed.\n")

            for i, (desc, p0_data) in enumerate(test_formats):
                if not client.is_connected:
                    print(f"\n  DISCONNECTED at test {i}. Stopping.")
                    break

                print(f"  --- Test {i+1}/{len(test_formats)}: {desc} ---")
                print(f"  P0 ({len(p0_data)}B): {p0_data[:32].hex()}{'...' if len(p0_data) > 32 else ''}")

                # Build and send the write command
                cmd_sn = int(time.time()) + i
                payload = cmd_sn.to_bytes(4, 'big') + p0_data
                packet = build_packet(0x93, payload)

                try:
                    await client.write_gatt_char(CHAR_UUID, packet)
                except Exception as e:
                    print(f"  SEND ERROR: {e}")
                    continue

                await asyncio.sleep(1.5)

                if not client.is_connected:
                    print(f"  DISCONNECTED after send. This format is unsafe.")
                    break

                # Read status to see if speed changed
                verify = await read_status(client, reassembler)
                if verify:
                    new_speed = extract_speed(verify)
                    if new_speed == TARGET_SPEED:
                        print(f"  *** SUCCESS! Speed changed to {new_speed}% ***")
                        print(f"  *** WORKING FORMAT: {desc} ***")
                        print(f"  *** P0 hex: {p0_data.hex()} ***")

                        # Restore original speed
                        print(f"\n  Restoring speed to {current_speed}%...")
                        restore_p0 = bytearray(p0_data)
                        # Find and replace TARGET_SPEED with current_speed
                        for j in range(len(restore_p0)):
                            if restore_p0[j] == TARGET_SPEED:
                                restore_p0[j] = current_speed
                                break
                        restore_payload = (cmd_sn + 999).to_bytes(4, 'big') + bytes(restore_p0)
                        restore_packet = build_packet(0x93, restore_payload)
                        await client.write_gatt_char(CHAR_UUID, restore_packet)
                        await asyncio.sleep(1.5)

                        await client.stop_notify(CHAR_UUID)
                        return
                    else:
                        print(f"  Speed still {new_speed}% (unchanged)")
                else:
                    print(f"  Could not read status to verify")

                # Small delay between tests
                await asyncio.sleep(0.5)

            print(f"\n[4] No format changed the speed.")
            print(f"    All {len(test_formats)} formats tried.")
            await client.stop_notify(CHAR_UUID)

    except Exception as e:
        print(f"Connection error: {e}")
        import traceback
        traceback.print_exc()

    print("\n" + "=" * 70)
    print("RESULTS")
    print("=" * 70)
    print(f"None of the tested formats changed speed from {current_speed}% to {TARGET_SPEED}%.")
    print("Next step: Try WiFi protocol (TCP port 12416) instead of BLE.")


if __name__ == "__main__":
    asyncio.run(run_tests())
