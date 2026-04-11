#!/usr/bin/env python3
"""
Test MDP feed mode with 2-minute timer
"""

import paho.mqtt.client as mqtt
import time
import json

MQTT_HOST = "192.168.254.195"
MQTT_PORT = 1883
TOPIC_PREFIX = "jebao"
PUMP_ID = "mdp_test_pump"

def test_feed_mode_timer():
    """Test MDP feed mode with automatic timer"""
    client = mqtt.Client(callback_api_version=mqtt.CallbackAPIVersion.VERSION2)
    
    feed_start_time = None
    pump_states = {}
    
    def on_connect(client, userdata, flags, rc, properties=None):
        if rc == 0:
            print(f"✅ Connected to MQTT broker at {MQTT_HOST}:{MQTT_PORT}")
            
            # Subscribe to all state topics
            client.subscribe(f"{TOPIC_PREFIX}/{PUMP_ID}/+/state")
            print(f"📡 Subscribed to {TOPIC_PREFIX}/{PUMP_ID}/+/state")
        else:
            print(f"❌ Failed to connect: {rc}")
    
    def on_message(client, userdata, msg):
        nonlocal feed_start_time, pump_states
        
        topic = msg.topic
        payload = msg.payload.decode('utf-8')
        timestamp = time.strftime("%H:%M:%S")
        
        # Extract entity type
        entity = topic.split('/')[-2]
        pump_states[entity] = payload
        
        print(f"[{timestamp}] {entity}: {payload}")
        
        # Track feed mode timing
        if entity == "feed":
            if payload == "ON" and feed_start_time is None:
                feed_start_time = time.time()
                print(f"🐟 Feed mode started! Timer should run for 2 minutes...")
            elif payload == "OFF" and feed_start_time is not None:
                elapsed = time.time() - feed_start_time
                print(f"🎯 Feed mode ended after {elapsed:.1f} seconds")
                if 115 <= elapsed <= 125:  # Allow 5-second tolerance
                    print(f"✅ Timer worked correctly! (~2 minutes)")
                else:
                    print(f"⚠️  Timer seems off (expected ~120 seconds)")
                feed_start_time = None
        
        # Show current pump status
        if len(pump_states) >= 3:  # power, feed, flow
            power = pump_states.get('power', 'Unknown')
            feed = pump_states.get('feed', 'Unknown') 
            flow = pump_states.get('flow', 'Unknown')
            print(f"    📊 Status: Power={power}, Feed={feed}, Flow={flow}%")
    
    client.on_connect = on_connect
    client.on_message = on_message
    
    try:
        client.connect(MQTT_HOST, MQTT_PORT, 60)
        client.loop_start()
        
        # Wait for connection
        time.sleep(2)
        
        print(f"\n🧪 Testing MDP Feed Mode with Timer")
        print(f"═══════════════════════════════════════")
        
        # Test 1: Normal feed mode (should auto-resume after 2 min)
        print(f"\n1️⃣ Starting feed mode (should stop pump for 2 minutes)")
        client.publish(f"{TOPIC_PREFIX}/{PUMP_ID}/feed/set", "ON")
        
        print(f"⏰ Waiting for automatic resume...")
        print(f"   (This should take about 2 minutes)")
        
        # Wait up to 150 seconds for auto-resume
        for i in range(150):
            time.sleep(1)
            if i % 10 == 0 and i > 0:  # Update every 10 seconds
                elapsed = i
                remaining = max(0, 120 - elapsed)
                print(f"   ⏳ {elapsed}s elapsed, ~{remaining}s remaining...")
            
            # Check if feed mode ended automatically
            if 'feed' in pump_states and pump_states['feed'] == 'OFF':
                break
        
        time.sleep(3)
        
        # Test 2: Early termination
        print(f"\n2️⃣ Testing early termination")
        print(f"Starting feed mode again...")
        client.publish(f"{TOPIC_PREFIX}/{PUMP_ID}/feed/set", "ON")
        
        time.sleep(10)  # Wait 10 seconds
        
        print(f"Ending feed mode early...")
        client.publish(f"{TOPIC_PREFIX}/{PUMP_ID}/feed/set", "OFF")
        
        time.sleep(3)
        
        print(f"\n✅ Feed mode timer test completed!")
        
    except Exception as e:
        print(f"❌ Error: {e}")
    finally:
        client.loop_stop()
        client.disconnect()

if __name__ == "__main__":
    print(f"🐟 MDP Feed Mode Timer Test")
    print(f"Testing 2-minute auto-resume functionality")
    print()
    test_feed_mode_timer()