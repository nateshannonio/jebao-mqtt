#!/usr/bin/env python3
"""
Focused test of MDP feed mode - debug what's happening
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

def make_feed_test_commands():
    """Create different feed command variations to test"""
    command_sn = int(time.time())
    action = 0x01
    
    commands = {
        "Feed ON - Method 1 (Power+Feed bits)": bytes([action, 0x03]),  # Both power (bit 0) and feed (bit 1)
        "Feed ON - Method 2 (Just Feed bit)": bytes([action, 0x02]),    # Just feed (bit 1)
        "Feed ON - Method 3 (All flags)": bytes([action, 0xFF]),        # All flags set
        "Feed OFF - Method 1 (Just Power)": bytes([action, 0x01]),      # Just power (bit 0)
        "Feed OFF - Method 2 (Clear all)": bytes([action, 0x00]),       # Clear all
    }
    
    result = {}
    for desc, payload in commands.items():
        full_payload = command_sn.to_bytes(4, 'big') + payload
        result[desc] = build_packet(0x93, full_payload)
        command_sn += 1  # Different serial number for each
    
    return result

async def test_feed_modes():
    print(f"Testing MDP Feed Mode - Debug Session")
    print(f"Connecting to {MDP_MAC}...")
    
    responses = []
    
    def handler(sender, data):
        timestamp = time.time()
        print(f"[{timestamp:.3f}] RX: {data.hex()}")
        responses.append((timestamp, data))
        
        # Detailed parsing
        if len(data) >= 8:
            cmd = int.from_bytes(data[6:8], 'big')
            print(f"  CMD: 0x{cmd:04x}")
            
            if cmd == 0x0093 and len(data) > 12:
                p0 = data[12:]
                print(f"  P0 raw: {p0.hex()}")
                if len(p0) >= 2:
                    action = p0[0]
                    flag_byte = p0[1] 
                    print(f"  Action: 0x{action:02x}")
                    print(f"  Flags: 0x{flag_byte:02x} (binary: {format(flag_byte, '08b')})")
                    
                    # Parse individual bits
                    power_bit = (flag_byte & 0x01) != 0
                    feed_bit = (flag_byte & 0x02) != 0
                    print(f"  Power bit (0): {power_bit}")
                    print(f"  Feed bit (1): {feed_bit}")
                    
                    # Check for other bits
                    for i in range(2, 8):
                        if flag_byte & (1 << i):
                            print(f"  Bit {i}: SET")
    
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
            
            # Get current pump status first
            print("\n=== CURRENT PUMP STATUS ===")
            await asyncio.sleep(1.0)  # Wait for any status updates
            
            # Test feed commands
            print("\n=== TESTING FEED COMMANDS ===")
            feed_commands = make_feed_test_commands()
            
            for desc, cmd in feed_commands.items():
                print(f"\n--- {desc} ---")
                print(f"TX: {cmd.hex()}")
                
                try:
                    await client.write_gatt_char(CHAR_UUID, cmd)
                    print("✅ Command sent")
                    
                    # Wait for response and pump reaction
                    await asyncio.sleep(3.0)
                    
                    if client.is_connected:
                        print("✅ Connection stable")
                    else:
                        print("❌ Pump disconnected")
                        break
                        
                except Exception as e:
                    print(f"❌ Error: {e}")
                    break
                
                # Ask user to observe pump behavior
                print("👀 Observe pump behavior - what do you see?")
                print("   (Press Enter to continue to next command)")
                # Note: In automated testing, we'll just wait
                await asyncio.sleep(2.0)
            
            await client.stop_notify(CHAR_UUID)
            
        except Exception as e:
            print(f"Connection error: {e}")
    
    print(f"\n=== SUMMARY ===")
    print(f"Total responses: {len(responses)}")
    print("Feed mode test completed")

if __name__ == "__main__":
    asyncio.run(test_feed_modes())