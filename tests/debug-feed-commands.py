#!/usr/bin/env python3
"""
Debug MDP feed mode commands - find the correct format
Based on earlier observation that some command triggered feed mode
"""

import asyncio
import time
from bleak import BleakClient

# Your MDP pump MAC
MDP_MAC = "7725528E-75A8-F1C3-71E6-CEF9A6EDA5EE"
SERVICE_UUID = "0000abf0-0000-1000-8000-00805f9b34fb"
CHAR_UUID = "0000abf7-0000-1000-8000-00805f9b34fb"

def build_packet(cmd: int, payload: bytes) -> bytes:
    """Build Gizwits BLE packet"""
    length = 3 + len(payload)
    return bytes([0x00, 0x00, 0x00, 0x03, length, 0x00]) + cmd.to_bytes(2, 'big') + payload

def create_feed_test_commands():
    """Create various command formats to test for feed mode"""
    base_sn = int(time.time())
    
    commands = {}
    
    # Test different bit positions for feed mode
    for bit_pos in range(2, 8):  # Test bits 2-7 (we know 0=power, 1 didn't work)
        flag_value = (1 << 0) | (1 << bit_pos)  # Power + feed bit
        cmd_sn = base_sn + bit_pos
        payload = cmd_sn.to_bytes(4, 'big') + bytes([0x01, flag_value])
        commands[f"Feed test - Bit {bit_pos} (0x{flag_value:02x})"] = build_packet(0x93, payload)
    
    # Test specific flag combinations that might indicate feed mode
    special_flags = [
        (0x04, "Feed bit 2 only"),
        (0x08, "Feed bit 3 only"), 
        (0x10, "Feed bit 4 only"),
        (0x05, "Power + bit 2"),
        (0x09, "Power + bit 3"),
        (0x11, "Power + bit 4"),
        (0x03, "Power + bit 1 (our current)"),
        (0x07, "Power + bit 1 + bit 2"),
        (0x0F, "Multiple bits"),
    ]
    
    for flag, desc in special_flags:
        cmd_sn = base_sn + 100 + flag
        payload = cmd_sn.to_bytes(4, 'big') + bytes([0x01, flag])
        commands[f"Special test - {desc}"] = build_packet(0x93, payload)
    
    # Test action variations (maybe feed mode uses different action)
    for action in [0x02, 0x03, 0x04, 0x05]:
        cmd_sn = base_sn + 200 + action
        payload = cmd_sn.to_bytes(4, 'big') + bytes([action, 0x01])  # Power bit with different action
        commands[f"Action test - 0x{action:02x}"] = build_packet(0x93, payload)
    
    # Test the original formats that worked from our earlier test
    cmd_sn = base_sn + 300
    # Recreate the successful formats from test-mdp-formats.py that might have triggered feed
    original_tests = [
        ("Recreate Format 1", bytes([0x01, 0x00, 50])),  # This was bridge format
        ("Recreate Format 2", bytes([0x01, 50])),        # Simple action+value
        ("Recreate Format 3", bytes([50])),              # Just value
        ("Recreate Format 6", bytes([0x01, 0x00, 0x00, 0x00, 0x00, 50])),  # Original style
    ]
    
    for desc, payload_data in original_tests:
        payload = cmd_sn.to_bytes(4, 'big') + payload_data
        commands[desc] = build_packet(0x93, payload)
        cmd_sn += 1
    
    return commands

async def debug_feed_commands():
    print(f"Debugging MDP feed mode commands")
    print(f"Goal: Find the command that actually triggers feed mode")
    print(f"Connecting to {MDP_MAC}...")
    
    responses = []
    successful_commands = []
    
    def handler(sender, data):
        timestamp = time.time()
        print(f"[{timestamp:.3f}] RX: {data.hex()}")
        responses.append((timestamp, data))
        
        if len(data) >= 8:
            cmd = int.from_bytes(data[6:8], 'big')
            if cmd == 0x0093:
                print(f"  ACK received")
    
    async with BleakClient(MDP_MAC) as client:
        try:
            print("Connected!")
            await client.start_notify(CHAR_UUID, handler)
            
            # Authentication
            print("\n=== AUTHENTICATION ===")
            get_pass = build_packet(0x06, b'')
            await client.write_gatt_char(CHAR_UUID, get_pass)
            await asyncio.sleep(0.5)
            
            if responses:
                resp = responses[-1][1]
                if len(resp) > 8:
                    passcode = resp[8:]
                    print(f"Passcode: {passcode.hex()}")
                    
                    login = build_packet(0x08, passcode)
                    await client.write_gatt_char(CHAR_UUID, login)
                    await asyncio.sleep(1.0)
                    print("Login complete\n")
            
            print("=== TESTING FEED MODE COMMANDS ===")
            print("Watch pump carefully for any behavior changes")
            print("(speed changes, LED changes, different sound, etc.)")
            
            test_commands = create_feed_test_commands()
            
            for i, (desc, cmd) in enumerate(test_commands.items()):
                print(f"\n[{i+1}/{len(test_commands)}] {desc}")
                print(f"TX: {cmd.hex()}")
                
                try:
                    await client.write_gatt_char(CHAR_UUID, cmd)
                    print("✅ Sent")
                    
                    # Wait and check if pump behavior changed
                    await asyncio.sleep(2.0)
                    
                    if client.is_connected:
                        successful_commands.append((desc, cmd.hex()))
                        print("✅ Connection stable")
                    else:
                        print("❌ Pump disconnected")
                        break
                        
                except Exception as e:
                    print(f"❌ Error: {e}")
                    break
                    
                # Short pause between commands
                await asyncio.sleep(0.5)
            
            await client.stop_notify(CHAR_UUID)
            
        except Exception as e:
            print(f"Connection error: {e}")
    
    print(f"\n=== RESULTS ===")
    print(f"Commands tested: {len(test_commands)}")
    print(f"Successful commands: {len(successful_commands)}")
    print(f"Total responses: {len(responses)}")
    print("\nAll successful commands:")
    for desc, hex_cmd in successful_commands:
        print(f"  {desc}: {hex_cmd}")

if __name__ == "__main__":
    asyncio.run(debug_feed_commands())