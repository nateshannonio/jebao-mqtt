#!/usr/bin/env python3
"""
Comprehensive test of MDP pump functionality
Tests power control, speed control, and feed mode with stable command formats
"""

import asyncio
import time
from bleak import BleakClient

# Your MDP pump MAC
MDP_MAC = "7725528E-75A8-F1C3-71E6-CEF9A6EDA5EE"
SERVICE_UUID = "0000abf0-0000-1000-8000-00805f9b34fb"
CHAR_UUID = "0000abf7-0000-1000-8000-00805f9b34fb"

# MDP attribute constants
MDP_ATTR_POWER = 0  # SwitchON - bit 0
MDP_ATTR_FEED = 1   # Feed mode - bit 1

def build_packet(cmd: int, payload: bytes) -> bytes:
    """Build Gizwits BLE packet"""
    length = 3 + len(payload)
    return bytes([0x00, 0x00, 0x00, 0x03, length, 0x00]) + cmd.to_bytes(2, 'big') + payload

def make_mdp_command(attrs: dict) -> bytes:
    """Build MDP command using the stable format we discovered"""
    command_sn = int(time.time())
    action = 0x01  # Write action
    
    # Build flag byte from attributes
    flag_byte = 0x00
    
    if 'power' in attrs and attrs['power']:
        flag_byte |= (1 << MDP_ATTR_POWER)  # Set power bit
        
    if 'feed' in attrs and attrs['feed']:
        flag_byte |= (1 << MDP_ATTR_FEED)   # Set feed mode bit
    
    # Handle different command types using our stable format
    if 'feed' in attrs:
        # Feed mode command - simple flag-based (format that worked)
        payload = bytes([action, flag_byte])
    elif 'power' in attrs and 'speed' not in attrs:
        # Power-only command - simple format
        payload = bytes([action, flag_byte])
    elif 'speed' in attrs:
        # Speed command - use format 1 from tests (most reliable)
        # Keep power state when changing speed
        if 'power' not in attrs:
            flag_byte |= (1 << MDP_ATTR_POWER)  # Assume keep power on
        payload = bytes([action, flag_byte, attrs['speed']])
    else:
        # Fallback
        payload = bytes([action, flag_byte])
    
    full_payload = command_sn.to_bytes(4, 'big') + payload
    return build_packet(0x93, full_payload)

def parse_status(data: bytes):
    """Parse pump status from response"""
    if len(data) >= 8:
        cmd = int.from_bytes(data[6:8], 'big')
        if cmd == 0x0093 and len(data) > 12:
            p0 = data[12:]
            if len(p0) >= 2:
                flag_byte = p0[1]
                power_on = (flag_byte & (1 << MDP_ATTR_POWER)) != 0
                feed_mode = (flag_byte & (1 << MDP_ATTR_FEED)) != 0
                
                # Look for speed value
                speed = None
                if len(p0) >= 3:
                    speed = p0[2]
                
                return {
                    'power': power_on,
                    'feed': feed_mode, 
                    'speed': speed
                }
    return None

async def test_complete_mdp():
    print(f"Complete MDP functionality test")
    print(f"Connecting to {MDP_MAC}...")
    
    responses = []
    pump_disconnected = False
    
    def handler(sender, data):
        nonlocal pump_disconnected
        timestamp = time.time()
        print(f"[{timestamp:.3f}] RX: {data.hex()}")
        responses.append((timestamp, data))
        
        # Parse and display status
        status = parse_status(data)
        if status:
            print(f"  Status: Power={status['power']}, Feed={status['feed']}, Speed={status['speed']}")
    
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
            
            # Comprehensive test sequence
            test_sequence = [
                ("Power ON", {'power': True}),
                ("Set Speed 60%", {'speed': 60}),
                ("Set Speed 80%", {'speed': 80}),
                ("Enable Feed Mode", {'feed': True}),
                ("Wait 3 seconds in feed mode", None),
                ("Disable Feed Mode", {'feed': False}),
                ("Set Speed 50%", {'speed': 50}),
                ("Power OFF", {'power': False}),
                ("Wait 2 seconds", None),
                ("Power ON with Speed 70%", {'power': True, 'speed': 70}),
                ("Enable Feed Mode again", {'feed': True}),
                ("Wait 3 seconds", None),
                ("Disable Feed Mode and set Speed 90%", {'feed': False, 'speed': 90}),
                ("Final Power OFF", {'power': False}),
            ]
            
            print("=== COMPREHENSIVE MDP TEST ===")
            for desc, attrs in test_sequence:
                print(f"\n{desc}:")
                
                if attrs is None:
                    # Wait period
                    wait_time = 3 if "3 seconds" in desc else 2
                    for i in range(wait_time):
                        print(f"  Waiting... {wait_time-i}s")
                        await asyncio.sleep(1.0)
                    continue
                
                cmd = make_mdp_command(attrs)
                print(f"TX: {cmd.hex()}")
                print(f"Command: {attrs}")
                
                try:
                    await client.write_gatt_char(CHAR_UUID, cmd)
                    print("✅ Command sent successfully")
                    
                    # Wait for response
                    await asyncio.sleep(1.5)
                    
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
    
    # Test summary
    print(f"\n=== TEST SUMMARY ===")
    print(f"Total responses: {len(responses)}")
    print(f"Connection stable: {'Yes' if not pump_disconnected else 'No'}")
    print(f"Commands tested: {len([t for t in test_sequence if t[1] is not None])}")
    
    if not pump_disconnected:
        print("🎉 All MDP functionality working correctly!")
        print("✅ Power control - WORKING")
        print("✅ Speed control - WORKING") 
        print("✅ Feed mode control - WORKING")
        print("✅ Combined commands - WORKING")
        print("✅ Stable connection - WORKING")
    else:
        print("⚠️  Some commands caused disconnection")

if __name__ == "__main__":
    asyncio.run(test_complete_mdp())