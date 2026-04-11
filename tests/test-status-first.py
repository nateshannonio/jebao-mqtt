#!/usr/bin/env python3
"""
Try reading pump status first, then sending control commands
Maybe we need to query state before controlling
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

async def test_status_then_control():
    print(f"🔍 Testing: Status Query → Control Commands")
    print(f"Current pump state: ON at 75% speed")
    print(f"Connecting to {MDP_MAC}...")
    
    responses = []
    
    def handler(sender, data):
        timestamp = time.time()
        print(f"[{timestamp:.1f}] RX: {data.hex()}")
        responses.append(data)
        
        # Detailed parsing
        if len(data) >= 8:
            cmd = int.from_bytes(data[6:8], 'big')
            if cmd == 0x0094:
                print(f"  ✅ ACK")
            elif cmd == 0x0062:
                print(f"  📊 Status message")
                if len(data) > 12:
                    p0 = data[12:]
                    print(f"      P0 data: {p0.hex()}")
            elif cmd == 0x0093:
                print(f"  📨 Control response")
                if len(data) > 12:
                    p0 = data[12:]
                    print(f"      P0 data: {p0.hex()}")
    
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
            
            # Step 1: Try to query pump status
            print("=== QUERYING PUMP STATUS ===")
            
            status_commands = [
                (0x62, b'', "Status query 0x62"),
                (0x61, b'', "Status query 0x61"), 
                (0x63, b'', "Status query 0x63"),
                (0x90, b'', "Query command 0x90"),
                (0x91, b'', "Query command 0x91"),
            ]
            
            for cmd_code, payload_data, desc in status_commands:
                if not client.is_connected:
                    break
                    
                print(f"\n[Query] {desc}")
                cmd = build_packet(cmd_code, payload_data)
                print(f"TX: {cmd.hex()}")
                
                try:
                    await client.write_gatt_char(CHAR_UUID, cmd)
                    print("📤 Query sent")
                    await asyncio.sleep(2.0)
                    
                    if client.is_connected:
                        print("✅ Query safe")
                    else:
                        print("❌ Query caused disconnection")
                        break
                except Exception as e:
                    print(f"❌ Query error: {e}")
                    continue
            
            # Step 2: Now try control commands (if still connected)
            if client.is_connected:
                print(f"\n=== ATTEMPTING CONTROL COMMANDS ===")
                print("Now that we've queried status, try control...")
                
                # Wait a bit after status queries
                await asyncio.sleep(2.0)
                
                # Try the simplest possible control command
                print(f"\n[Control] Attempting speed change to 70%")
                
                # Use the simplest format that might work
                simple_speed = build_packet(0x93, int(time.time()).to_bytes(4, 'big') + bytes([70]))
                print(f"TX: {simple_speed.hex()}")
                
                try:
                    await client.write_gatt_char(CHAR_UUID, simple_speed)
                    print("📤 Control command sent")
                    await asyncio.sleep(3.0)
                    
                    if client.is_connected:
                        print("✅ Control command didn't disconnect!")
                        print("❓ Did pump speed change to 70%?")
                        
                        # Try another command
                        print(f"\n[Control] Attempting speed change to 80%")
                        speed80 = build_packet(0x93, int(time.time()).to_bytes(4, 'big') + bytes([80]))
                        await client.write_gatt_char(CHAR_UUID, speed80)
                        await asyncio.sleep(3.0)
                        
                        if client.is_connected:
                            print("✅ Second control command also worked!")
                            print("❓ Did pump speed change to 80%?")
                        else:
                            print("❌ Second control command failed")
                    else:
                        print("❌ Control command caused disconnection")
                        
                except Exception as e:
                    print(f"❌ Control command error: {e}")
            
            await client.stop_notify(CHAR_UUID)
            
    except Exception as e:
        print(f"❌ Connection error: {e}")
    
    print(f"\n📊 Results:")
    print(f"Total responses: {len(responses)}")
    print("\n🎯 Critical Questions:")
    print("1. Did any query commands return useful status data?")
    print("2. Did the control commands work AFTER querying status?") 
    print("3. Did you see any speed changes (75% → 70% → 80%)?")

if __name__ == "__main__":
    asyncio.run(test_status_then_control())