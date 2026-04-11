#!/usr/bin/env python3
"""
Test different MDP command formats to find the one that works
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

async def test_command_formats():
    print(f"Testing MDP command formats with pump at ON/75%")
    print(f"Connecting to {MDP_MAC}...")
    
    responses = []
    
    def handler(sender, data):
        timestamp = time.time()
        print(f"[{timestamp:.3f}] RX: {data.hex()} (len={len(data)})")
        responses.append((timestamp, data))
        
        # Parse response
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
            
            # Current state: ON at 75%
            # Let's try different command formats to change speed to 50%
            
            command_tests = [
                # Format 1: Current bridge format (action + flag)
                ("Bridge format - Speed 50%", 
                 build_packet(0x93, int(time.time()).to_bytes(4, 'big') + bytes([0x01, 0x00, 50]))),
                
                # Format 2: Simple action + value  
                ("Simple action+value - Speed 50%",
                 build_packet(0x93, int(time.time()).to_bytes(4, 'big') + bytes([0x01, 50]))),
                
                # Format 3: Just the speed value
                ("Just speed value - Speed 50%",
                 build_packet(0x93, int(time.time()).to_bytes(4, 'big') + bytes([50]))),
                
                # Format 4: Power OFF command (simple)
                ("Power OFF - Simple",
                 build_packet(0x93, int(time.time()).to_bytes(4, 'big') + bytes([0x01, 0x00]))),
                
                # Format 5: Power OFF with flag
                ("Power OFF - With flag", 
                 build_packet(0x93, int(time.time()).to_bytes(4, 'big') + bytes([0x01, 0x01]))),
                
                # Format 6: Try original mdp_test.py style
                ("Original test style - Speed 50%",
                 build_packet(0x93, int(time.time()).to_bytes(4, 'big') + bytes([0x01, 0x00, 0x00, 0x00, 0x00, 50]))),
            ]
            
            print("=== TESTING COMMAND FORMATS ===")
            for desc, cmd in command_tests:
                print(f"\nTest: {desc}")
                print(f"TX: {cmd.hex()}")
                
                try:
                    await client.write_gatt_char(CHAR_UUID, cmd)
                    print("Command sent successfully")
                    
                    # Wait and see if pump stays connected
                    await asyncio.sleep(2.0)
                    
                    if client.is_connected:
                        print("✅ Pump stayed connected")
                    else:
                        print("❌ Pump disconnected")
                        break
                        
                except Exception as e:
                    print(f"❌ Error sending command: {e}")
                    break
                
            await client.stop_notify(CHAR_UUID)
            
        except Exception as e:
            print(f"Connection error: {e}")
    
    print(f"\nTotal responses: {len(responses)}")
    print("=== Response Summary ===")
    for i, (ts, data) in enumerate(responses):
        cmd = int.from_bytes(data[6:8], 'big') if len(data) >= 8 else 0
        print(f"{i+1}. [{ts:.3f}] CMD 0x{cmd:04x}: {data.hex()}")

if __name__ == "__main__":
    asyncio.run(test_command_formats())