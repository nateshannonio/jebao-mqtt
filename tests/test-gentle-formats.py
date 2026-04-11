#!/usr/bin/env python3
"""
Gentle testing - one command per connection to avoid BLE stack overload
Based on seeing disconnections in previous tests
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

async def test_single_command(test_name: str, payload_data: bytes, description: str):
    """Test a single command with full connect/disconnect cycle"""
    print(f"\n{'='*60}")
    print(f"[{test_name}] {description}")
    print(f"Payload: {payload_data.hex()}")
    print(f"{'='*60}")
    
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
            print("🔗 Connecting...")
            await client.start_notify(CHAR_UUID, handler)
            print("✅ Connected!")
            
            # Quick authentication
            get_pass = build_packet(0x06, b'')
            await client.write_gatt_char(CHAR_UUID, get_pass)
            await asyncio.sleep(0.5)
            
            if responses:
                resp = responses[-1]
                if len(resp) > 8:
                    passcode = resp[8:]
                    login = build_packet(0x08, passcode)
                    await client.write_gatt_char(CHAR_UUID, login)
                    await asyncio.sleep(1.0)
                    print("🔐 Authenticated")
            
            # Send the test command
            cmd_sn = int(time.time())
            payload = cmd_sn.to_bytes(4, 'big') + payload_data
            cmd = build_packet(0x93, payload)
            
            print(f"📤 Sending: {cmd.hex()}")
            await client.write_gatt_char(CHAR_UUID, cmd)
            
            # Wait and observe
            print("⏰ Waiting 5 seconds for response...")
            await asyncio.sleep(5.0)
            
            if client.is_connected:
                print("✅ Command completed safely")
                print("❓ Did you observe any change on the pump?")
            else:
                print("❌ Command caused disconnection")
            
            await client.stop_notify(CHAR_UUID)
            
    except Exception as e:
        print(f"❌ Error: {e}")
    
    print(f"📊 Responses received: {len(responses)}")
    return len(responses) > 0

async def run_gentle_tests():
    print("🧪 Gentle Command Testing - One Command Per Connection")
    print("Goal: Find working command format without overwhelming BLE stack")
    print(f"Testing pump: {MDP_MAC}")
    
    # Test cases - start with the most promising from research
    test_cases = [
        ("Test1", bytes([80]), "Simple speed 80% (most basic format)"),
        ("Test2", bytes([0x01, 80]), "Action 0x01 + Speed 80%"),
        ("Test3", bytes([0x05, 80]), "Attribute 5 + Speed 80%"),
        ("Test4", bytes([0x02, 80]), "Action 0x02 + Speed 80%"),
        ("Test5", bytes([0x00, 80]), "Action 0x00 + Speed 80%"),
    ]
    
    successful_tests = []
    
    for test_name, payload, description in test_cases:
        print(f"\n⏳ Starting {test_name}...")
        
        # Wait between tests to let pump recover
        if test_name != "Test1":
            print("⏰ Waiting 10 seconds between tests...")
            await asyncio.sleep(10)
        
        success = await test_single_command(test_name, payload, description)
        if success:
            successful_tests.append((test_name, description))
    
    print(f"\n" + "="*80)
    print("📋 FINAL RESULTS")
    print("="*80)
    print(f"Tests completed: {len(test_cases)}")
    print(f"Successful connections: {len(successful_tests)}")
    
    if successful_tests:
        print("\n✅ Tests that didn't cause disconnection:")
        for test_name, desc in successful_tests:
            print(f"  {test_name}: {desc}")
    
    print("\n🎯 KEY QUESTION:")
    print("Did you see the pump speed actually change during any of these tests?")
    print("If yes, which test number caused the speed change?")

if __name__ == "__main__":
    asyncio.run(run_gentle_tests())