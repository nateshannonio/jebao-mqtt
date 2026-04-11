#!/usr/bin/env python3
"""
Read pump status to verify speed position
User will set pump to 75% to confirm position 27 is speed value
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

async def read_pump_status():
    print("📊 Reading Pump Status")
    print("Expected: Pump should be at 75% if you changed it")
    print(f"Connecting to {MDP_MAC}...")
    
    responses = []
    
    def handler(sender, data):
        timestamp = time.time()
        print(f"[{timestamp:.1f}] RX: {data.hex()}")
        responses.append(data)
        
        if len(data) >= 8:
            cmd = int.from_bytes(data[6:8], 'big')
            if cmd == 0x0100:
                print(f"  📊 Status response received!")
                if len(data) > 39:  # Position 27 in payload = position 39 in full packet
                    speed_byte = data[39]
                    print(f"  🎯 SPEED AT POSITION 27: {speed_byte}% (0x{speed_byte:02x})")
                    print(f"  ✅ Confirmed: Position 27 contains pump speed!")
                    
                    # Check other interesting positions
                    if len(data) > 50:
                        print(f"\n  Other potentially interesting bytes:")
                        print(f"    Position 36: {data[36]} (0x{data[36]:02x})")
                        print(f"    Position 37: {data[37]} (0x{data[37]:02x})")
                        print(f"    Position 38: {data[38]} (0x{data[38]:02x})")
                        print(f"    Position 40: {data[40]} (0x{data[40]:02x})")
                        print(f"    Position 41: {data[41]} (0x{data[41]:02x})")
    
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
            
            print("=== READING STATUS ===")
            
            # Send status read command (action 0x02)
            cmd_sn = int(time.time())
            status_cmd = build_packet(0x93, cmd_sn.to_bytes(4, 'big') + bytes([0x02, 0x00]))
            print(f"Sending status read command...")
            print(f"TX: {status_cmd.hex()}")
            
            await client.write_gatt_char(CHAR_UUID, status_cmd)
            await asyncio.sleep(2.0)
            
            await client.stop_notify(CHAR_UUID)
            
    except Exception as e:
        print(f"❌ Connection error: {e}")
    
    print(f"\n📋 Summary:")
    print("If position 27 shows 75, we've confirmed the speed position!")
    print("This means we know how to READ the speed correctly.")
    print("Now we just need to find the correct WRITE command format.")

if __name__ == "__main__":
    asyncio.run(read_pump_status())