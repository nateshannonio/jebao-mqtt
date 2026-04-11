#!/usr/bin/env python3
"""
Test WiFi protocol for MDP pump control.

Jebao WiFi+BLE pumps (like MDP-5000) run a Gizwits GAgent that listens
on TCP port 12416 for LAN control. This bypasses BLE entirely and:
- Has no single-connection limitation
- Uses the same Gizwits protocol but over TCP
- Can be sniffed with Wireshark while using the app simultaneously

This script:
1. Discovers the pump on the local network via UDP broadcast
2. Connects via TCP and authenticates
3. Reads status
4. Attempts speed control

Based on: https://github.com/jrigling/homeassistant-jebao (MDP-20000 WiFi)
and Gizwits LAN protocol documentation.
"""

import asyncio
import json
import socket
import struct
import time

# Network settings - adjust if your pump is on a different subnet
BROADCAST_ADDR = "255.255.255.255"
GIZWITS_UDP_PORT = 12414  # Gizwits discovery port
GIZWITS_TCP_PORT = 12416  # Gizwits LAN control port

# If you already know your pump's IP, set it here to skip discovery
PUMP_IP = None  # e.g., "192.168.254.123"

# Gizwits LAN protocol constants
GIZWITS_HEADER = bytes([0x00, 0x00, 0x00, 0x03])


def build_lan_packet(cmd: int, payload: bytes = b'') -> bytes:
    """Build a Gizwits LAN protocol packet"""
    length = 3 + len(payload)
    return GIZWITS_HEADER + bytes([length, 0x00]) + cmd.to_bytes(2, 'big') + payload


def parse_lan_packet(data: bytes):
    """Parse a Gizwits LAN protocol packet"""
    if len(data) < 8:
        return None
    header = data[:4]
    length = data[4]
    flags = data[5]
    cmd = int.from_bytes(data[6:8], 'big')
    payload = data[8:] if len(data) > 8 else b''
    return {
        'header': header.hex(),
        'length': length,
        'flags': flags,
        'cmd': cmd,
        'cmd_hex': f'0x{cmd:04x}',
        'payload': payload,
        'raw': data,
    }


async def discover_pump():
    """Try to discover Gizwits devices on the LAN via UDP broadcast"""
    print("=" * 60)
    print("Phase 1: UDP Discovery")
    print("=" * 60)

    # Gizwits devices respond to broadcast on port 12414
    # The discovery packet varies by implementation
    discovery_packets = [
        # Standard Gizwits LAN discovery
        b'{"cmd": 1}',
        # Alternate JSON format
        b'{"cmd":1}',
        # Binary discovery
        build_lan_packet(0x0003),
        build_lan_packet(0x0004),
        # Simple ping
        b'\x00\x00\x00\x03\x03\x00\x00\x03',
    ]

    found_devices = []

    for i, disc_pkt in enumerate(discovery_packets):
        print(f"\n  Trying discovery format {i+1}: {disc_pkt[:32].hex() if isinstance(disc_pkt, bytes) and not disc_pkt.startswith(b'{') else disc_pkt[:50]}")

        sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        sock.setsockopt(socket.SOL_SOCKET, socket.SO_BROADCAST, 1)
        sock.settimeout(2.0)

        try:
            sock.sendto(disc_pkt, (BROADCAST_ADDR, GIZWITS_UDP_PORT))

            while True:
                try:
                    data, addr = sock.recvfrom(1024)
                    print(f"  Response from {addr[0]}:{addr[1]}")
                    print(f"    Raw: {data.hex()}")
                    try:
                        text = data.decode('utf-8', errors='replace')
                        print(f"    Text: {text}")
                    except:
                        pass
                    found_devices.append(addr[0])
                except socket.timeout:
                    break
        except Exception as e:
            print(f"    Error: {e}")
        finally:
            sock.close()

    # Also try the TCP port directly on common IPs if no discovery response
    if not found_devices:
        print("\n  No UDP responses. Trying TCP port scan on local subnet...")
        # Get local IP to determine subnet
        try:
            s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
            s.connect(("8.8.8.8", 80))
            local_ip = s.getsockname()[0]
            s.close()
            subnet = '.'.join(local_ip.split('.')[:3])
            print(f"  Local IP: {local_ip}, scanning {subnet}.0/24 on port {GIZWITS_TCP_PORT}")

            # Quick scan - just try connecting to port 12416
            for last_octet in range(1, 255):
                ip = f"{subnet}.{last_octet}"
                sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
                sock.settimeout(0.1)
                result = sock.connect_ex((ip, GIZWITS_TCP_PORT))
                sock.close()
                if result == 0:
                    print(f"  FOUND: {ip} has port {GIZWITS_TCP_PORT} open!")
                    found_devices.append(ip)
        except Exception as e:
            print(f"  Scan error: {e}")

    return found_devices


