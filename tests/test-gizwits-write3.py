#!/usr/bin/env python3
"""
Gizwits P0 Write Test - Round 3

Round 1-2 findings:
- Status response (cmd 0x0100): 211 bytes total, P0 = 199 bytes
- P0 structure: [dynamic_byte, 0x00, 0x16, <22-byte product key>, <device data>]
- Device data at P0[25:]: [0x03, 0x11, 0x4B, 0x0A, 0x1E, ...]
  - [0] = 0x03 = action (status report from device)
  - [1] = 0x11 = bool flags (bit0=power ON, bit4=?)
  - [2] = 0x4B = 75 = speed (uint8)
  - [3:] = other data point values
- Only one BLE characteristic exists (abf7)
- cmd 0x0090 IS recognized (got 0x0091 ACK)
- App works via BLE even with WiFi disabled - so BLE writes ARE possible

Round 2 bugs found:
1. We included the action byte (0x03) inside attr_vals - should be stripped
2. Packet flag byte (position 5) always 0x00, but device uses 0x02
3. Never acknowledged the 0x0062 message after login

Round 3 focuses on:
1. Correct attr_vals (strip action byte from device data)
2. Try flag byte = 0x02 in outer packet header
3. Acknowledge 0x0062 before sending controls
4. Systematically try every attr_flags bit 0-15
5. Try both cmd 0x0090 and 0x0093
"""

import asyncio
import time
from bleak import BleakClient

MDP_MAC = "7725528E-75A8-F1C3-71E6-CEF9A6EDA5EE"
SERVICE_UUID = "0000abf0-0000-1000-8000-00805f9b34fb"
CHAR_UUID = "0000abf7-0000-1000-8000-00805f9b34fb"

TARGET_SPEED = 55
SPEED_POS_IN_P0 = 27
DEVICE_DATA_START = 25


def build_packet(cmd: int, payload: bytes, flags: int = 0x00) -> bytes:
    """Build Gizwits BLE packet with configurable flags byte"""
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


def hexdump(data: bytes, prefix: str = "  ", max_bytes: int = 64):
    for i in range(0, min(len(data), max_bytes), 16):
        chunk = data[i:i+16]
        hex_str = ' '.join(f'{b:02x}' for b in chunk)
        ascii_str = ''.join(chr(b) if 32 <= b <= 126 else '.' for b in chunk)
        print(f"{prefix}{i:04x}: {hex_str:<48} | {ascii_str}")


async def read_status(client, reassembler, wait=3.0):
    """Read full status, return reassembled packet or None"""
    before = len(reassembler.complete_packets)
    sn = int(time.time())
    await client.write_gatt_char(CHAR_UUID,
        build_packet(0x93, sn.to_bytes(4, 'big') + bytes([0x02, 0x00])))
    await asyncio.sleep(wait)

    for pkt in reassembler.complete_packets[before:]:
        if len(pkt) >= 8 and int.from_bytes(pkt[6:8], 'big') == 0x0100:
            if len(pkt) > 12 + SPEED_POS_IN_P0:
                return pkt
    return None


def get_speed(pkt):
    if pkt and len(pkt) > 12 + SPEED_POS_IN_P0:
        return pkt[12 + SPEED_POS_IN_P0]
    return -1


async def try_write(client, reassembler, desc, cmd_code, p0_data,
                    use_sn=True, pkt_flags=0x00):
    """Send a write command and verify if speed changed. Returns new speed or -1."""
    if not client.is_connected:
        return -2  # disconnected

    print(f"  [{desc}]")
    print(f"    cmd=0x{cmd_code:04x} flags=0x{pkt_flags:02x} sn={'yes' if use_sn else 'no'}")
    print(f"    P0 ({len(p0_data)}B): {p0_data[:20].hex()}{'...' if len(p0_data) > 20 else ''}")

    if use_sn:
        sn = int(time.time())
        payload = sn.to_bytes(4, 'big') + p0_data
    else:
        payload = p0_data

    packet = build_packet(cmd_code, payload, flags=pkt_flags)

    try:
        await client.write_gatt_char(CHAR_UUID, packet)
    except Exception as e:
        print(f"    SEND ERROR: {e}")
        return -1

    await asyncio.sleep(1.0)

    if not client.is_connected:
        print(f"    DISCONNECTED!")
        return -2

    # Verify
    status = await read_status(client, reassembler, wait=2.0)
    speed = get_speed(status)
    if speed == TARGET_SPEED:
        print(f"    *** SUCCESS! Speed = {speed}% ***")
    elif speed >= 0:
        print(f"    Speed still {speed}%")
    else:
        print(f"    Could not verify")
    return speed


