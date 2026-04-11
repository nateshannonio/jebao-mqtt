#!/usr/bin/env python3
"""
Quick test script to send commands to MDP pump and see responses
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

def build_mdp_command(attrs: dict) -> bytes:
    """Build MDP command packet"""
    action = 0x01  # Write action
    flag_byte = 0x00
    values = []
    
    # Handle power (SwitchON) - bit 0
    if 'power' in attrs:
        flag_byte |= 0x01  # Set bit 0 to indicate SwitchON is being modified
        if attrs['power']:
            flag_byte |= 0x80  # Set the actual value bit
    
    # Handle speed - append value
    if 'speed' in attrs:
        values.append(attrs['speed'])
    
    payload = bytes([action, flag_byte]) + bytes(values)
    
    # Add command serial number (4 bytes) + P0 data
    command_sn = int(time.time()) % 0xFFFFFFFF
    full_payload = command_sn.to_bytes(4, 'big') + payload
    
    return build_packet(0x93, full_payload)

async def test_mdp_commands():
    responses = []
    
    def handler(sender, data):
        print(f"RX: {data.hex()} (len={len(data)})")
        responses.append(data)
        
        # Parse response
        if len(data) >= 8:
            cmd = int.from_bytes(data[6:8], 'big')
            print(f"  CMD: 0x{cmd:04x}")
            
            if cmd == 0x0093 and len(data) > 12:
                p0 = data[12:]
                print(f"  P0:  {p0.hex()}")
    
    print(f"Connecting to MDP at {MDP_MAC}...")
    
    async with BleakClient(MDP_MAC) as client:
        print("Connected!")
        
        # Ensure services are discovered  
        services = client.services
        
        await client.start_notify(CHAR_UUID, handler)
        
        # Step 1: Get passcode
        print("\n--- Getting passcode ---")
        get_pass = build_packet(0x06, b'')
        print(f"TX: {get_pass.hex()}")
        await client.write_gatt_char(CHAR_UUID, get_pass)
        await asyncio.sleep(0.5)
        
        if responses:
            resp = responses[-1]
            if len(resp) > 8:
                passcode = resp[8:]
                print(f"Passcode: {passcode.hex()}")
                
                # Step 2: Login
                print("\n--- Logging in ---")
                login_payload = passcode
                login = build_packet(0x08, login_payload)
                print(f"TX: {login.hex()}")
                await client.write_gatt_char(CHAR_UUID, login)
                await asyncio.sleep(1.0)
                
                if responses and len(responses) > 1:
                    print("Login successful!")
                    
                    # Step 3: Try power ON command
                    print("\n--- Sending Power ON ---")
                    power_on_cmd = build_mdp_command({'power': True})
                    print(f"TX: {power_on_cmd.hex()}")
                    await client.write_gatt_char(CHAR_UUID, power_on_cmd)
                    await asyncio.sleep(2.0)
                    
                    # Step 4: Try speed command
                    print("\n--- Sending Speed 70% ---")
                    speed_cmd = build_mdp_command({'speed': 70})
                    print(f"TX: {speed_cmd.hex()}")
                    await client.write_gatt_char(CHAR_UUID, speed_cmd)
                    await asyncio.sleep(2.0)
                    
                    # Step 5: Try power OFF command
                    print("\n--- Sending Power OFF ---")
                    power_off_cmd = build_mdp_command({'power': False})
                    print(f"TX: {power_off_cmd.hex()}")
                    await client.write_gatt_char(CHAR_UUID, power_off_cmd)
                    await asyncio.sleep(2.0)
        
        await client.stop_notify(CHAR_UUID)
        
    print(f"\nTotal responses received: {len(responses)}")

if __name__ == "__main__":
    asyncio.run(test_mdp_commands())