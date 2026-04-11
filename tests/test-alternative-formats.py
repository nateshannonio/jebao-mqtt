#!/usr/bin/env python3
"""
Test alternative MDP command formats based on GitHub research
Research shows newer WiFi+BLE devices use different protocols than older ones
Current issue: Commands get ACK but don't actually control pump (stays at 75%)
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

async def test_alternative_formats():
    print(f"🔬 Testing Alternative MDP Command Formats")
    print(f"Based on research: newer WiFi+BLE devices use different protocols")
    print(f"Current: Commands get ACK but pump stays at 75%")
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
            elif cmd == 0x0062:
                print(f"  📊 Status response")
                if len(data) > 12:
                    payload = data[12:]
                    print(f"      Status data: {payload.hex()}")
    
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
            
            print("=== TESTING ALTERNATIVE COMMAND FORMATS ===")
            print("Goal: Find format that actually changes pump speed (not just ACK)")
            
            # Test 1: Try raw commands without Gizwits wrapper
            print(f"\n[Test 1] Raw Commands (no Gizwits protocol wrapper)")
            raw_tests = [
                (bytes([85]), "Raw speed 85%"),
                (bytes([0x05, 85]), "Attr 5 + Speed 85%"),
                (bytes([0x01, 0x05, 85]), "Action + Attr + Speed"),
            ]
            
            for payload_data, desc in raw_tests:
                if not client.is_connected:
                    break
                    
                print(f"\n  {desc}")
                cmd_sn = int(time.time())
                # Try with 0x93 command but different payload structure
                payload = cmd_sn.to_bytes(4, 'big') + payload_data
                cmd = build_packet(0x93, payload)
                
                print(f"  Payload: {payload_data.hex()}")
                print(f"  TX: {cmd.hex()}")
                
                try:
                    await client.write_gatt_char(CHAR_UUID, cmd)
                    print("  📤 Sent")
                    await asyncio.sleep(3.0)
                    
                    if client.is_connected:
                        print("  ✅ Safe")
                        print("  ❓ Did speed change?")
                    else:
                        print("  ❌ Disconnected")
                        break
                except Exception as e:
                    print(f"  ❌ Error: {e}")
            
            # Test 2: Try different action codes  
            if client.is_connected:
                print(f"\n[Test 2] Different Action Codes")
                action_tests = [
                    (bytes([0x02, 90]), "Action 0x02 + Speed 90%"),
                    (bytes([0x03, 0x01, 90]), "Action 0x03 + Flag + Speed"),
                    (bytes([0x04, 90]), "Action 0x04 + Speed 90%"),
                    (bytes([0x00, 90]), "Action 0x00 + Speed 90%"),
                ]
                
                for payload_data, desc in action_tests:
                    if not client.is_connected:
                        break
                        
                    print(f"\n  {desc}")
                    cmd_sn = int(time.time()) + 100
                    payload = cmd_sn.to_bytes(4, 'big') + payload_data
                    cmd = build_packet(0x93, payload)
                    
                    print(f"  TX: {cmd.hex()}")
                    
                    try:
                        await client.write_gatt_char(CHAR_UUID, cmd)
                        await asyncio.sleep(3.0)
                        
                        if client.is_connected:
                            print("  ✅ Safe")
                            print("  ❓ Did speed change?")
                        else:
                            print("  ❌ Disconnected")
                            break
                    except Exception as e:
                        print(f"  ❌ Error: {e}")
            
            # Test 3: Try attribute-value pairs directly
            if client.is_connected:
                print(f"\n[Test 3] Direct Attribute-Value Format")
                attr_tests = [
                    (bytes([0x01, 0x05, 95]), "Write Attr 5 (Motor) = 95%"),
                    (bytes([0x01, 0x01, 0x01]), "Write Attr 1 (Power) = ON"),
                    (bytes([0x01, 0x01, 0x00, 0x05, 95]), "Multi-attr: Power + Speed"),
                ]
                
                for payload_data, desc in attr_tests:
                    if not client.is_connected:
                        break
                        
                    print(f"\n  {desc}")
                    cmd_sn = int(time.time()) + 200
                    payload = cmd_sn.to_bytes(4, 'big') + payload_data
                    cmd = build_packet(0x93, payload)
                    
                    print(f"  TX: {cmd.hex()}")
                    
                    try:
                        await client.write_gatt_char(CHAR_UUID, cmd)
                        await asyncio.sleep(3.0)
                        
                        if client.is_connected:
                            print("  ✅ Safe")
                            print("  ❓ Did speed change?")
                        else:
                            print("  ❌ Disconnected")
                            break
                    except Exception as e:
                        print(f"  ❌ Error: {e}")
            
            # Test 4: Try without command serial number
            if client.is_connected:
                print(f"\n[Test 4] Commands Without Serial Number")
                no_sn_tests = [
                    (bytes([0x01, 60]), "Direct Action + Speed (no SN)"),
                    (bytes([60]), "Just Speed Value (no SN)"),
                    (bytes([0x05, 60]), "Attr + Speed (no SN)"),
                ]
                
                for payload_data, desc in no_sn_tests:
                    if not client.is_connected:
                        break
                        
                    print(f"\n  {desc}")
                    # Use payload directly without command serial number
                    cmd = build_packet(0x93, payload_data)
                    
                    print(f"  TX: {cmd.hex()}")
                    
                    try:
                        await client.write_gatt_char(CHAR_UUID, cmd)
                        await asyncio.sleep(3.0)
                        
                        if client.is_connected:
                            print("  ✅ Safe")
                            print("  ❓ Did speed change?")
                        else:
                            print("  ❌ Disconnected")
                            break
                    except Exception as e:
                        print(f"  ❌ Error: {e}")
            
            await client.stop_notify(CHAR_UUID)
            
    except Exception as e:
        print(f"❌ Connection error: {e}")
    
    print(f"\n📊 Test Summary:")
    print(f"Total responses: {len(responses)}")
    print("\n🎯 Critical Question:")
    print("Did ANY of these alternative formats actually change pump speed?")
    print("Current expectation: pump should change from 75% to test values")

if __name__ == "__main__":
    asyncio.run(test_alternative_formats())