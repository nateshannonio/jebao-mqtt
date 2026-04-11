#!/usr/bin/env python3
"""
Test higher bits (4-7) first as they're less likely to cause disconnection
Work backwards from bit 7 down
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

async def test_high_bits():
    print(f"🔧 Testing High Bits (7,6,5,4) for Feed Mode")
    print(f"Starting with safest bits first")
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
            
            print("=== TESTING HIGH BITS ===")
            print("👀 Watch pump display carefully!")
            
            # Test high bits first (less likely to disconnect)
            for bit in [7, 6, 5, 4]:
                flag_value = 1 << bit  
                
                print(f"\n[Bit {bit}] Testing flag 0x{flag_value:02x}")
                
                cmd_sn = int(time.time()) + bit
                payload = cmd_sn.to_bytes(4, 'big') + bytes([0x01, flag_value])
                cmd = build_packet(0x93, payload)
                
                print(f"TX: {cmd.hex()}")
                
                try:
                    await client.write_gatt_char(CHAR_UUID, cmd)
                    print("📤 Command sent")
                    
                    # Wait longer to observe any changes
                    for i in range(5):
                        await asyncio.sleep(1.0)
                        if not client.is_connected:
                            print("❌ Connection lost")
                            break
                        if i == 2:
                            print("   ⏰ Checking pump display...")
                        elif i == 4:
                            print("   ❓ Any 'FEED' text or timer?")
                    
                    if client.is_connected:
                        print("✅ Connection stable - command safe")
                        print(f"❓ RESULT: Did bit {bit} trigger feed mode?")
                        print("   - 'FEED' display?")
                        print("   - Countdown timer?") 
                        print("   - Pump stopped?")
                        
                        # Small pause for observation
                        await asyncio.sleep(2.0)
                    else:
                        print(f"❌ Bit {bit} caused disconnection")
                        break
                    
                except Exception as e:
                    print(f"❌ Error with bit {bit}: {e}")
                    break
            
            # If still connected, try bit 3
            if client.is_connected:
                print(f"\n[Bit 3] Testing flag 0x08")
                cmd_sn = int(time.time()) + 100
                payload = cmd_sn.to_bytes(4, 'big') + bytes([0x01, 0x08])
                cmd = build_packet(0x93, payload)
                
                print(f"TX: {cmd.hex()}")
                
                try:
                    await client.write_gatt_char(CHAR_UUID, cmd)
                    print("📤 Sent bit 3 test")
                    
                    await asyncio.sleep(5.0)
                    
                    if client.is_connected:
                        print("✅ Bit 3 safe")
                        print("❓ Did bit 3 trigger feed mode?")
                    else:
                        print("❌ Bit 3 caused disconnection")
                
                except Exception as e:
                    print(f"❌ Error with bit 3: {e}")
            
            await client.stop_notify(CHAR_UUID)
            
    except Exception as e:
        print(f"❌ Connection error: {e}")
    
    print(f"\n📊 Test complete")
    print(f"Responses received: {len(responses)}")
    print("🎯 Which bit showed 'FEED' on pump display?")

if __name__ == "__main__":
    asyncio.run(test_high_bits())