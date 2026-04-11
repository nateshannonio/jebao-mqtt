#!/usr/bin/env python3
"""
Test very simple commands without power bit
Try to find ANY working control command
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

async def test_simple_commands():
    print(f"🔧 Testing Simplest Possible Commands")
    print(f"Goal: Find ANY command that works and controls the pump")
    print(f"Connecting to {MDP_MAC}...")
    
    responses = []
    
    def handler(sender, data):
        timestamp = time.time()
        print(f"[{timestamp:.1f}] RX: {data.hex()}")
        responses.append(data)
        
        if len(data) >= 8:
            cmd = int.from_bytes(data[6:8], 'big')
            if cmd == 0x0094:
                print(f"  ✅ ACK")
    
    try:
        async with BleakClient(MDP_MAC) as client:
            print("✅ Connected!")
            await client.start_notify(CHAR_UUID, handler)
            
            # Authentication
            print("\n=== AUTHENTICATION ===")
            get_pass = build_packet(0x06, b'')
            await client.write_gatt_char(CHAR_UUID, get_pass)
            await asyncio.sleep(0.5)
            
            if responses:
                resp = responses[-1]
                if len(resp) > 8:
                    passcode = resp[8:]
                    print(f"Passcode: {passcode.hex()}")
                    
                    login = build_packet(0x08, passcode)
                    await client.write_gatt_char(CHAR_UUID, login)
                    await asyncio.sleep(1.0)
                    print("Login complete\n")
            
            print("=== TESTING SIMPLE COMMANDS ===")
            
            # Test 1: Minimal commands
            simple_tests = [
                (bytes([0x01, 0x00]), "Action 0x01, no flag"),
                (bytes([0x00, 0x00]), "All zeros"),
                (bytes([0x01]), "Just action"),
                (bytes([0x00]), "Just zero"),
                (bytes([80]), "Just value 80"),
                (bytes([50]), "Just value 50"),
            ]
            
            for pattern, desc in simple_tests:
                print(f"\nTesting: {desc}")
                cmd_sn = int(time.time()) + len(pattern)
                payload = cmd_sn.to_bytes(4, 'big') + pattern
                cmd = build_packet(0x93, payload)
                
                print(f"Pattern: {pattern.hex()} | TX: {cmd.hex()}")
                
                try:
                    await client.write_gatt_char(CHAR_UUID, cmd)
                    print("📤 Sent")
                    await asyncio.sleep(2.0)
                    
                    if client.is_connected:
                        print("✅ Safe command")
                        print("❓ Any pump changes?")
                    else:
                        print("❌ Disconnected")
                        break
                except Exception as e:
                    print(f"❌ Error: {e}")
                    break
                    
            # Test 2: Try copying successful patterns from other tests
            if client.is_connected:
                print(f"\n=== TRYING KNOWN SAFE PATTERNS ===")
                
                # These worked in previous tests
                safe_patterns = [
                    (bytes([0x02, 0x00]), "Action 0x02 (worked before)"),
                    (bytes([0x03, 0x00]), "Action 0x03 (worked before)"),
                ]
                
                for pattern, desc in safe_patterns:
                    print(f"\nTesting: {desc}")
                    cmd_sn = int(time.time()) + 1000
                    payload = cmd_sn.to_bytes(4, 'big') + pattern
                    cmd = build_packet(0x93, payload)
                    
                    print(f"TX: {cmd.hex()}")
                    
                    try:
                        await client.write_gatt_char(CHAR_UUID, cmd)
                        print("📤 Sent known safe pattern")
                        await asyncio.sleep(3.0)
                        
                        if client.is_connected:
                            print("✅ Pattern confirmed safe")
                            print("❓ Any visible changes on pump?")
                        else:
                            print("❌ Pattern failed this time")
                            break
                    except Exception as e:
                        print(f"❌ Error: {e}")
                        break
            
            await client.stop_notify(CHAR_UUID)
            
    except Exception as e:
        print(f"❌ Connection error: {e}")
    
    print(f"\n📊 Results:")
    print(f"Responses: {len(responses)}")
    print("🎯 Did ANY command cause visible changes?")
    print("🔍 This will help us understand what commands actually work!")

if __name__ == "__main__":
    asyncio.run(test_simple_commands())