async def try_tcp_connection(ip: str):
    """Try to connect to the pump via TCP and exchange protocol messages"""
    print(f"\n{'=' * 60}")
    print(f"Phase 2: TCP Connection to {ip}:{GIZWITS_TCP_PORT}")
    print(f"{'=' * 60}")

    try:
        reader, writer = await asyncio.wait_for(
            asyncio.open_connection(ip, GIZWITS_TCP_PORT),
            timeout=5.0
        )
    except Exception as e:
        print(f"  Connection failed: {e}")
        return

    print(f"  Connected to {ip}:{GIZWITS_TCP_PORT}")

    async def read_response(timeout=3.0):
        """Read and parse a response"""
        try:
            data = await asyncio.wait_for(reader.read(4096), timeout=timeout)
            if data:
                parsed = parse_lan_packet(data)
                if parsed:
                    print(f"    <- CMD {parsed['cmd_hex']}, {len(data)}B: {data.hex()[:80]}")
                    return parsed
                else:
                    print(f"    <- Raw: {data.hex()[:80]}")
            return None
        except asyncio.TimeoutError:
            print(f"    <- (no response within {timeout}s)")
            return None

    try:
        # Step 1: Try passcode exchange (same as BLE)
        print("\n  [1] Requesting passcode (cmd 0x0006)...")
        writer.write(build_lan_packet(0x0006))
        await writer.drain()
        resp = await read_response()

        passcode = None
        if resp and resp['cmd'] == 0x0007 and resp['payload']:
            passcode = resp['payload']
            print(f"  Passcode received: {passcode.hex()}")

        # Step 2: Login
        if passcode:
            print("\n  [2] Logging in (cmd 0x0008)...")
            writer.write(build_lan_packet(0x0008, passcode))
            await writer.drain()
            resp = await read_response()

            if resp and resp['cmd'] == 0x0009:
                if resp['payload'] and resp['payload'][0] == 0x00:
                    print("  Login successful!")
                else:
                    print(f"  Login response: {resp['payload'].hex() if resp['payload'] else 'empty'}")

        # Step 3: Read status
        print("\n  [3] Reading status (cmd 0x0093, action 0x02)...")
        cmd_sn = int(time.time())
        status_p0 = cmd_sn.to_bytes(4, 'big') + bytes([0x02, 0x00])
        writer.write(build_lan_packet(0x0093, status_p0))
        await writer.drain()

        # Read multiple responses (status might be large or split)
        status_data = None
        for _ in range(5):
            resp = await read_response(timeout=2.0)
            if resp:
                if resp['cmd'] == 0x0100 or (resp['cmd'] == 0x0093 and len(resp['payload']) > 20):
                    status_data = resp
                    print(f"  Status data received! {len(resp['raw'])} bytes")
                    if len(resp['raw']) > 12 + 27:
                        speed = resp['raw'][12 + 27]
                        print(f"  Current speed (pos 27): {speed}%")
            else:
                break

        # Step 4: Try WiFi-specific control commands
        # The jrigling integration uses cmd 0x0090 for WiFi control
        print("\n  [4] Testing WiFi control commands...")

        wifi_test_formats = []

        # Format 1: cmd 0x0090 (WiFi equivalent of BLE 0x0093)
        if status_data and len(status_data['raw']) > 12:
            full_p0 = status_data['raw'][12:]
            modified = bytearray(full_p0)
            modified[0] = 0x01  # write action
            modified[27] = 55  # target speed
            wifi_test_formats.append((
                "WiFi cmd 0x0090 + modified status",
                0x0090,
                cmd_sn.to_bytes(4, 'big') + bytes(modified)
            ))

        # Format 2: cmd 0x0093 with modified status (same as BLE)
        if status_data and len(status_data['raw']) > 12:
            wifi_test_formats.append((
                "cmd 0x0093 + modified status (BLE-style)",
                0x0093,
                cmd_sn.to_bytes(4, 'big') + bytes(modified)
            ))

        # Format 3: Simple control via 0x0090
        wifi_test_formats.append((
            "cmd 0x0090 + action 0x01 + speed",
            0x0090,
            cmd_sn.to_bytes(4, 'big') + bytes([0x01, 0x00, 55])
        ))

        for desc, cmd_code, payload in wifi_test_formats:
            print(f"\n  Testing: {desc}")
            print(f"    Payload ({len(payload)}B): {payload[:32].hex()}...")
            writer.write(build_lan_packet(cmd_code, payload))
            await writer.drain()
            resp = await read_response()

            # Check if speed changed
            await asyncio.sleep(1.0)
            print("    Re-reading status...")
            verify_sn = int(time.time())
            writer.write(build_lan_packet(0x0093, verify_sn.to_bytes(4, 'big') + bytes([0x02, 0x00])))
            await writer.drain()
            for _ in range(3):
                resp = await read_response(timeout=2.0)
                if resp and len(resp['raw']) > 12 + 27:
                    new_speed = resp['raw'][12 + 27]
                    if new_speed == 55:
                        print(f"    *** SUCCESS! Speed changed to {new_speed}% ***")
                        print(f"    *** Working format: {desc} ***")
                    else:
                        print(f"    Speed still {new_speed}%")
                    break

        # Step 5: Listen for any spontaneous messages
        print("\n  [5] Listening for spontaneous messages (10s)...")
        for _ in range(5):
            resp = await read_response(timeout=2.0)

    except Exception as e:
        print(f"  Error: {e}")
        import traceback
        traceback.print_exc()
    finally:
        writer.close()
        try:
            await writer.wait_closed()
        except:
            pass
    print("  Connection closed.")


