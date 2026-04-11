#!/usr/bin/env python3
"""
Listen to MDP pump BLE traffic
User will manually control feed mode via app while we capture the commands
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

def parse_command_detailed(data: bytes):
    """Parse command in detail to understand structure"""
    if len(data) < 8:
        return "Too short"
    
    # Gizwits header: 6 bytes + 2 byte command + payload
    header = data[:6]
    cmd = int.from_bytes(data[6:8], 'big')
    payload = data[8:]
    
    result = f"CMD: 0x{cmd:04x}"
    
    if cmd == 0x0093 and len(payload) >= 4:  # Control command
        # Command serial number (4 bytes) + P0 data
        cmd_sn = int.from_bytes(payload[:4], 'big')
        p0 = payload[4:]
        result += f", SN: {cmd_sn}, P0: {p0.hex()}"
        
        if len(p0) >= 2:
            action = p0[0]
            flag_byte = p0[1]
            result += f" (Action: 0x{action:02x}, Flags: 0x{flag_byte:02x})"
            
            # Parse flag bits
            flag_bits = []
            for i in range(8):
                if flag_byte & (1 << i):
                    flag_bits.append(f"bit{i}")
            if flag_bits:
                result += f" [{', '.join(flag_bits)}]"
            
            # Additional data
            if len(p0) > 2:
                extra_data = p0[2:]
                result += f", Extra: {extra_data.hex()}"
                if len(extra_data) == 1:
                    result += f" (dec: {extra_data[0]})"
    
    elif cmd == 0x0094:  # ACK response
        result += " (ACK)"
    elif cmd == 0x0062:  # Status report
        if len(payload) >= 4:
            p0 = payload[4:]
            result += f", Status P0: {p0.hex()}"
    
    return result

async def listen_to_pump():
    print(f"🎧 Listening to MDP pump traffic")
    print(f"📱 Use your Jebao app to control feed mode")
    print(f"📋 I'll capture all commands and show you the exact format")
    print(f"Connecting to {MDP_MAC}...")
    
    captured_commands = []
    start_time = time.time()
    
    def handler(sender, data):
        timestamp = time.time() - start_time
        
        # Parse the command
        parsed = parse_command_detailed(data)
        
        print(f"[{timestamp:6.2f}s] RX: {data.hex()}")
        print(f"           -> {parsed}")
        
        # Store for analysis
        captured_commands.append({
            'timestamp': timestamp,
            'raw': data.hex(),
            'parsed': parsed,
            'data': data
        })
        
        print()  # Empty line for readability
    
    async with BleakClient(MDP_MAC) as client:
        try:
            print("✅ Connected! Starting to listen...")
            await client.start_notify(CHAR_UUID, handler)
            
            print("\n" + "="*60)
            print("🎯 INSTRUCTIONS:")
            print("1. Open your Jebao app")
            print("2. Navigate to feed mode controls")
            print("3. Turn feed mode ON")
            print("4. Wait a few seconds")
            print("5. Turn feed mode OFF")
            print("6. Wait a few seconds")
            print("7. Try any other feed-related controls")
            print("8. Press Ctrl+C when done")
            print("="*60)
            print()
            
            # Listen indefinitely until user stops
            try:
                while True:
                    await asyncio.sleep(1)
            except KeyboardInterrupt:
                print("\n🛑 Stopped listening by user")
            
            await client.stop_notify(CHAR_UUID)
            
        except Exception as e:
            print(f"❌ Connection error: {e}")
            return
    
    print(f"\n📊 CAPTURE SUMMARY:")
    print(f"Total commands captured: {len(captured_commands)}")
    print(f"Listening duration: {time.time() - start_time:.1f} seconds")
    
    if captured_commands:
        print(f"\n📋 ALL CAPTURED COMMANDS:")
        print("-" * 80)
        for i, cmd in enumerate(captured_commands):
            print(f"{i+1:2d}. [{cmd['timestamp']:6.2f}s] {cmd['raw']}")
            print(f"    {cmd['parsed']}")
        
        print(f"\n🔍 ANALYSIS:")
        print("Look for commands that appear when you:")
        print("- Turned feed mode ON")
        print("- Turned feed mode OFF")
        print("- These commands will show us the exact feed mode format!")
        
        # Group similar commands
        unique_p0_patterns = {}
        for cmd in captured_commands:
            if '0x0093' in cmd['parsed'] and 'P0:' in cmd['parsed']:
                # Extract P0 pattern
                p0_start = cmd['parsed'].find('P0: ') + 4
                p0_end = cmd['parsed'].find(' ', p0_start)
                if p0_end == -1:
                    p0_pattern = cmd['parsed'][p0_start:]
                else:
                    p0_pattern = cmd['parsed'][p0_start:p0_end]
                
                if p0_pattern not in unique_p0_patterns:
                    unique_p0_patterns[p0_pattern] = []
                unique_p0_patterns[p0_pattern].append(cmd['timestamp'])
        
        if unique_p0_patterns:
            print(f"\n🏷️  UNIQUE COMMAND PATTERNS:")
            for pattern, timestamps in unique_p0_patterns.items():
                print(f"P0: {pattern} -> appeared at: {[f'{t:.1f}s' for t in timestamps]}")
    
    else:
        print("⚠️  No commands captured. Make sure the app is connected and you're using feed controls.")

if __name__ == "__main__":
    asyncio.run(listen_to_pump())