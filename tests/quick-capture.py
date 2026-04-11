#!/usr/bin/env python3
"""
Quick capture approach:
1. Connect, listen for 10 seconds, disconnect
2. User immediately connects app and sends ONE command
3. Repeat for each command type
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

async def quick_capture_session():
    print(f"🎯 Quick Capture Method")
    print(f"📋 Process:")
    print(f"   1. I'll connect and listen for 10 seconds")
    print(f"   2. I'll disconnect")
    print(f"   3. You immediately open app and send ONE command")
    print(f"   4. Repeat for each command type")
    print()
    
    sessions = [
        "Speed change (e.g., 75% → 80%)",
        "Power OFF", 
        "Power ON",
        "Feed mode ON",
        "Feed mode OFF",
    ]
    
    for i, command_type in enumerate(sessions):
        print(f"\n" + "="*60)
        print(f"📱 SESSION {i+1}/{len(sessions)}: {command_type}")
        print(f"="*60)
        
        captured = []
        
        def handler(sender, data):
            timestamp = time.time()
            captured.append((timestamp, data))
            print(f"[{timestamp:.1f}] RX: {data.hex()}")
            
            # Quick analysis
            if len(data) >= 8:
                cmd = int.from_bytes(data[6:8], 'big')
                if cmd == 0x0093:
                    print(f"  🎯 CONTROL COMMAND: {data.hex()}")
                elif cmd == 0x0094:
                    print(f"  ✅ ACK")
        
        # Step 1: Connect and listen briefly
        print(f"🔗 Connecting to capture any residual traffic...")
        
        try:
            async with BleakClient(MDP_MAC) as client:
                await client.start_notify(CHAR_UUID, handler)
                
                # Quick auth
                get_pass = build_packet(0x06, b'')
                await client.write_gatt_char(CHAR_UUID, get_pass)
                await asyncio.sleep(0.3)
                
                if captured:
                    resp = captured[-1][1]
                    if len(resp) > 8:
                        passcode = resp[8:]
                        login = build_packet(0x08, passcode)
                        await client.write_gatt_char(CHAR_UUID, login)
                        await asyncio.sleep(0.3)
                
                # Listen briefly
                print(f"👂 Listening for 10 seconds...")
                for countdown in range(10, 0, -1):
                    print(f"   {countdown}s remaining...")
                    await asyncio.sleep(1)
                
                await client.stop_notify(CHAR_UUID)
                print(f"🔌 Disconnected!")
                
        except Exception as e:
            print(f"❌ Error: {e}")
        
        # Step 2: User action
        print(f"\n📱 NOW: Open your app IMMEDIATELY and do:")
        print(f"   🎯 {command_type}")
        print(f"   ⚡ Do it QUICKLY while pump is free")
        print(f"")
        input("Press Enter when you've sent the command...")
        
        if captured:
            print(f"\n📊 Captured {len(captured)} packets:")
            for ts, data in captured:
                if len(data) >= 8:
                    cmd = int.from_bytes(data[6:8], 'big')
                    print(f"  [{ts:.1f}] CMD 0x{cmd:04x}: {data.hex()}")
        else:
            print(f"❌ No packets captured")
        
        # Pause between sessions
        if i < len(sessions) - 1:
            print(f"\n⏸️  Preparing for next session...")
            await asyncio.sleep(3)
    
    print(f"\n🏁 All sessions complete!")
    print(f"📋 Summary: Check output above for any 0x93 control commands")

if __name__ == "__main__":
    print(f"🎯 MDP Quick Capture - Working Around Single BLE Connection Limit")
    print()
    asyncio.run(quick_capture_session())