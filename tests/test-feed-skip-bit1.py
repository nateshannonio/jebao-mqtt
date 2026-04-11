#!/usr/bin/env python3
"""
Test feed mode skipping bit 1 (which causes disconnection)
Start with bit 2 and higher
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

async def test_feed_skip_bit1():
    print(f"🔧 Feed Mode Test - Skipping Bit 1")
    print(f"Testing bits 2-7 for feed mode")
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
            
            print("=== TESTING BITS 2-7 ===")
            print("👀 Watch for 'FEED' display on pump")
            
            # Test bits 2-7 individually (avoiding bit 0=power, bit 1=problem)
            for bit in [2, 3, 4, 5, 6, 7]:
                flag_value = 1 << bit  # Just this bit, no others
                
                print(f"\n[Bit {bit}] Testing 0x{flag_value:02x}")
                
                cmd_sn = int(time.time()) + bit
                payload = cmd_sn.to_bytes(4, 'big') + bytes([0x01, flag_value])
                cmd = build_packet(0x93, payload)
                
                print(f"TX: {cmd.hex()}")
                
                try:
                    await client.write_gatt_char(CHAR_UUID, cmd)
                    print("📤 Sent")
                    
                    # Wait and observe
                    await asyncio.sleep(3.0)
                    
                    if client.is_connected:
                        print("✅ Stable connection")
                        print("❓ Did pump show 'FEED'? Any display changes?")
                    else:
                        print("❌ Disconnected - this bit may also be problematic")
                        break
                    
                except Exception as e:
                    print(f"❌ Error: {e}")
                    break
            
            # If we're still connected, try some combinations
            if client.is_connected:
                print(f"\n=== TRYING COMBINATIONS ===")
                
                combo_tests = [
                    (0x04 | 0x01, "Bit 2 + Power"),    # Most likely feed + power
                    (0x08 | 0x01, "Bit 3 + Power"),
                    (0x10 | 0x01, "Bit 4 + Power"),
                ]
                
                for flag_value, desc in combo_tests:
                    print(f"\n[Combo] {desc} (0x{flag_value:02x})")
                    
                    cmd_sn = int(time.time()) + 100 + flag_value
                    payload = cmd_sn.to_bytes(4, 'big') + bytes([0x01, flag_value])
                    cmd = build_packet(0x93, payload)
                    
                    print(f"TX: {cmd.hex()}")
                    
                    try:
                        await client.write_gatt_char(CHAR_UUID, cmd)
                        print("📤 Sent")
                        
                        await asyncio.sleep(3.0)
                        
                        if client.is_connected:
                            print("✅ Stable")
                            print("❓ 'FEED' display? Timer? Pump stop?")
                        else:
                            print("❌ Disconnected")
                            break
                        
                    except Exception as e:
                        print(f"❌ Error: {e}")
                        break
            
            await client.stop_notify(CHAR_UUID)
            
    except Exception as e:
        print(f"❌ Connection error: {e}")
    
    print(f"\n📊 Results: {len(responses)} responses received")
    print("🎯 Which commands triggered 'FEED' mode?")

if __name__ == "__main__":
    asyncio.run(test_feed_skip_bit1())