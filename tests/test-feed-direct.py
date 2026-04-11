#!/usr/bin/env python3
"""
Direct test of feed mode command via BLE
Simple test to verify the command works
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

def make_feed_command() -> bytes:
    """Create the feed mode command based on our implementation"""
    command_sn = int(time.time())
    action = 0x01  # Write action
    
    # Based on our analysis: feed mode sets bit 1 (0x02) + power bit 0 (0x01) = 0x03
    flag_byte = 0x03  # Both power and feed bits
    
    payload = bytes([action, flag_byte])
    full_payload = command_sn.to_bytes(4, 'big') + payload
    return build_packet(0x93, full_payload)

def make_power_on_command(speed: int = 70) -> bytes:
    """Create power ON command with speed"""
    command_sn = int(time.time())
    action = 0x01
    flag_byte = 0x01  # Just power bit
    
    payload = bytes([action, flag_byte, speed])
    full_payload = command_sn.to_bytes(4, 'big') + payload
    return build_packet(0x93, full_payload)

async def test_feed_direct():
    print(f"🧪 Direct Feed Mode Test")
    print(f"Connecting to {MDP_MAC}...")
    
    responses = []
    
    def handler(sender, data):
        timestamp = time.time()
        print(f"[{timestamp:.1f}] RX: {data.hex()}")
        responses.append(data)
        
        # Parse response
        if len(data) >= 8:
            cmd = int.from_bytes(data[6:8], 'big')
            if cmd == 0x0093:
                print(f"  ✅ ACK received")
            elif cmd == 0x0062 and len(data) > 12:
                p0 = data[12:]
                print(f"  📊 Status: {p0.hex()}")
    
    async with BleakClient(MDP_MAC) as client:
        try:
            print("✅ Connected!")
            await client.start_notify(CHAR_UUID, handler)
            
            # Authentication
            print("\n=== Authentication ===")
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
            
            # Test sequence
            print("=== Feed Mode Test ===")
            
            print("\n1. Activating Feed Mode")
            feed_cmd = make_feed_command()
            print(f"TX: {feed_cmd.hex()}")
            
            await client.write_gatt_char(CHAR_UUID, feed_cmd)
            print("📤 Feed command sent!")
            
            print("⏰ Watch the pump - it should:")
            print("   - Display 'FEED' on screen")  
            print("   - Stop completely")
            print("   - Show countdown timer")
            
            # Wait and observe
            print("\nWaiting 10 seconds to observe...")
            for i in range(10):
                await asyncio.sleep(1)
                print(f"   {10-i}s...")
            
            if not client.is_connected:
                print("❌ Pump disconnected - feed command might have failed")
                return
            
            print("\n2. Resuming normal operation")
            resume_cmd = make_power_on_command(75)
            print(f"TX: {resume_cmd.hex()}")
            
            await client.write_gatt_char(CHAR_UUID, resume_cmd)
            print("📤 Resume command sent!")
            
            await asyncio.sleep(3)
            
            if client.is_connected:
                print("✅ Test completed - pump should be running normally")
            else:
                print("❌ Lost connection during test")
            
            await client.stop_notify(CHAR_UUID)
            
        except Exception as e:
            print(f"❌ Error: {e}")
    
    print(f"\nResponses received: {len(responses)}")

if __name__ == "__main__":
    asyncio.run(test_feed_direct())