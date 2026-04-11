#!/usr/bin/env python3
"""
Gentle feed mode testing - try safer commands first
Avoid combinations that might cause disconnection
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

def create_safe_test_commands():
    """Create safer commands to test feed mode without disconnection"""
    commands = {}
    base_sn = int(time.time())
    
    # Start with single bits (no power bit) - these are safer
    safe_tests = [
        (0x02, "Bit 1 only (our current guess, no power)"),
        (0x04, "Bit 2 only"),  
        (0x08, "Bit 3 only"),
        (0x10, "Bit 4 only"),
        (0x20, "Bit 5 only"),
        (0x40, "Bit 6 only"),
        (0x80, "Bit 7 only"),
    ]
    
    for flag_value, desc in safe_tests:
        cmd_sn = base_sn + flag_value
        payload = cmd_sn.to_bytes(4, 'big') + bytes([0x01, flag_value])
        commands[f"Safe test: {desc}"] = {
            'command': build_packet(0x93, payload),
            'flag': flag_value,
            'safe': True
        }
    
    # Then try different action codes (still without power)
    for action in [0x02, 0x03, 0x04]:
        cmd_sn = base_sn + 200 + action
        payload = cmd_sn.to_bytes(4, 'big') + bytes([action, 0x02])  # bit 1 with different action
        commands[f"Action test: 0x{action:02x} with bit 1"] = {
            'command': build_packet(0x93, payload),
            'flag': 0x02,
            'safe': False  # Less sure about these
        }
    
    return commands

async def test_feed_gentle():
    print(f"🔧 Gentle Feed Mode Testing")
    print(f"Testing safer commands to avoid disconnection")
    print(f"Connecting to {MDP_MAC}...")
    
    responses = []
    feed_candidates = []
    
    def handler(sender, data):
        timestamp = time.time()
        print(f"[{timestamp:.1f}] RX: {data.hex()}")
        responses.append(data)
        
        if len(data) >= 8:
            cmd = int.from_bytes(data[6:8], 'big')
            if cmd == 0x0094:
                print(f"  ✅ ACK received")
            elif cmd == 0x0062 and len(data) > 12:
                p0 = data[12:]
                print(f"  📊 Status update: {p0.hex()}")
    
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
            
            print("=== GENTLE TESTING ===")
            print("🎯 Testing individual bits first (safer)")
            print("👀 Watch pump display for 'FEED' text")
            print()
            
            test_commands = create_safe_test_commands()
            
            for desc, cmd_data in test_commands.items():
                print(f"Testing: {desc}")
                print(f"Flag: 0x{cmd_data['flag']:02x} | TX: {cmd_data['command'].hex()}")
                
                try:
                    await client.write_gatt_char(CHAR_UUID, cmd_data['command'])
                    print("📤 Sent")
                    
                    # Wait and check for pump display changes
                    await asyncio.sleep(2.0)
                    
                    if client.is_connected:
                        print("✅ Connection stable")
                        
                        # Check if this might be feed mode
                        print("❓ OBSERVATION CHECK:")
                        print("   - Did pump display change to 'FEED'?")
                        print("   - Did pump stop/pause?")
                        print("   - Any timer countdown?")
                        print("   - Any other behavior change?")
                        
                        # If this seemed to work, note it
                        feed_candidates.append(cmd_data['flag'])
                        
                    else:
                        print("❌ Disconnected - this flag might be problematic")
                        break
                    
                except Exception as e:
                    print(f"❌ Error: {e}")
                    break
                
                print()
                await asyncio.sleep(1.0)  # Brief pause between tests
            
            await client.stop_notify(CHAR_UUID)
            
    except Exception as e:
        print(f"❌ Connection error: {e}")
        return
    
    print(f"\n📊 RESULTS:")
    print(f"Commands tested: {len(test_commands)}")
    print(f"Total responses: {len(responses)}")
    
    if feed_candidates:
        print(f"\n🎯 POTENTIAL FEED MODE FLAGS:")
        for flag in feed_candidates:
            print(f"  - 0x{flag:02x} (bit {flag.bit_length()-1})")
        print(f"\nWhich ones triggered 'FEED' display?")
    else:
        print(f"⚠️  No candidates found - may need different approach")

if __name__ == "__main__":
    asyncio.run(test_feed_gentle())