#!/usr/bin/env python3
"""
60-second BLE traffic listener
User will operate pump with physical controller while we capture commands
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

def parse_command(data: bytes, timestamp: float):
    """Parse and analyze command structure"""
    if len(data) < 8:
        return f"[{timestamp:.1f}] Short packet: {data.hex()}"
    
    header = data[:6]
    cmd = int.from_bytes(data[6:8], 'big')
    payload = data[8:]
    
    result = f"[{timestamp:.1f}] CMD: 0x{cmd:04x}"
    
    if cmd == 0x0093 and len(payload) >= 4:  # Control command
        cmd_sn = int.from_bytes(payload[:4], 'big')
        p0 = payload[4:]
        result += f" | SN: {cmd_sn} | P0: {p0.hex()}"
        
        # Parse P0 structure
        if len(p0) >= 1:
            if len(p0) == 1:
                result += f" | Single byte: {p0[0]} (0x{p0[0]:02x})"
            elif len(p0) == 2:
                result += f" | Two bytes: [{p0[0]}, {p0[1]}] (0x{p0[0]:02x}, 0x{p0[1]:02x})"
            elif len(p0) >= 3:
                result += f" | Multi-byte: action=0x{p0[0]:02x}, flag=0x{p0[1]:02x}, extra={p0[2:].hex()}"
                
    elif cmd == 0x0094:  # ACK
        result += " | ACK response"
    elif cmd == 0x0062:  # Status 
        result += " | Status report"
        if len(payload) >= 4:
            p0 = payload[4:]
            result += f" | P0: {p0.hex()}"
    
    return result

async def listen_60_seconds():
    print(f"🎧 60-Second BLE Traffic Listener")
    print(f"📋 Instructions:")
    print(f"   1. I'll connect and start listening")
    print(f"   2. Use your PHYSICAL CONTROLLER to:")
    print(f"      - Change speed (try different values)")
    print(f"      - Turn pump ON/OFF") 
    print(f"      - Activate FEED mode")
    print(f"      - Any other controls you have")
    print(f"   3. I'll capture all commands for 60 seconds")
    print(f"")
    print(f"Connecting to {MDP_MAC}...")
    
    captured_commands = []
    start_time = time.time()
    
    def handler(sender, data):
        timestamp = time.time() - start_time
        
        # Parse and display immediately
        parsed = parse_command(data, timestamp)
        print(parsed)
        
        # Store for analysis
        captured_commands.append({
            'timestamp': timestamp,
            'raw': data.hex(),
            'data': data,
            'parsed': parsed
        })
    
    try:
        async with BleakClient(MDP_MAC) as client:
            print("✅ Connected!")
            await client.start_notify(CHAR_UUID, handler)
            
            # Quick authentication
            print("\n=== AUTHENTICATION ===")
            get_pass = build_packet(0x06, b'')
            await client.write_gatt_char(CHAR_UUID, get_pass)
            await asyncio.sleep(0.5)
            
            if captured_commands:
                resp = captured_commands[-1]['data']
                if len(resp) > 8:
                    passcode = resp[8:]
                    print(f"Passcode: {passcode.hex()}")
                    
                    login = build_packet(0x08, passcode)
                    await client.write_gatt_char(CHAR_UUID, login)
                    await asyncio.sleep(0.5)
                    print("Login complete")
            
            print(f"\n" + "="*80)
            print(f"🎯 READY! Use your physical controller NOW!")
            print(f"⏰ Listening for 60 seconds...")
            print(f"📱 Try these actions:")
            print(f"   - Change speed to different values")
            print(f"   - Power ON/OFF") 
            print(f"   - Feed mode")
            print(f"   - Any other buttons/controls")
            print(f"="*80)
            print()
            
            # Listen for exactly 60 seconds
            end_time = start_time + 60
            
            while time.time() < end_time:
                remaining = int(end_time - time.time())
                
                # Update timer every 10 seconds
                if remaining % 10 == 0 and remaining > 0:
                    print(f"⏰ {remaining} seconds remaining...")
                
                await asyncio.sleep(1)
            
            print(f"\n🛑 60 seconds completed!")
            await client.stop_notify(CHAR_UUID)
            
    except Exception as e:
        print(f"❌ Connection error: {e}")
        return
    
    # Analysis
    print(f"\n" + "="*80)
    print(f"📊 CAPTURE ANALYSIS")
    print(f"="*80)
    print(f"Total commands captured: {len(captured_commands)}")
    print(f"Listening duration: {time.time() - start_time:.1f} seconds")
    
    if captured_commands:
        print(f"\n📋 ALL CAPTURED COMMANDS:")
        print("-" * 100)
        for i, cmd in enumerate(captured_commands):
            print(f"{i+1:2d}. {cmd['parsed']}")
        
        print(f"\n🔍 DETAILED ANALYSIS:")
        
        # Group by command type
        control_commands = []
        status_messages = []
        
        for cmd in captured_commands:
            if '0x0093' in cmd['parsed']:  # Control commands
                control_commands.append(cmd)
            elif '0x0062' in cmd['parsed']:  # Status messages
                status_messages.append(cmd)
        
        print(f"\nControl commands (0x93): {len(control_commands)}")
        print(f"Status messages (0x62): {len(status_messages)}")
        
        if control_commands:
            print(f"\n🎯 CONTROL COMMANDS (these are what we need!):")
            for i, cmd in enumerate(control_commands):
                print(f"  {i+1}. {cmd['parsed']}")
        
        print(f"\n🏆 SUCCESS!")
        print(f"Now we have the EXACT command formats your pump uses!")
        
    else:
        print(f"⚠️  No commands captured")
        print(f"Make sure you used the physical controller during the 60 seconds")

if __name__ == "__main__":
    asyncio.run(listen_60_seconds())