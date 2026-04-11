#!/usr/bin/env python3
"""
Scan for MDP pump BLE traffic using passive scanning
This can capture data even when we can't connect directly
"""

import asyncio
import time
from bleak import BleakScanner, BleakClient
import logging

# Your MDP pump MAC and identifiers
MDP_MAC = "7725528E-75A8-F1C3-71E6-CEF9A6EDA5EE"
MDP_NAME = "Jebao_WiFi-b17c"
SERVICE_UUID = "0000abf0-0000-1000-8000-00805f9b34fb"
CHAR_UUID = "0000abf7-0000-1000-8000-00805f9b34fb"

# Disable bleak debug logs to keep output clean
logging.getLogger('bleak').setLevel(logging.WARNING)

async def scan_and_try_connect():
    print(f"🔍 Scanning for MDP pump...")
    print(f"Looking for: {MDP_MAC} or '{MDP_NAME}'")
    print(f"📱 Make sure your Jebao app is NOT connected to the pump")
    print()
    
    pump_found = False
    connection_attempts = 0
    max_attempts = 5
    
    while not pump_found and connection_attempts < max_attempts:
        connection_attempts += 1
        print(f"🔄 Scan attempt {connection_attempts}/{max_attempts}...")
        
        # Scan for devices
        try:
            devices = await BleakScanner.discover(timeout=10.0)
            
            print(f"Found {len(devices)} BLE devices:")
            for device in devices:
                name = device.name or "Unknown"
                print(f"  📡 {device.address} - {name}")
                
                # Check if this is our pump
                if (device.address == MDP_MAC or 
                    (device.name and MDP_NAME.lower() in device.name.lower())):
                    print(f"🎯 Found MDP pump: {device.address} ({device.name})")
                    pump_found = True
                    
                    # Try to connect and listen
                    try:
                        print(f"🔗 Attempting to connect...")
                        await listen_to_device(device.address)
                        return
                    except Exception as e:
                        print(f"❌ Connection failed: {e}")
                        if "not found" in str(e).lower():
                            print("💡 Pump disappeared - it might be connected to your app")
                        break
            
            if not pump_found:
                print(f"❌ MDP pump not found in scan")
                print(f"💡 Tips:")
                print(f"   - Make sure pump is powered on")
                print(f"   - Close the Jebao app (it might be connected)")
                print(f"   - Move closer to the pump")
                print(f"   - Wait a moment and try again")
                
                await asyncio.sleep(5)
                
        except Exception as e:
            print(f"❌ Scan failed: {e}")
            await asyncio.sleep(3)
    
    if not pump_found:
        print(f"\n🚨 Could not find or connect to pump after {max_attempts} attempts")
        print(f"\n📋 Alternative approach:")
        print(f"1. Make sure pump is on and app is closed")
        print(f"2. Try running this script again")
        print(f"3. Or try connecting with the app first, then close app and run this")

async def listen_to_device(mac_address):
    print(f"🎧 Starting to listen to {mac_address}...")
    
    captured_data = []
    start_time = time.time()
    
    def notification_handler(sender, data):
        timestamp = time.time() - start_time
        
        print(f"[{timestamp:6.2f}s] 📥 RX: {data.hex()}")
        
        # Parse the data
        if len(data) >= 8:
            cmd = int.from_bytes(data[6:8], 'big') if len(data) >= 8 else 0
            print(f"           📋 CMD: 0x{cmd:04x}")
            
            if cmd == 0x0093 and len(data) > 12:  # Control command
                p0 = data[12:]
                print(f"           📄 P0: {p0.hex()}")
                if len(p0) >= 2:
                    action = p0[0]
                    flags = p0[1]
                    print(f"           ⚡ Action: 0x{action:02x}, Flags: 0x{flags:02x} (binary: {format(flags, '08b')})")
        
        captured_data.append({
            'timestamp': timestamp,
            'data': data,
            'hex': data.hex()
        })
        print()
    
    async with BleakClient(mac_address) as client:
        print(f"✅ Connected to pump!")
        
        # Start notifications
        await client.start_notify(CHAR_UUID, notification_handler)
        
        print(f"\n" + "="*70)
        print(f"🎯 READY TO CAPTURE FEED MODE COMMANDS!")
        print(f"")
        print(f"📱 NOW:")
        print(f"1. Open your Jebao app")
        print(f"2. Connect to the pump in the app")
        print(f"3. Find the feed mode control")
        print(f"4. Turn feed mode ON")
        print(f"5. Wait 3-5 seconds")
        print(f"6. Turn feed mode OFF") 
        print(f"7. Wait 3-5 seconds")
        print(f"8. Try turning it ON again")
        print(f"9. Press Ctrl+C here when done")
        print(f"")
        print(f"🔍 I'll show you exactly what commands are sent!")
        print(f"="*70)
        print()
        
        try:
            # Listen until user interrupts
            while True:
                await asyncio.sleep(0.1)
                
        except KeyboardInterrupt:
            print(f"\n🛑 Stopping capture...")
        
        await client.stop_notify(CHAR_UUID)
    
    # Analysis
    print(f"\n📊 CAPTURE RESULTS:")
    print(f"Total commands captured: {len(captured_data)}")
    
    if captured_data:
        print(f"\n📋 ALL CAPTURED COMMANDS:")
        for i, item in enumerate(captured_data):
            print(f"{i+1:2d}. [{item['timestamp']:6.2f}s] {item['hex']}")
        
        print(f"\n🔍 Now we can identify the feed mode commands!")
        print(f"Look at the timestamps when you turned feed mode ON/OFF")
    else:
        print(f"⚠️  No data captured - make sure app was connected and controlling pump")

if __name__ == "__main__":
    print(f"🎧 MDP Feed Mode Command Capture Tool")
    print(f"🎯 Goal: Capture the exact commands for feed mode ON/OFF")
    print()
    
    asyncio.run(scan_and_try_connect())