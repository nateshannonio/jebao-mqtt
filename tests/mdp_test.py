#!/usr/bin/env python3
"""
MDP-5000 Control Protocol Test

Based on Gizwits protocol analysis:
- Attribute ID 0: SwitchON (bool) - Power
- Attribute ID 5: Motor_Speed (uint8) - Speed 30-100

P0 Write command format (Gizwits):
  [action=0x01] [0x00] [0x00] [attr_flags...] [values...]

attr_flags is a bitmap where bit N = 1 means attribute N is being set
For bool attrs: packed into flag bytes
For uint8 attrs: value follows flags
"""

import asyncio
from bleak import BleakClient

MDP_MAC = "38:1F:8D:E1:28:52"  # Change to your MDP MAC
SERVICE_UUID = "0000abf0-0000-1000-8000-00805f9b34fb"
CHAR_UUID = "0000abf7-0000-1000-8000-00805f9b34fb"

def build_packet(cmd: int, payload: bytes) -> bytes:
    """Build Gizwits BLE packet: [00 00 00 03] [len] [00] [00 cmd] [payload]"""
    length = 3 + len(payload)  # cmd(2) + flag(1) + payload
    return bytes([0x00, 0x00, 0x00, 0x03, length, 0x00, 0x00, cmd]) + payload

def build_p0_write(attrs: dict) -> bytes:
    """
    Build P0 write command for MDP pump.
    
    attrs = {
        'SwitchON': True/False,  # bit 0
        'Motor_Speed': 0-100,     # attr id 5
    }
    """
    # Action byte: 0x01 = write
    action = 0x01
    
    # Build attribute flags (which attrs are being set)
    # Byte 0 bits: SwitchON(0), Mode(1), FeedSwitch(2), TimerON(3), AutoMode(4-6)
    # Byte 1+: uint8 values follow
    
    flag_byte = 0x00
    values = []
    
    if 'SwitchON' in attrs:
        flag_byte |= 0x01  # bit 0
        if attrs['SwitchON']:
            flag_byte |= 0x80  # Set value bit? Or separate?
    
    # For Motor_Speed (id 5), we need to indicate it's being set
    # and provide the value
    if 'Motor_Speed' in attrs:
        # Motor_Speed is uint8, id=5
        # Need to set flag and append value
        values.append(attrs['Motor_Speed'])
    
    # This is speculative - need to verify exact format
    payload = bytes([action, flag_byte]) + bytes(values)
    return build_packet(0x93, payload)

async def test_mdp_control():
    print(f"Connecting to MDP at {MDP_MAC}...")
    
    async with BleakClient(MDP_MAC) as client:
        print("Connected!")
        
        # Setup notification handler
        responses = []
        def handler(sender, data):
            print(f"RX: {data.hex()}")
            responses.append(data)
        
        await client.start_notify(CHAR_UUID, handler)
        
        # Step 1: Get passcode
        print("\n--- Getting passcode ---")
        get_pass = bytes([0x00, 0x00, 0x00, 0x03, 0x03, 0x00, 0x00, 0x06])
        await client.write_gatt_char(CHAR_UUID, get_pass)
        await asyncio.sleep(0.5)
        
        if not responses:
            print("No passcode response!")
            return
            
        # Parse passcode
        resp = responses[-1]
        passcode_len = resp[9]
        passcode = resp[10:10+passcode_len]
        print(f"Passcode ({passcode_len} bytes): {passcode.hex()}")
        
        # Step 2: Login with MDP format (00 + len prefix)
        print("\n--- Logging in ---")
        responses.clear()
        login_payload = bytes([0x00, passcode_len]) + passcode
        login_len = 3 + len(login_payload)
        login = bytes([0x00, 0x00, 0x00, 0x03, login_len, 0x00, 0x00, 0x08]) + login_payload
        print(f"TX: {login.hex()}")
        await client.write_gatt_char(CHAR_UUID, login)
        await asyncio.sleep(0.5)
        
        if responses and responses[-1][8] == 0x00:
            print("Login successful!")
        else:
            print("Login may have failed")
            
        # Wait for status
        await asyncio.sleep(1.0)
        print(f"\nReceived {len(responses)} packets after login")
        
        # Step 3: Try control command
        print("\n--- Testing control command ---")
        responses.clear()
        
        # Try simple P0 write: set SwitchON = True
        # Format based on Gizwits: action(1) + attr_flags + values
        
        # Attempt 1: Simple single-byte command
        test_cmds = [
            # (description, command bytes)
            ("P0 action=0x01 flag=0x01 (SwitchON=1)", 
             build_packet(0x93, bytes([0x01, 0x01]))),
            
            ("P0 action=0x01 flag=0x81 (SwitchON=1 with value bit)",
             build_packet(0x93, bytes([0x01, 0x81]))),
             
            ("P0 with Motor_Speed=50",
             build_packet(0x93, bytes([0x01, 0x00, 0x00, 0x00, 0x00, 0x32]))),  # 0x32 = 50
        ]
        
        for desc, cmd in test_cmds:
            print(f"\nTrying: {desc}")
            print(f"TX: {cmd.hex()}")
            await client.write_gatt_char(CHAR_UUID, cmd)
            await asyncio.sleep(1.0)
            
            if responses:
                print(f"Got {len(responses)} response(s)")
                for r in responses:
                    print(f"  RX: {r.hex()}")
            responses.clear()
        
        await client.stop_notify(CHAR_UUID)

if __name__ == "__main__":
    asyncio.run(test_mdp_control())
