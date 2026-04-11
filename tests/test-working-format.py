#!/usr/bin/env python3
"""
Build on the working format - try variations that might actually control speed
Current: pump at 75%, commands get ACK but don't change speed
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

async def test_control_variations():
    print(f"🔧 Testing Control Command Variations")
    print(f"Current: Pump ON at 75% - commands get ACK but don't change speed")
    print(f"Goal: Find format that actually changes speed")
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
            
            print("=== TESTING SPEED CONTROL VARIATIONS ===")
            print("👀 Watch pump speed display for actual changes!")
            
            # Try different payload structures that might actually control speed
            speed_tests = [
                # Test 1: Try with action prefix
                (bytes([0x01, 90]), "Action 0x01 + Speed 90%"),
                
                # Test 2: Try with different action codes
                (bytes([0x02, 85]), "Action 0x02 + Speed 85%"),
                (bytes([0x03, 85]), "Action 0x03 + Speed 85%"),
                
                # Test 3: Try multi-byte speed formats
                (bytes([0x01, 0x00, 60]), "Action + Flag + Speed 60%"),
                (bytes([0x01, 0x01, 60]), "Action + Power + Speed 60%"),
                
                # Test 4: Try speed in different positions
                (bytes([90, 0x01]), "Speed 90% + Action"),
                (bytes([0x00, 85]), "Zero + Speed 85%"),
                
                # Test 5: Try larger payloads
                (bytes([0x01, 0x00, 0x00, 0x00, 95]), "Padded format + Speed 95%"),
                (bytes([0x01, 0x00, 0x00, 95, 0x00]), "Speed in middle position"),
                
                # Test 6: Try just different speeds with original working format
                (bytes([65]), "Just Speed 65%"),
                (bytes([85]), "Just Speed 85%"),
                (bytes([95]), "Just Speed 95%"),
            ]
            
            for i, (payload_data, desc) in enumerate(speed_tests):
                print(f"\n[{i+1}/{len(speed_tests)}] {desc}")
                
                cmd_sn = int(time.time()) + i
                payload = cmd_sn.to_bytes(4, 'big') + payload_data
                cmd = build_packet(0x93, payload)
                
                print(f"Payload: {payload_data.hex()}")
                print(f"TX: {cmd.hex()}")
                
                try:
                    await client.write_gatt_char(CHAR_UUID, cmd)
                    print("📤 Command sent")
                    
                    await asyncio.sleep(3.0)
                    
                    if client.is_connected:
                        print("✅ Command safe")
                        print("❓ Did pump speed change? Current speed reading?")
                        
                        # Give time to observe
                        await asyncio.sleep(1.0)
                    else:
                        print("❌ Command caused disconnection")
                        break
                        
                except Exception as e:
                    print(f"❌ Error: {e}")
                    break
            
            # Final test - try to turn pump OFF (most obvious change)
            if client.is_connected:
                print(f"\n[Final] Attempting to turn pump OFF")
                print("This should be the most obvious change if it works")
                
                off_tests = [
                    (bytes([0x00]), "Speed 0 (off)"),
                    (bytes([0x01, 0x00]), "Action + Off"),
                    (bytes([0xFF]), "Speed 255 (might be off)"),
                ]
                
                for payload_data, desc in off_tests:
                    print(f"\n[OFF Test] {desc}")
                    cmd_sn = int(time.time()) + 1000
                    payload = cmd_sn.to_bytes(4, 'big') + payload_data
                    cmd = build_packet(0x93, payload)
                    
                    print(f"TX: {cmd.hex()}")
                    
                    try:
                        await client.write_gatt_char(CHAR_UUID, cmd)
                        print("📤 OFF command sent")
                        await asyncio.sleep(4.0)
                        
                        if client.is_connected:
                            print("✅ OFF command safe")
                            print("❓ Did pump turn OFF?")
                        else:
                            print("❌ OFF command failed")
                            break
                    except Exception as e:
                        print(f"❌ OFF error: {e}")
                        break
            
            await client.stop_notify(CHAR_UUID)
            
    except Exception as e:
        print(f"❌ Connection error: {e}")
    
    print(f"\n📊 Test Results:")
    print(f"Commands tested: {len(speed_tests) + 3}")
    print(f"Responses received: {len(responses)}")
    print("\n🎯 KEY QUESTION:")
    print("Did ANY command cause visible pump speed changes?")
    print("What's the current pump status after all tests?")

if __name__ == "__main__":
    asyncio.run(test_control_variations())