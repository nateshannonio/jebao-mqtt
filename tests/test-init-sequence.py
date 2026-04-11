#!/usr/bin/env python3
"""
Test if pump needs initialization sequence or control mode activation
Some IoT devices require specific handshake before accepting control commands
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

async def test_init_sequences():
    print("🔐 Testing Initialization Sequences")
    print("Theory: Pump might need special init before accepting control")
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
                if len(data) > 39:
                    speed_byte = data[39]
                    print(f"  🎯 Current speed: {speed_byte}%")
    
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
            
            print("=== TESTING INIT SEQUENCES ===")
            
            # Test 1: Try enabling notifications/subscriptions
            print("\n[1] Try subscription commands")
            subscribe_cmds = [
                (0x10, b'', "Subscribe command 0x10"),
                (0x11, b'', "Subscribe command 0x11"),
                (0x12, b'', "Subscribe command 0x12"),
            ]
            
            for cmd_code, payload, desc in subscribe_cmds:
                if not client.is_connected:
                    break
                print(f"  Testing: {desc}")
                cmd = build_packet(cmd_code, payload)
                try:
                    await client.write_gatt_char(CHAR_UUID, cmd)
                    await asyncio.sleep(1.0)
                except:
                    pass
            
            # Test 2: Try control mode activation
            print("\n[2] Try control mode activation")
            control_cmds = [
                (0x60, b'', "Control mode 0x60"),
                (0x61, b'', "Control mode 0x61"),
                (0x63, b'', "Control mode 0x63"),
                (0x64, b'', "Control mode 0x64"),
            ]
            
            for cmd_code, payload, desc in control_cmds:
                if not client.is_connected:
                    break
                print(f"  Testing: {desc}")
                cmd = build_packet(cmd_code, payload)
                try:
                    await client.write_gatt_char(CHAR_UUID, cmd)
                    await asyncio.sleep(1.0)
                except:
                    pass
            
            # Test 3: Now try control command after init
            if client.is_connected:
                print("\n[3] Trying control command after init sequence")
                print("  Target: Change speed to 85%")
                
                # Try simplest format
                cmd_sn = int(time.time())
                control = build_packet(0x93, cmd_sn.to_bytes(4, 'big') + bytes([85]))
                print(f"  TX: {control.hex()}")
                
                try:
                    await client.write_gatt_char(CHAR_UUID, control)
                    await asyncio.sleep(3.0)
                    
                    if client.is_connected:
                        print("  ✅ Command sent")
                        print("  ❓ Did pump speed change to 85%?")
                        
                        # Read status to verify
                        print("\n[4] Reading final status")
                        status_cmd = build_packet(0x93, int(time.time()).to_bytes(4, 'big') + bytes([0x02, 0x00]))
                        await client.write_gatt_char(CHAR_UUID, status_cmd)
                        await asyncio.sleep(2.0)
                    else:
                        print("  ❌ Disconnected")
                except Exception as e:
                    print(f"  ❌ Error: {e}")
            
            await client.stop_notify(CHAR_UUID)
            
    except Exception as e:
        print(f"❌ Connection error: {e}")
    
    print(f"\n📊 Summary:")
    print("Tested various initialization sequences")
    print("🎯 Did the pump speed change from 72% to 85%?")

if __name__ == "__main__":
    asyncio.run(test_init_sequences())