async def main():
    print("=" * 60)
    print("MDP-5000 WiFi Protocol Test")
    print("=" * 60)
    print(f"Pump BLE name: Jebao_WiFi-b17c")
    print(f"Target TCP port: {GIZWITS_TCP_PORT}")
    print()

    if PUMP_IP:
        print(f"Using configured IP: {PUMP_IP}")
        devices = [PUMP_IP]
    else:
        devices = await discover_pump()

    if not devices:
        print("\nNo devices found on the network.")
        print("\nTroubleshooting:")
        print("  1. Make sure the pump is connected to your WiFi network")
        print("     (use the Jebao app to configure WiFi first)")
        print("  2. Check your router's DHCP table for a device named 'Jebao' or 'ESP'")
        print("  3. Try setting PUMP_IP manually at the top of this script")
        print("  4. Make sure your computer is on the same subnet as the pump")
        return

    print(f"\nFound {len(devices)} potential device(s): {devices}")

    for ip in devices:
        await try_tcp_connection(ip)

    print("\n" + "=" * 60)
    print("SUMMARY")
    print("=" * 60)
    print("If TCP connection worked, the WiFi protocol bypasses all BLE")
    print("limitations. Next steps:")
    print("  1. Use Wireshark to capture app traffic on port 12416")
    print("  2. Filter: tcp.port == 12416")
    print("  3. Control the pump with the app while capturing")
    print("  4. The captured packets will show the exact write format")


if __name__ == "__main__":
    asyncio.run(main())
