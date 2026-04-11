#!/usr/bin/env python3
"""
Test stable MDP control with verified command formats
Current state: ON at 75% speed
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

def make_mdp_command(action_type: str, value: int = None) -> bytes:
    """Create stable MDP command using tested formats"""
    command_sn = int(time.time())
    
    if action_type == "speed":
        # Format 1 from tests: action + flag + speed_value (most reliable)
        payload = bytes([0x01, 0x00, value])  # action=0x01, flag=0x00, speed=value
    elif action_type == "power_on":
        # Format 4 from tests: simple power on 
        payload = bytes([0x01, 0x01])  # action=0x01, flag=0x01
    elif action_type == "power_off":
        # Format 4 from tests: simple power off
        payload = bytes([0x01, 0x00])  # action=0x01, flag=0x00
    else:
        # Fallback
        payload = bytes([0x01, 0x00])
    
    full_payload = command_sn.to_bytes(4, 'big') + payload
    return build_packet(0x93, full_payload)

async def test_stable_mdp():
    print(f"Testing stable MDP control (pump currently ON at 75%)")
    print(f"Connecting to {MDP_MAC}...")
    
    responses = []
    pump_disconnected = False
    
    def handler(sender, data):
        nonlocal pump_disconnected
        timestamp = time.time()
        print(f"[{timestamp:.3f}] RX: {data.hex()} (len={len(data)})")
        responses.append((timestamp, data))
        
        if len(data) >= 8:
            cmd = int.from_bytes(data[6:8], 'big')
            print(f"  CMD: 0x{cmd:04x}")
            
            if cmd == 0x0093 and len(data) > 12:
                p0 = data[12:]
                print(f"  P0:  {p0.hex()}")
    
    async with BleakClient(MDP_MAC) as client:
        try:
            print("Connected!")
            await client.start_notify(CHAR_UUID, handler)
            
            # Step 1: Authentication
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
            
            # Test sequence: speed changes first (safer)
            test_commands = [
                ("Change speed to 50%", make_mdp_command("speed", 50)),
                ("Change speed to 90%", make_mdp_command("speed", 90)),  
                ("Change speed to 65%", make_mdp_command("speed", 65)),
                ("Power OFF", make_mdp_command("power_off")),
                ("Wait 3 seconds", None),  # Pause
                ("Power ON", make_mdp_command("power_on")),
                ("Set speed to 75%", make_mdp_command("speed", 75)),
            ]
            
            print("=== TESTING STABLE MDP COMMANDS ===")
            for desc, cmd in test_commands:
                print(f"\n{desc}:")
                
                if cmd is None:
                    print("Waiting...")
                    await asyncio.sleep(3.0)
                    continue
                    
                print(f"TX: {cmd.hex()}")
                
                try:
                    await client.write_gatt_char(CHAR_UUID, cmd)
                    print("✅ Command sent successfully")
                    
                    await asyncio.sleep(2.0)
                    
                    if client.is_connected:
                        print("✅ Pump stayed connected")
                    else:
                        print("❌ Pump disconnected")
                        pump_disconnected = True
                        break
                        
                except Exception as e:
                    print(f"❌ Error: {e}")
                    pump_disconnected = True
                    break
                
            await client.stop_notify(CHAR_UUID)
            
        except Exception as e:
            print(f"Connection error: {e}")
    
    print(f"\nTest Results:")
    print(f"- Total responses: {len(responses)}")
    print(f"- Pump stayed connected: {'Yes' if not pump_disconnected else 'No'}")
    print(f"- Commands tested: {len([c for c in test_commands if c[1] is not None])}")

if __name__ == "__main__":
    asyncio.run(test_stable_mdp())