#!/usr/bin/env python3
"""
Alternative approach to feed mode testing
Since individual bits cause disconnection, try different approaches:
1. Different command codes (not 0x93)
2. Special value patterns
3. Multi-byte sequences
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

async def test_alternative_feed():
    print(f"🔧 Alternative Feed Mode Testing")
    print(f"Trying different command approaches")
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
            elif cmd == 0x0062:
                print(f"  📊 Status")
    
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
            
            print("=== ALTERNATIVE APPROACHES ===")
            
            # Test 1: Different command codes
            print(f"\n1️⃣ Testing different command codes")
            
            alt_commands = [
                (0x91, "Command 0x91"),
                (0x92, "Command 0x92"), 
                (0x94, "Command 0x94"),
                (0x95, "Command 0x95"),
            ]
            
            for cmd_code, desc in alt_commands:
                print(f"\n[{desc}]")
                cmd_sn = int(time.time()) + cmd_code
                payload = cmd_sn.to_bytes(4, 'big') + bytes([0x01, 0x00])  # Simple payload
                cmd = build_packet(cmd_code, payload)
                
                print(f"TX: {cmd.hex()}")
                
                try:
                    await client.write_gatt_char(CHAR_UUID, cmd)
                    print("📤 Sent")
                    await asyncio.sleep(3.0)
                    
                    if client.is_connected:
                        print("✅ Safe command")
                        print("❓ Any display changes?")
                    else:
                        print("❌ Disconnected")
                        break
                except Exception as e:
                    print(f"❌ Error: {e}")
                    break
            
            # Test 2: Special 0x93 patterns that might be feed mode
            if client.is_connected:
                print(f"\n2️⃣ Testing special 0x93 patterns")
                
                special_patterns = [
                    (bytes([0x02, 0x00]), "Action 0x02"),  # Different action
                    (bytes([0x03, 0x00]), "Action 0x03"),
                    (bytes([0x01, 0x00, 0x00]), "Zero flag + extra byte"),
                    (bytes([0x01, 0x00, 0x01]), "Zero flag + 0x01"),
                    (bytes([0x01, 0x00, 0xFF]), "Zero flag + 0xFF"),
                    (bytes([0xFF, 0x00]), "Action 0xFF"),
                    (bytes([0x00, 0x00]), "All zeros"),
                ]
                
                for pattern, desc in special_patterns:
                    print(f"\n[Special] {desc}")
                    cmd_sn = int(time.time()) + len(pattern)
                    payload = cmd_sn.to_bytes(4, 'big') + pattern
                    cmd = build_packet(0x93, payload)
                    
                    print(f"TX: {cmd.hex()}")
                    
                    try:
                        await client.write_gatt_char(CHAR_UUID, cmd)
                        print("📤 Sent special pattern")
                        await asyncio.sleep(3.0)
                        
                        if client.is_connected:
                            print("✅ Pattern safe")
                            print("❓ 'FEED' display? Timer?")
                        else:
                            print("❌ Pattern caused disconnection")
                            break
                    except Exception as e:
                        print(f"❌ Error: {e}")
                        break
            
            # Test 3: Try to trigger with known safe speed command then modify
            if client.is_connected:
                print(f"\n3️⃣ Testing speed command variations")
                
                # First, a normal speed command we know works
                print("Normal speed command (baseline):")
                cmd_sn = int(time.time()) + 1000
                payload = cmd_sn.to_bytes(4, 'big') + bytes([0x01, 0x01, 50])  # Power + speed
                cmd = build_packet(0x93, payload)
                
                print(f"TX: {cmd.hex()}")
                await client.write_gatt_char(CHAR_UUID, cmd)
                await asyncio.sleep(2.0)
                
                if client.is_connected:
                    print("✅ Speed command works")
                    
                    # Now try variations that might be feed
                    variations = [
                        (bytes([0x01, 0x01, 0x00]), "Speed 0 (stop)"),  # Maybe feed = speed 0?
                        (bytes([0x01, 0x01, 0xFF]), "Speed 255"),
                        (bytes([0x01, 0x00, 0x00, 0x01]), "Extra feed byte"),
                    ]
                    
                    for var_payload, desc in variations:
                        print(f"\n[Variation] {desc}")
                        cmd_sn = int(time.time()) + 2000
                        payload = cmd_sn.to_bytes(4, 'big') + var_payload
                        cmd = build_packet(0x93, payload)
                        
                        print(f"TX: {cmd.hex()}")
                        await client.write_gatt_char(CHAR_UUID, cmd)
                        await asyncio.sleep(3.0)
                        
                        if client.is_connected:
                            print("✅ Variation safe")
                            print("❓ Feed mode triggered?")
                        else:
                            print("❌ Variation failed")
                            break
            
            await client.stop_notify(CHAR_UUID)
            
    except Exception as e:
        print(f"❌ Connection error: {e}")
    
    print(f"\n📊 Test Results:")
    print(f"Total responses: {len(responses)}")
    print("🎯 Which approach triggered 'FEED' mode?")

if __name__ == "__main__":
    asyncio.run(test_alternative_feed())