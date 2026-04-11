#!/usr/bin/env python3
"""
Test MDP feed mode functionality
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

def make_feed_command(enable: bool) -> bytes:
    """Create MDP feed mode command"""
    command_sn = int(time.time())
    action = 0x01
    
    if enable:
        # Enable feed mode: set feed bit (bit 1) 
        # Also keep power on (bit 0) - feed mode requires power
        flag_byte = 0x03  # Both power (bit 0) and feed (bit 1)
    else:
        # Disable feed mode: clear feed bit but keep power on
        flag_byte = 0x01  # Just power (bit 0)
    
    payload = bytes([action, flag_byte])
    full_payload = command_sn.to_bytes(4, 'big') + payload
    return build_packet(0x93, full_payload)

async def test_feed_mode():
    print(f"Testing MDP feed mode functionality")
    print(f"Connecting to {MDP_MAC}...")
    
    responses = []
    
    def handler(sender, data):
        timestamp = time.time()
        print(f"[{timestamp:.3f}] RX: {data.hex()}")
        responses.append((timestamp, data))
        
        # Parse response
        if len(data) >= 8:
            cmd = int.from_bytes(data[6:8], 'big')
            print(f"  CMD: 0x{cmd:04x}")
            
            if cmd == 0x0093 and len(data) > 12:
                p0 = data[12:]
                if len(p0) >= 2:
                    flag_byte = p0[1]
                    power_on = (flag_byte & 0x01) != 0
                    feed_mode = (flag_byte & 0x02) != 0
                    print(f"  Status: Power={power_on}, Feed={feed_mode}")
    
    async with BleakClient(MDP_MAC) as client:
        try:
            print("Connected!")
            await client.start_notify(CHAR_UUID, handler)
            
            # Authentication
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
            
            # Test feed mode sequence
            feed_tests = [
                ("Enable Feed Mode", True),
                ("Wait 5 seconds in feed mode", None),
                ("Disable Feed Mode", False),
                ("Wait 3 seconds", None),
                ("Enable Feed Mode again", True),
                ("Wait 3 seconds", None),  
                ("Disable Feed Mode", False),
            ]
            
            print("=== TESTING FEED MODE ===")
            for desc, enable in feed_tests:
                print(f"\n{desc}:")
                
                if enable is None:
                    # Wait period
                    wait_time = 5 if "5 seconds" in desc else 3
                    for i in range(wait_time):
                        print(f"  Waiting... {wait_time-i}s")
                        await asyncio.sleep(1.0)
                    continue
                
                cmd = make_feed_command(enable)
                print(f"TX: {cmd.hex()}")
                
                try:
                    await client.write_gatt_char(CHAR_UUID, cmd)
                    print("✅ Command sent successfully")
                    
                    await asyncio.sleep(1.5)
                    
                    if client.is_connected:
                        print("✅ Pump stayed connected")
                    else:
                        print("❌ Pump disconnected")
                        break
                        
                except Exception as e:
                    print(f"❌ Error: {e}")
                    break
                
            await client.stop_notify(CHAR_UUID)
            
        except Exception as e:
            print(f"Connection error: {e}")
    
    print(f"\nTest completed. Total responses: {len(responses)}")

if __name__ == "__main__":
    asyncio.run(test_feed_mode())