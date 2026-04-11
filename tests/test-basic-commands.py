#!/usr/bin/env python3
"""
Test basic pump commands to verify they're working
Speed 80, Power OFF, Power ON, Speed 85
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

def make_speed_command(speed: int) -> bytes:
    """Create speed command (power + speed)"""
    command_sn = int(time.time())
    action = 0x01
    flag_byte = 0x01  # Power bit
    
    payload = bytes([action, flag_byte, speed])
    full_payload = command_sn.to_bytes(4, 'big') + payload
    return build_packet(0x93, full_payload)

def make_power_command(on: bool) -> bytes:
    """Create power on/off command"""
    command_sn = int(time.time())
    action = 0x01
    flag_byte = 0x01 if on else 0x00  # Power bit
    
    payload = bytes([action, flag_byte])
    full_payload = command_sn.to_bytes(4, 'big') + payload
    return build_packet(0x93, full_payload)

async def test_basic_commands():
    print(f"🧪 Testing Basic MDP Commands")
    print(f"Sequence: Speed 80 → Power OFF → Power ON → Speed 85")
    print(f"Connecting to {MDP_MAC}...")
    
    responses = []
    
    def handler(sender, data):
        timestamp = time.time()
        print(f"[{timestamp:.1f}] RX: {data.hex()}")
        responses.append(data)
        
        if len(data) >= 8:
            cmd = int.from_bytes(data[6:8], 'big')
            if cmd == 0x0094:
                print(f"  ✅ ACK received")
            elif cmd == 0x0062:
                print(f"  📊 Status update")
    
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
            
            # Test sequence
            commands = [
                ("Set Speed to 80%", make_speed_command(80)),
                ("Power OFF", make_power_command(False)),
                ("Power ON", make_power_command(True)),
                ("Set Speed to 85%", make_speed_command(85)),
            ]
            
            print("=== TESTING BASIC COMMANDS ===")
            print("👀 Watch pump for changes!")
            
            for i, (desc, cmd) in enumerate(commands):
                print(f"\n[{i+1}/4] {desc}")
                print(f"TX: {cmd.hex()}")
                
                try:
                    await client.write_gatt_char(CHAR_UUID, cmd)
                    print("📤 Command sent")
                    
                    # Wait and observe
                    await asyncio.sleep(3.0)
                    
                    if client.is_connected:
                        print("✅ Connection stable")
                        
                        # Ask for observation
                        if "Speed 80" in desc:
                            print("❓ Did pump speed change to 80%?")
                        elif "Power OFF" in desc:
                            print("❓ Did pump turn OFF completely?")
                        elif "Power ON" in desc:
                            print("❓ Did pump turn ON again?")
                        elif "Speed 85" in desc:
                            print("❓ Did pump speed change to 85%?")
                            
                    else:
                        print("❌ Connection lost - command may have failed")
                        break
                        
                except Exception as e:
                    print(f"❌ Error: {e}")
                    break
                
                # Pause between commands
                await asyncio.sleep(1.0)
            
            # Try one more test - a safe speed change
            if client.is_connected:
                print(f"\n[Extra] Set Speed to 70% (final test)")
                final_cmd = make_speed_command(70)
                print(f"TX: {final_cmd.hex()}")
                
                try:
                    await client.write_gatt_char(CHAR_UUID, final_cmd)
                    print("📤 Final command sent")
                    await asyncio.sleep(3.0)
                    
                    if client.is_connected:
                        print("✅ Final command successful")
                        print("❓ Did speed change to 70%?")
                    else:
                        print("❌ Final command failed")
                        
                except Exception as e:
                    print(f"❌ Final command error: {e}")
            
            await client.stop_notify(CHAR_UUID)
            
    except Exception as e:
        print(f"❌ Connection error: {e}")
    
    print(f"\n📊 Test Results:")
    print(f"Total responses: {len(responses)}")
    print(f"Commands attempted: 4-5")
    print("\n🎯 Summary:")
    print("- Speed 80%: Working? ❓")
    print("- Power OFF: Working? ❓") 
    print("- Power ON: Working? ❓")
    print("- Speed 85%: Working? ❓")

if __name__ == "__main__":
    asyncio.run(test_basic_commands())