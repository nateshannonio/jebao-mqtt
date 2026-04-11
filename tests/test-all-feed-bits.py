#!/usr/bin/env python3
"""
Systematic test of all possible feed mode bit positions
Tests bits 0-7 to find which one actually triggers "FEED" display
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

def create_bit_test_commands():
    """Create commands testing each bit position for feed mode"""
    commands = {}
    base_sn = int(time.time())
    
    # Test each bit position individually (with power bit set)
    for bit in range(8):
        if bit == 0:
            continue  # Skip bit 0 (power bit)
        
        flag_value = 0x01 | (1 << bit)  # Power bit + test bit
        cmd_sn = base_sn + bit
        payload = cmd_sn.to_bytes(4, 'big') + bytes([0x01, flag_value])
        
        commands[f"Test Bit {bit} (0x{flag_value:02x})"] = {
            'command': build_packet(0x93, payload),
            'bit': bit,
            'flag': flag_value
        }
    
    # Test some specific combinations that might be feed mode
    special_tests = [
        (0x04, "Bit 2 only (no power)"),
        (0x08, "Bit 3 only (no power)"),
        (0x10, "Bit 4 only (no power)"),
        (0x20, "Bit 5 only (no power)"),
        (0x02, "Bit 1 only (our current guess)"),
        (0x06, "Bits 1+2 (no power)"),
        (0x0A, "Bits 1+3 (no power)"),
    ]
    
    for flag_value, desc in special_tests:
        cmd_sn = base_sn + 100 + flag_value
        payload = cmd_sn.to_bytes(4, 'big') + bytes([0x01, flag_value])
        commands[f"Special: {desc}"] = {
            'command': build_packet(0x93, payload),
            'bit': -1,
            'flag': flag_value
        }
    
    return commands

async def test_all_feed_bits():
    print(f"🔍 Systematic Feed Mode Bit Test")
    print(f"Goal: Find which bit actually triggers 'FEED' display")
    print(f"Connecting to {MDP_MAC}...")
    
    responses = []
    successful_tests = []
    
    def handler(sender, data):
        timestamp = time.time()
        print(f"[{timestamp:.1f}] RX: {data.hex()}")
        responses.append(data)
        
        if len(data) >= 8:
            cmd = int.from_bytes(data[6:8], 'big')
            if cmd == 0x0094:
                print(f"  ✅ ACK")
            elif cmd == 0x0093:
                print(f"  📨 Command response")
    
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
            
            print("=== SYSTEMATIC BIT TESTING ===")
            print("👀 WATCH THE PUMP DISPLAY for 'FEED' text!")
            print("🔊 Listen for any sounds/changes")
            print()
            
            test_commands = create_bit_test_commands()
            
            for i, (desc, cmd_data) in enumerate(test_commands.items()):
                print(f"[{i+1}/{len(test_commands)}] {desc}")
                print(f"TX: {cmd_data['command'].hex()}")
                
                try:
                    await client.write_gatt_char(CHAR_UUID, cmd_data['command'])
                    print("📤 Command sent")
                    
                    # Wait for response and pump reaction
                    await asyncio.sleep(3.0)
                    
                    if client.is_connected:
                        successful_tests.append((desc, cmd_data['flag']))
                        print("✅ Connection stable")
                        
                        # Ask user to observe (in real testing, you'd pause here)
                        print("👀 OBSERVE: Did pump show 'FEED'? (y/n/unsure)")
                        print("   Any display changes? Any behavior changes?")
                        
                    else:
                        print("❌ Pump disconnected - command may have failed")
                        break
                        
                except Exception as e:
                    print(f"❌ Error: {e}")
                    break
                
                print("-" * 50)
                await asyncio.sleep(1.0)  # Brief pause between tests
            
            # Power back on after testing
            print("\n=== RESTORING NORMAL OPERATION ===")
            normal_cmd = build_packet(0x93, int(time.time()).to_bytes(4, 'big') + bytes([0x01, 0x01, 70]))
            await client.write_gatt_char(CHAR_UUID, normal_cmd)
            await asyncio.sleep(2.0)
            
            await client.stop_notify(CHAR_UUID)
            
    except Exception as e:
        print(f"❌ Connection error: {e}")
        return
    
    print(f"\n📊 TEST RESULTS:")
    print(f"Commands tested: {len(test_commands)}")
    print(f"Successful sends: {len(successful_tests)}")
    print(f"Total responses: {len(responses)}")
    
    if successful_tests:
        print(f"\n✅ SUCCESSFUL COMMANDS:")
        for desc, flag in successful_tests:
            print(f"  {desc} (flag: 0x{flag:02x})")
        
        print(f"\n🎯 ANALYSIS:")
        print(f"Look for commands that caused:")
        print(f"- Pump display to show 'FEED'")
        print(f"- Pump to stop with timer")
        print(f"- Any other distinctive behavior")

if __name__ == "__main__":
    asyncio.run(test_all_feed_bits())