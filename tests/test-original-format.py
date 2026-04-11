#!/usr/bin/env python3
"""
Test the original command formats from test-mdp-formats.py
These worked before - let's see which ones actually control the pump
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

async def test_original_formats():
    print(f"🔍 Testing Original Command Formats")
    print(f"These formats worked in previous tests")
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
            
            print("=== TESTING ORIGINAL FORMATS ===")
            print("👀 Watch pump carefully for ANY changes!")
            
            # Original formats from test-mdp-formats.py that worked
            command_tests = [
                # Format 1: Bridge format (action + flag + speed) 
                ("Bridge format - Speed 50%", 
                 int(time.time()).to_bytes(4, 'big') + bytes([0x01, 0x00, 50])),
                
                # Format 2: Simple action + value  
                ("Simple action+value - Speed 50%",
                 int(time.time()).to_bytes(4, 'big') + bytes([0x01, 50])),
                
                # Format 3: Just the speed value
                ("Just speed value - Speed 50%",
                 int(time.time()).to_bytes(4, 'big') + bytes([50])),
                
                # Format 4: Power commands
                ("Power OFF - Simple",
                 int(time.time()).to_bytes(4, 'big') + bytes([0x01, 0x00])),
                
                # Format 6: Original test style
                ("Original test style - Speed 50%",
                 int(time.time()).to_bytes(4, 'big') + bytes([0x01, 0x00, 0x00, 0x00, 0x00, 50])),
                
                # Try some variations
                ("Speed 80 - Bridge format",
                 int(time.time()).to_bytes(4, 'big') + bytes([0x01, 0x00, 80])),
                
                ("Speed 30 - Simple format",
                 int(time.time()).to_bytes(4, 'big') + bytes([30])),
                
                ("Power ON - Flag 0x01",
                 int(time.time()).to_bytes(4, 'big') + bytes([0x01, 0x01])),
            ]
            
            for i, (desc, payload) in enumerate(command_tests):
                print(f"\n[{i+1}/{len(command_tests)}] {desc}")
                
                cmd = build_packet(0x93, payload)
                print(f"Payload: {payload.hex()}")
                print(f"TX: {cmd.hex()}")
                
                try:
                    await client.write_gatt_char(CHAR_UUID, cmd)
                    print("📤 Command sent")
                    
                    # Wait and observe pump
                    await asyncio.sleep(3.0)
                    
                    if client.is_connected:
                        print("✅ Command successful - connection stable")
                        print("❓ OBSERVE: Any pump changes?")
                        print("   - Speed change?")
                        print("   - Power on/off?") 
                        print("   - Display changes?")
                        print("   - Sound changes?")
                    else:
                        print("❌ Command failed - pump disconnected")
                        break
                        
                except Exception as e:
                    print(f"❌ Error: {e}")
                    break
                
                # Brief pause between commands
                await asyncio.sleep(1.0)
            
            await client.stop_notify(CHAR_UUID)
            
    except Exception as e:
        print(f"❌ Connection error: {e}")
    
    print(f"\n📊 Test Complete")
    print(f"Responses received: {len(responses)}")
    print("\n🎯 CRITICAL QUESTION:")
    print("Which commands caused visible changes to the pump?")
    print("- Speed changes?")
    print("- Power on/off?")
    print("- Any other behavior?")

if __name__ == "__main__":
    asyncio.run(test_original_formats())