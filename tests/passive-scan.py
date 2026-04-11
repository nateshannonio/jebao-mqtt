#!/usr/bin/env python3
"""
Passive BLE scanning - don't connect, just listen for advertisements
This way app can connect while we passively monitor
"""

import asyncio
import time
from bleak import BleakScanner

# Your MDP pump MAC
MDP_MAC = "7725528E-75A8-F1C3-71E6-CEF9A6EDA5EE"
MDP_NAME = "Jebao_WiFi-b17c"

async def passive_monitor():
    print(f"📡 Passive BLE Monitor")
    print(f"🎯 Goal: Monitor BLE advertisements while app controls pump")
    print(f"📋 Approach: No connection - just passive scanning")
    print(f"")
    print(f"Looking for pump: {MDP_MAC} ({MDP_NAME})")
    print()
    
    captured_ads = []
    start_time = time.time()
    
    def detection_callback(device, advertisement_data):
        timestamp = time.time() - start_time
        
        # Check if this is our pump
        is_target = (device.address == MDP_MAC or 
                    (device.name and MDP_NAME.lower() in device.name.lower()))
        
        if is_target:
            print(f"[{timestamp:.1f}] 🎯 TARGET PUMP: {device.address}")
            print(f"    Name: {device.name}")
            print(f"    RSSI: {advertisement_data.rssi}")
            print(f"    Service UUIDs: {advertisement_data.service_uuids}")
            print(f"    Manufacturer Data: {advertisement_data.manufacturer_data}")
            print(f"    Service Data: {advertisement_data.service_data}")
            print()
            
            captured_ads.append({
                'timestamp': timestamp,
                'device': device,
                'advertisement': advertisement_data
            })
    
    print(f"🔍 Starting passive scan...")
    print(f"📱 NOW: Use your Jebao app to control the pump")
    print(f"⏰ Scanning for 60 seconds...")
    print(f"")
    
    try:
        # Create scanner
        scanner = BleakScanner(detection_callback)
        
        # Start scanning
        await scanner.start()
        print(f"✅ Scanner active - use your app now!")
        print(f"👀 Watching for pump advertisements...")
        print()
        
        # Scan for 60 seconds
        for remaining in range(60, 0, -1):
            if remaining % 10 == 0:
                print(f"⏰ {remaining} seconds remaining...")
            await asyncio.sleep(1)
        
        # Stop scanning
        await scanner.stop()
        print(f"\n🛑 Scan complete!")
        
    except Exception as e:
        print(f"❌ Scanner error: {e}")
    
    # Results
    print(f"\n📊 RESULTS:")
    print(f"Total pump advertisements: {len(captured_ads)}")
    
    if captured_ads:
        print(f"\n📋 CAPTURED ADVERTISEMENTS:")
        for i, ad in enumerate(captured_ads):
            print(f"{i+1}. [{ad['timestamp']:.1f}s] {ad['device'].name}")
            print(f"   Address: {ad['device'].address}")
            print(f"   RSSI: {ad['advertisement'].rssi}")
            if ad['advertisement'].manufacturer_data:
                print(f"   Manufacturer Data: {ad['advertisement'].manufacturer_data}")
            if ad['advertisement'].service_data:
                print(f"   Service Data: {ad['advertisement'].service_data}")
            print()
    else:
        print(f"❌ No pump advertisements captured")
        print(f"💡 This suggests pump doesn't broadcast when app is connected")
    
    print(f"\n🤔 Alternative: Try the quick-capture method")

if __name__ == "__main__":
    asyncio.run(passive_monitor())