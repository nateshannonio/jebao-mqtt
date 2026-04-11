#!/usr/bin/env python3
"""
Test MDP feed mode via MQTT commands
"""

import paho.mqtt.client as mqtt
import time
import json

MQTT_HOST = "192.168.254.195"
MQTT_PORT = 1883
TOPIC_PREFIX = "jebao"
PUMP_ID = "mdp_test_pump"

def test_feed_mode():
    """Test feed mode ON and OFF commands via MQTT"""
    client = mqtt.Client(callback_api_version=mqtt.CallbackAPIVersion.VERSION2)
    
    def on_connect(client, userdata, flags, rc, properties=None):
        if rc == 0:
            print(f"Connected to MQTT broker at {MQTT_HOST}:{MQTT_PORT}")
            
            # Subscribe to all state topics to see responses
            client.subscribe(f"{TOPIC_PREFIX}/{PUMP_ID}/+/state")
            print(f"Subscribed to {TOPIC_PREFIX}/{PUMP_ID}/+/state")
        else:
            print(f"Failed to connect: {rc}")
    
    def on_message(client, userdata, msg):
        topic = msg.topic
        payload = msg.payload.decode('utf-8')
        timestamp = time.strftime("%H:%M:%S")
        print(f"[{timestamp}] {topic} = {payload}")
    
    client.on_connect = on_connect
    client.on_message = on_message
    
    try:
        client.connect(MQTT_HOST, MQTT_PORT, 60)
        client.loop_start()
        
        # Wait for connection
        time.sleep(2)
        
        print(f"\n=== MDP Feed Mode Test via MQTT ===")
        
        # Test sequence
        feed_tests = [
            ("Turn Feed Mode ON", "ON"),
            ("Wait 5 seconds to observe", None),
            ("Turn Feed Mode OFF", "OFF"),
            ("Wait 3 seconds", None),
            ("Turn Feed Mode ON again", "ON"),
            ("Wait 5 seconds to observe", None),
            ("Turn Feed Mode OFF", "OFF"),
        ]
        
        for desc, command in feed_tests:
            print(f"\n{desc}:")
            
            if command is None:
                # Wait period
                wait_time = 5 if "5 seconds" in desc else 3
                for i in range(wait_time):
                    print(f"  Waiting... {wait_time-i}s")
                    time.sleep(1)
                continue
            
            # Send feed command
            topic = f"{TOPIC_PREFIX}/{PUMP_ID}/feed/set"
            print(f"Publishing: {topic} = {command}")
            client.publish(topic, command)
            
            # Wait for response
            time.sleep(2)
        
        print(f"\n=== Feed Mode Test Complete ===")
        print("Observations:")
        print("1. Did you see the pump speed change when feed mode turned ON?")
        print("2. Did the pump return to normal speed when feed mode turned OFF?")
        print("3. Was there any visual indication (LED changes, etc.)?")
        
    except Exception as e:
        print(f"Error: {e}")
    finally:
        client.loop_stop()
        client.disconnect()

if __name__ == "__main__":
    test_feed_mode()