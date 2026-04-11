#!/usr/bin/env python3
"""
Test script to send MQTT commands to the MDP pump
"""

import paho.mqtt.client as mqtt
import time

MQTT_HOST = "192.168.254.195"
MQTT_PORT = 1883
TOPIC_PREFIX = "jebao"
PUMP_ID = "mdp_test_pump"

def test_commands():
    client = mqtt.Client(callback_api_version=mqtt.CallbackAPIVersion.VERSION2)
    
    def on_connect(client, userdata, flags, rc, properties=None):
        if rc == 0:
            print(f"Connected to MQTT broker at {MQTT_HOST}:{MQTT_PORT}")
            
            # Subscribe to state topics to see responses
            client.subscribe(f"{TOPIC_PREFIX}/{PUMP_ID}/+/state")
            print(f"Subscribed to {TOPIC_PREFIX}/{PUMP_ID}/+/state")
        else:
            print(f"Failed to connect: {rc}")
    
    def on_message(client, userdata, msg):
        topic = msg.topic
        payload = msg.payload.decode('utf-8')
        print(f"State Update: {topic} = {payload}")
    
    client.on_connect = on_connect
    client.on_message = on_message
    
    try:
        client.connect(MQTT_HOST, MQTT_PORT, 60)
        client.loop_start()
        
        # Wait for connection
        time.sleep(2)
        
        print("\n=== Testing MDP Pump Commands ===")
        
        # Test 1: Turn pump ON
        print(f"\n1. Sending Power ON command...")
        client.publish(f"{TOPIC_PREFIX}/{PUMP_ID}/power/set", "ON")
        time.sleep(3)
        
        # Test 2: Set speed to 70%
        print(f"\n2. Sending Speed 70% command...")
        client.publish(f"{TOPIC_PREFIX}/{PUMP_ID}/flow/set", "70")
        time.sleep(3)
        
        # Test 3: Set speed to 50%
        print(f"\n3. Sending Speed 50% command...")
        client.publish(f"{TOPIC_PREFIX}/{PUMP_ID}/flow/set", "50")
        time.sleep(3)
        
        # Test 4: Turn pump OFF
        print(f"\n4. Sending Power OFF command...")
        client.publish(f"{TOPIC_PREFIX}/{PUMP_ID}/power/set", "OFF")
        time.sleep(3)
        
        print(f"\n=== Test Complete ===")
        
    except Exception as e:
        print(f"Error: {e}")
    finally:
        client.loop_stop()
        client.disconnect()

if __name__ == "__main__":
    test_commands()