async def run_tests():
    print("=" * 70)
    print("Gizwits P0 Write Test - Round 3")
    print("=" * 70)
    print(f"Target speed: {TARGET_SPEED}%\n")

    reassembler = PacketReassembler()

    def handler(sender, data):
        completed = reassembler.feed(data)
        for pkt in completed:
            if len(pkt) >= 8:
                cmd = int.from_bytes(pkt[6:8], 'big')
                tags = {0x0094: "ACK-93", 0x0091: "ACK-90", 0x0100: "STATUS",
                        0x0007: "PASSCODE", 0x0009: "LOGIN", 0x0062: "DEV-STATUS",
                        0x0093: "P0-UPDATE"}
                tag = tags.get(cmd, f"0x{cmd:04x}")
                print(f"    <- {tag} ({len(pkt)}B)")

    try:
        async with BleakClient(MDP_MAC) as client:
            await client.start_notify(CHAR_UUID, handler)

            # === AUTH ===
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

            print(f"  Passcode: {passcode.hex()}")
            await client.write_gatt_char(CHAR_UUID, build_packet(0x08, passcode))
            await asyncio.sleep(1.5)

            # Check for 0x0062 message
            got_0062 = False
            msg_0062 = None
            for pkt in reassembler.complete_packets:
                if len(pkt) >= 8 and int.from_bytes(pkt[6:8], 'big') == 0x0062:
                    got_0062 = True
                    msg_0062 = pkt
                    print(f"  Got 0x0062: {pkt.hex()}")
                    break

            # === ACKNOWLEDGE 0x0062 ===
            if got_0062:
                print("\n[1.5] Acknowledging 0x0062 message...")
                # Try sending ACK for 0x0062
                ack_cmds = [0x0063, 0x0062, 0x0060, 0x0061]
                for ack_cmd in ack_cmds:
                    try:
                        await client.write_gatt_char(CHAR_UUID,
                            build_packet(ack_cmd, b'\x00'))
                        print(f"  Sent 0x{ack_cmd:04x} ACK")
                        await asyncio.sleep(0.5)
                    except:
                        pass

            # === READ STATUS ===
            print(f"\n[2] Reading status...")
            status_pkt = await read_status(client, reassembler)
            if not status_pkt:
                print("  No status response!")
                return

            full_p0 = status_pkt[12:]
            current_speed = full_p0[SPEED_POS_IN_P0]
            device_data = full_p0[DEVICE_DATA_START:]
            # IMPORTANT: strip the action byte (0x03) from device data to get attr_vals
            attr_vals = bytearray(device_data[1:])  # [0x11, 0x4B, 0x0A, 0x1E, ...]
            speed_pos_in_attrvals = 1  # speed is at position 1 in attr_vals

            print(f"  Current speed: {current_speed}%")
            print(f"  Device data action byte: 0x{device_data[0]:02x}")
            print(f"  attr_vals ({len(attr_vals)}B):")
            hexdump(attr_vals, max_bytes=48)
            print(f"  attr_vals[0] (bool flags): 0x{attr_vals[0]:02x} = {attr_vals[0]:08b}")
            print(f"  attr_vals[1] (speed): {attr_vals[1]}")

            if current_speed == TARGET_SPEED:
                print(f"\n  Already at {TARGET_SPEED}%!")
                return

            # Prepare modified attr_vals with target speed
            mod_attrvals = bytearray(attr_vals)
            mod_attrvals[speed_pos_in_attrvals] = TARGET_SPEED

            # ============================================================
            # TEST GROUPS
            # ============================================================
            print(f"\n[3] Testing write formats...\n")

            # ----------------------------------------------------------
            # Group A: Correct Gizwits P0 format with STRIPPED action byte
            # P0 = action(0x01) + attr_flags(1-2 bytes) + attr_vals
            # Try every attr_flags bit 0-15 to find which one = speed
            # ----------------------------------------------------------
            print("  === Group A: Proper P0 with stripped attr_vals ===")

            for bit in range(16):
                if not client.is_connected:
                    break
                if bit < 8:
                    flags = bytes([1 << bit])
                else:
                    flags = bytes([0x00, 1 << (bit - 8)])

                p0 = bytes([0x01]) + flags + bytes(mod_attrvals)
                result = await try_write(client, reassembler,
                    f"A: attr_flags bit {bit} (0x{flags.hex()})", 0x93, p0)
                if result == TARGET_SPEED:
                    return
                if result == -2:
                    break

            # ----------------------------------------------------------
            # Group B: Same but with outer packet flags=0x02
            # ----------------------------------------------------------
            if client.is_connected:
                print("\n  === Group B: flags=0x02 in outer packet ===")
                for flags_val in [0x01, 0x02, 0x04, 0x08, 0x10]:
                    if not client.is_connected:
                        break
                    p0 = bytes([0x01, 0x04]) + bytes(mod_attrvals)  # bit 2 for speed
                    result = await try_write(client, reassembler,
                        f"B: pkt_flags=0x{flags_val:02x}", 0x93, p0,
                        pkt_flags=flags_val)
                    if result == TARGET_SPEED:
                        return
                    if result == -2:
                        break

            # ----------------------------------------------------------
            # Group C: cmd 0x0090 with correct attr_vals
            # ----------------------------------------------------------
            if client.is_connected:
                print("\n  === Group C: cmd 0x0090 with proper attr_vals ===")
                for bit in range(8):
                    if not client.is_connected:
                        break
                    flags = bytes([1 << bit])
                    p0 = bytes([0x01]) + flags + bytes(mod_attrvals)
                    result = await try_write(client, reassembler,
                        f"C: 0x0090 attr_flags bit {bit}", 0x0090, p0)
                    if result == TARGET_SPEED:
                        return
                    if result == -2:
                        break

            # ----------------------------------------------------------
            # Group D: Just modify bool flags + speed, minimal payload
            # Theory: maybe attr_vals should ONLY contain the changed values
            # ----------------------------------------------------------
            if client.is_connected:
                print("\n  === Group D: Minimal attr_vals (only changed fields) ===")
                tests_d = [
                    # (desc, attr_flags, attr_vals)
                    ("D1: flags=0x02, vals=[speed]", bytes([0x02]), bytes([TARGET_SPEED])),
                    ("D2: flags=0x04, vals=[speed]", bytes([0x04]), bytes([TARGET_SPEED])),
                    ("D3: flags=0x02, vals=[0x11, speed]", bytes([0x02]), bytes([0x11, TARGET_SPEED])),
                    ("D4: flags=0x06, vals=[0x11, speed]", bytes([0x06]), bytes([0x11, TARGET_SPEED])),
                    ("D5: flags=0x03, vals=[0x11, speed]", bytes([0x03]), bytes([0x11, TARGET_SPEED])),
                    # Maybe speed is a 16-bit value?
                    ("D6: flags=0x02, vals=[0x00, speed]", bytes([0x02]), bytes([0x00, TARGET_SPEED])),
                    ("D7: flags=0x04, vals=[0x00, speed]", bytes([0x04]), bytes([0x00, TARGET_SPEED])),
                ]
                for desc, aflags, avals in tests_d:
                    if not client.is_connected:
                        break
                    p0 = bytes([0x01]) + aflags + avals
                    result = await try_write(client, reassembler, desc, 0x93, p0)
                    if result == TARGET_SPEED:
                        return
                    if result == -2:
                        break

            # ----------------------------------------------------------
            # Group E: Without cmd_sn, with correct attr_vals
            # ----------------------------------------------------------
            if client.is_connected:
                print("\n  === Group E: No cmd_sn ===")
                for bit in [0, 1, 2, 3, 4]:
                    if not client.is_connected:
                        break
                    flags = bytes([1 << bit])
                    p0 = bytes([0x01]) + flags + bytes(mod_attrvals)
                    result = await try_write(client, reassembler,
                        f"E: no_sn, attr_flags bit {bit}", 0x93, p0, use_sn=False)
                    if result == TARGET_SPEED:
                        return
                    if result == -2:
                        break

            # ----------------------------------------------------------
            # Group F: Completely raw - write attr_vals directly
            # Maybe the protocol is simpler than Gizwits standard
            # ----------------------------------------------------------
            if client.is_connected:
                print("\n  === Group F: Raw data, non-standard formats ===")
                tests_f = [
                    # Maybe just: action + entire device data (with action changed)
                    ("F1: device_data with action=0x01",
                        bytes([0x01]) + bytes(device_data[1:])),
                    # Maybe: action + bool_flags + speed (no other vals needed)
                    ("F2: 0x01 + 0x11 + speed (3 bytes)",
                        bytes([0x01, 0x11, TARGET_SPEED])),
                    # With power bit cleared to test
                    ("F3: 0x01 + 0x01 + speed (power on, no bit4)",
                        bytes([0x01, 0x01, TARGET_SPEED])),
                    # Try the exact format from the status but action=0x01
                    ("F4: echo devdata[0:8] with action=0x01",
                        bytes([0x01]) + bytes(device_data[1:8])),
                    # Maybe speed needs the full data context up to it
                    ("F5: 0x01 + devdata[1:3] (bool+speed only)",
                        bytes([0x01, device_data[1], TARGET_SPEED])),
                ]
                for desc, p0 in tests_f:
                    if not client.is_connected:
                        break
                    result = await try_write(client, reassembler, desc, 0x93, p0)
                    if result == TARGET_SPEED:
                        return
                    if result == -2:
                        break

            # ----------------------------------------------------------
            # Group G: Try 0x0090 without cmd_sn
            # ----------------------------------------------------------
            if client.is_connected:
                print("\n  === Group G: 0x0090 without cmd_sn ===")
                tests_g = [
                    ("G1: 0x0090 no_sn, 0x01+0x04+attrvals",
                        bytes([0x01, 0x04]) + bytes(mod_attrvals)),
                    ("G2: 0x0090 no_sn, 0x01+0x02+attrvals",
                        bytes([0x01, 0x02]) + bytes(mod_attrvals)),
                    ("G3: 0x0090 no_sn, 0x01+0x01+speed",
                        bytes([0x01, 0x01, TARGET_SPEED])),
                    ("G4: 0x0090 no_sn, raw devdata action=0x01",
                        bytes([0x01]) + bytes(device_data[1:])),
                ]
                for desc, p0 in tests_g:
                    if not client.is_connected:
                        break
                    result = await try_write(client, reassembler, desc, 0x0090, p0,
                                           use_sn=False)
                    if result == TARGET_SPEED:
                        return
                    if result == -2:
                        break

            if client.is_connected:
                await client.stop_notify(CHAR_UUID)

    except Exception as e:
        print(f"\nError: {e}")
        import traceback
        traceback.print_exc()

    print("\n" + "=" * 70)
    print("ROUND 3 RESULTS: No format changed speed.")
    print("=" * 70)
    print("\nNext steps:")
    print("  1. Decompile the Jebao app APK to find exact BLE write format")
    print("  2. Try WiFi protocol to sniff working commands from the app")
    print("  3. Try a BLE MITM proxy between phone and pump")


if __name__ == "__main__":
    asyncio.run(run_tests())
