#!/usr/bin/env python3
"""
Test different command types to find the actual WRITE command
Based on Test4 analysis showing 0x02 returns status with current speed at position 27
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

async def test_commands():
    print("🔬 Testing Different Command Types")
    print("Current pump: 72% speed")
    print("Goal: Find command that actually changes speed to 85%")
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
            elif cmd == 0x0100:
                print(f"  📊 Status response")
                # Check for speed value at position 27 in payload
                if len(data) > 39:  # 12 header + 27 = 39
                    speed_byte = data[39]
                    print(f"  🎯 Speed value at position 27: {speed_byte}% (0x{speed_byte:02x})")
    
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
            
            print("=== TESTING WRITE COMMANDS ===")
            
            # Test 1: Read current status first
            print("\n[1] Reading current status (action 0x02)")
            cmd_sn = int(time.time())
            status_cmd = build_packet(0x93, cmd_sn.to_bytes(4, 'big') + bytes([0x02, 0x00]))
            await client.write_gatt_char(CHAR_UUID, status_cmd)
            await asyncio.sleep(2.0)
            
            # Test 2: Try different command codes instead of 0x93
            test_commands = [
                (0x91, bytes([85]), "Command 0x91 with speed 85%"),
                (0x92, bytes([85]), "Command 0x92 with speed 85%"),
                (0x95, bytes([85]), "Command 0x95 with speed 85%"),
                (0x96, bytes([85]), "Command 0x96 with speed 85%"),
                (0x93, bytes([0x01, 0x00, 85]), "Command 0x93 action 0x01 with flags + speed"),
                (0x93, bytes([0x03, 85]), "Command 0x93 action 0x03 + speed"),
                (0x93, bytes([0x04, 85]), "Command 0x93 action 0x04 + speed"),
            ]
            
            for cmd_code, payload_data, desc in test_commands:
                if not client.is_connected:
                    print("❌ Disconnected, stopping tests")
                    break
                
                print(f"\n[Test] {desc}")
                cmd_sn = int(time.time()) + 100
                
                if cmd_code == 0x93:
                    # Include command serial number for 0x93
                    payload = cmd_sn.to_bytes(4, 'big') + payload_data
                else:
                    # Try without serial number for other commands
                    payload = payload_data
                
                cmd = build_packet(cmd_code, payload)
                print(f"TX: {cmd.hex()}")
                
                try:
                    await client.write_gatt_char(CHAR_UUID, cmd)
                    print("📤 Sent")
                    await asyncio.sleep(3.0)
                    
                    if client.is_connected:
                        print("✅ Command safe")
                        print("❓ Did pump speed change to 85%?")
                    else:
                        print("❌ Command caused disconnection")
                        break
                        
                except Exception as e:
                    print(f"❌ Error: {e}")
                    break
            
            # Final status check
            if client.is_connected:
                print("\n[Final] Reading status again to check if speed changed")
                cmd_sn = int(time.time()) + 1000
                status_cmd = build_packet(0x93, cmd_sn.to_bytes(4, 'big') + bytes([0x02, 0x00]))
                await client.write_gatt_char(CHAR_UUID, status_cmd)
                await asyncio.sleep(2.0)
            
            await client.stop_notify(CHAR_UUID)
            
    except Exception as e:
        print(f"❌ Connection error: {e}")
    
    print(f"\n📊 Test complete")
    print("🎯 Key question: Did the pump speed change from 72% to 85%?")

if __name__ == "__main__":
    asyncio.run(test_commands())