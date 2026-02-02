#!/usr/bin/env python3
"""
Jebao Pump MQTT Bridge for Home Assistant

This script connects to Jebao DMP series aquarium pumps via BLE
and exposes them to Home Assistant through MQTT with auto-discovery.

Usage:
    python3 jebao_mqtt_bridge.py --config config.yaml

Author: Reverse engineered from Jebao Android app
"""

import asyncio
import argparse
import json
import logging
import random
import signal
import sys
import time
from dataclasses import dataclass, field
from datetime import datetime, date
from pathlib import Path
from typing import Optional, Callable

import yaml
from bleak import BleakClient, BleakScanner
from bleak.exc import BleakError
import paho.mqtt.client as mqtt

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger('jebao_mqtt')

# BLE Constants
SERVICE_UUID = "0000abf0-0000-1000-8000-00805f9b34fb"
CHAR_UUID = "0000abf7-0000-1000-8000-00805f9b34fb"

# Gizwits Protocol Commands
CMD_GET_PASSCODE = 0x0006
CMD_LOGIN = 0x0008
CMD_CONTROL = 0x0093

# Attribute definitions (type, attr_hi, attr_lo)
ATTR_POWER = (0x00, 0x00, 0x01)
ATTR_FEED = (0x00, 0x00, 0x04)
ATTR_MODE = (0x00, 0x10, 0x02)
ATTR_FLOW = (0x00, 0x80, 0x00)
ATTR_FREQUENCY = (0x01, 0x00, 0x00)

# Mode mappings (BLE value -> Display name)
MODES = {
    0: "Classic Wave",   # Mode 1 on controller
    1: "Cross-flow",     # Mode 5 on controller
    2: "Sine Wave",      # Mode 2 on controller
    4: "Random",         # Mode 4 on controller
    6: "Constant",       # Mode 3 on controller
}
MODE_VALUES = {v: k for k, v in MODES.items()}

# Statistics configuration
STATE_PUBLISH_INTERVAL = 60  # Publish state every 60 seconds for better graphs


@dataclass
class PumpState:
    """Current state of a pump"""
    power: bool = False
    feed: bool = False
    mode: int = 0
    flow: int = 50
    frequency: int = 8
    connected: bool = False
    # Runtime tracking
    power_on_time: float = 0.0  # Timestamp when power turned on
    runtime_today: float = 0.0  # Hours running today
    last_runtime_reset: str = ""  # Date of last reset (YYYY-MM-DD)
    # Track if we've received actual state from pump
    state_initialized: bool = False
    

@dataclass 
class PumpConfig:
    """Configuration for a single pump"""
    name: str
    mac: str
    id: str = ""
    flow_min: int = 30
    flow_max: int = 100
    frequency_min: int = 5
    frequency_max: int = 20
    
    def __post_init__(self):
        if not self.id:
            # Generate ID from name
            self.id = self.name.lower().replace(" ", "_").replace("-", "_")


class JebaoPump:
    """Handles BLE communication with a single Jebao pump"""
    
    def __init__(self, config: PumpConfig, state_callback: Callable, pump_index: int = 0):
        self.config = config
        self.state_callback = state_callback
        self.state = PumpState()
        self.client: Optional[BleakClient] = None
        self.passcode: bytes = b''
        self.command_sn = 1
        self.authenticated = False
        self._connect_lock = asyncio.Lock()
        self._reconnect_task = None
        self._running = True  # Flag to stop reconnect on shutdown
        self._loop: Optional[asyncio.AbstractEventLoop] = None  # Event loop reference
        self._pump_index = pump_index  # Used to stagger reconnection attempts
        
    def _make_packet(self, cmd: int, payload: bytes = b'') -> bytes:
        """Build a Gizwits protocol packet"""
        length = 3 + len(payload)
        return bytes([0x00, 0x00, 0x00, 0x03, length, 0x00]) + \
               cmd.to_bytes(2, 'big') + payload
    
    def _make_write_p0(self, attr: tuple, value: int) -> bytes:
        """Build P0 data for writing an attribute"""
        p0 = bytearray(11)
        p0[0] = 0x11  # Write action
        p0[7] = attr[0]  # Type
        p0[8] = attr[1]  # Attr hi
        p0[9] = attr[2]  # Attr lo
        p0[10] = value
        return bytes(p0)
    
    def _notification_handler(self, sender, data: bytes):
        """Handle incoming BLE notifications"""
        if len(data) < 8:
            return
            
        cmd = int.from_bytes(data[6:8], 'big')
        
        if cmd == 0x0007 and len(data) > 8:
            # Passcode response
            self.passcode = data[8:]
            logger.debug(f"[{self.config.name}] Received passcode")
            asyncio.create_task(self._send_login())
            
        elif cmd == 0x0009:
            # Login response
            if len(data) > 8 and data[8] == 0x00:
                logger.info(f"[{self.config.name}] Login successful")
                self.authenticated = True
                self.state.connected = True
                self.state_callback(self)
            else:
                logger.warning(f"[{self.config.name}] Login failed")
                
        elif cmd == 0x0093 and len(data) >= 19:
            # Status update
            p0 = data[12:]
            if len(p0) >= 11:
                type_byte = p0[7]
                attr_hi = p0[8]
                attr_lo = p0[9]
                value = p0[10]
                
                self._update_state(type_byte, attr_hi, attr_lo, value)
                
        elif cmd == 0x0094:
            # ACK
            logger.debug(f"[{self.config.name}] Command acknowledged")
    
    def _update_state(self, type_byte: int, attr_hi: int, attr_lo: int, value: int):
        """Update state from received attribute"""
        changed = False
        
        if type_byte == 0x00 and attr_hi == 0x00 and attr_lo == 0x01:
            if self.state.power != bool(value):
                # Track runtime
                now = time.time()
                if value:  # Turning ON
                    self.state.power_on_time = now
                else:  # Turning OFF
                    if self.state.power_on_time > 0:
                        # Add elapsed time to runtime
                        elapsed_hours = (now - self.state.power_on_time) / 3600
                        self.state.runtime_today += elapsed_hours
                        self.state.power_on_time = 0
                
                self.state.power = bool(value)
                changed = True
                logger.info(f"[{self.config.name}] Power: {'ON' if value else 'OFF'}")
                
        elif type_byte == 0x00 and attr_hi == 0x00 and attr_lo == 0x04:
            if self.state.feed != bool(value):
                self.state.feed = bool(value)
                changed = True
                logger.info(f"[{self.config.name}] Feed: {'ON' if value else 'OFF'}")
                
        elif type_byte == 0x00 and attr_hi == 0x10 and attr_lo == 0x02:
            if self.state.mode != value:
                self.state.mode = value
                changed = True
                logger.info(f"[{self.config.name}] Mode: {MODES.get(value, 'Unknown')}")
                
        elif type_byte == 0x00 and attr_hi == 0x80 and attr_lo == 0x00:
            if self.state.flow != value:
                self.state.flow = value
                changed = True
                logger.info(f"[{self.config.name}] Flow: {value}%")
                
        elif type_byte == 0x01 and attr_hi == 0x00 and attr_lo == 0x00:
            if self.state.frequency != value:
                self.state.frequency = value
                changed = True
                logger.info(f"[{self.config.name}] Frequency: {value}s")
        
        if changed:
            self.state.state_initialized = True
            self.state_callback(self)
    
    async def _send_login(self):
        """Send login packet with passcode"""
        if self.client and self.client.is_connected:
            packet = self._make_packet(CMD_LOGIN, self.passcode)
            await self.client.write_gatt_char(CHAR_UUID, packet, response=False)
    
    async def _send_command(self, attr: tuple, value: int):
        """Send a control command"""
        if not self.authenticated or not self.client or not self.client.is_connected:
            logger.warning(f"[{self.config.name}] Cannot send - not connected")
            return False
            
        p0 = self._make_write_p0(attr, value)
        payload = self.command_sn.to_bytes(4, 'big') + p0
        packet = self._make_packet(CMD_CONTROL, payload)
        
        self.command_sn += 1
        
        try:
            await self.client.write_gatt_char(CHAR_UUID, packet, response=False)
            return True
        except BleakError as e:
            logger.error(f"[{self.config.name}] Send failed: {e}")
            return False
    
    async def connect(self):
        """Connect to the pump"""
        async with self._connect_lock:
            if self.client and self.client.is_connected:
                return True
            
            # Store event loop reference for callbacks
            self._loop = asyncio.get_running_loop()
                
            try:
                logger.info(f"[{self.config.name}] Connecting to {self.config.mac}...")
                
                self.client = BleakClient(
                    self.config.mac,
                    disconnected_callback=self._on_disconnect
                )
                
                await self.client.connect()
                logger.info(f"[{self.config.name}] Connected")
                
                # Subscribe to notifications
                await self.client.start_notify(CHAR_UUID, self._notification_handler)
                
                # Request passcode
                packet = self._make_packet(CMD_GET_PASSCODE)
                await self.client.write_gatt_char(CHAR_UUID, packet, response=False)
                
                # Wait for authentication
                for _ in range(50):  # 5 second timeout
                    if self.authenticated:
                        return True
                    await asyncio.sleep(0.1)
                
                logger.warning(f"[{self.config.name}] Authentication timeout")
                await self._cleanup_connection()
                return False
                
            except BleakError as e:
                logger.error(f"[{self.config.name}] Connection failed: {e}")
                await self._cleanup_connection()
                return False
            except Exception as e:
                logger.error(f"[{self.config.name}] Unexpected error during connect: {e}")
                await self._cleanup_connection()
                return False
    
    async def _cleanup_connection(self):
        """Clean up connection state"""
        self.authenticated = False
        self.state.connected = False
        if self.client:
            try:
                await self.client.disconnect()
            except Exception:
                pass
            self.client = None
    
    def _on_disconnect(self, client):
        """Handle disconnection - called from BLE callback"""
        logger.warning(f"[{self.config.name}] Disconnected")
        self.authenticated = False
        self.state.connected = False
        self.state.state_initialized = False  # Reset so we don't publish stale data
        
        # Notify state change
        try:
            self.state_callback(self)
        except Exception as e:
            logger.error(f"[{self.config.name}] Error in state callback: {e}")
        
        # Schedule reconnect in the event loop
        if self._loop is not None:
            try:
                # Check if there's already a reconnect task running
                if self._reconnect_task is None or self._reconnect_task.done():
                    self._reconnect_task = asyncio.run_coroutine_threadsafe(
                        self._reconnect_loop(), self._loop
                    )
            except Exception as e:
                logger.error(f"[{self.config.name}] Failed to schedule reconnect: {e}")
    
    async def _reconnect_loop(self):
        """Attempt to reconnect with backoff"""
        delay = 5
        max_delay = 300  # Max 5 minutes between attempts
        max_attempts = 0  # 0 = infinite
        attempts = 0
        
        # Stagger reconnection attempts for multiple pumps to avoid BLE adapter contention
        # Each pump waits an additional 2 seconds based on its index
        stagger_delay = self._pump_index * 2
        if stagger_delay > 0:
            logger.info(f"[{self.config.name}] Staggering reconnect by {stagger_delay}s")
            await asyncio.sleep(stagger_delay)
        
        while not self.authenticated:
            attempts += 1
            if max_attempts > 0 and attempts > max_attempts:
                logger.error(f"[{self.config.name}] Max reconnection attempts reached")
                break
                
            logger.info(f"[{self.config.name}] Reconnecting in {delay:.1f}s... (attempt {attempts})")
            await asyncio.sleep(delay)
            
            # Check if we should still be trying
            if not self._running:
                logger.info(f"[{self.config.name}] Stopping reconnect - bridge shutting down")
                break
            
            try:
                if await self.connect():
                    logger.info(f"[{self.config.name}] Reconnection successful")
                    break
            except Exception as e:
                logger.error(f"[{self.config.name}] Reconnection attempt failed: {e}")
            
            # Exponential backoff with jitter to prevent synchronized retries
            jitter = random.uniform(0, delay * 0.1)  # Up to 10% jitter
            delay = min(delay * 2 + jitter, max_delay)
        
        logger.debug(f"[{self.config.name}] Reconnect loop ended")
    
    async def disconnect(self):
        """Disconnect from the pump"""
        self._running = False
        
        if self._reconnect_task:
            try:
                if hasattr(self._reconnect_task, 'cancel'):
                    self._reconnect_task.cancel()
            except Exception:
                pass
            
        await self._cleanup_connection()
    
    # Control methods
    async def set_power(self, on: bool):
        logger.info(f"[{self.config.name}] Setting power: {'ON' if on else 'OFF'}")
        return await self._send_command(ATTR_POWER, 1 if on else 0)
    
    async def set_feed(self, on: bool):
        logger.info(f"[{self.config.name}] Setting feed: {'ON' if on else 'OFF'}")
        return await self._send_command(ATTR_FEED, 1 if on else 0)
    
    async def set_flow(self, percent: int):
        percent = max(self.config.flow_min, min(self.config.flow_max, percent))
        logger.info(f"[{self.config.name}] Setting flow: {percent}%")
        return await self._send_command(ATTR_FLOW, percent)
    
    async def set_frequency(self, seconds: int):
        seconds = max(self.config.frequency_min, min(self.config.frequency_max, seconds))
        logger.info(f"[{self.config.name}] Setting frequency: {seconds}s")
        return await self._send_command(ATTR_FREQUENCY, seconds)
    
    async def set_mode(self, mode: int):
        if mode in MODES:
            logger.info(f"[{self.config.name}] Setting mode: {MODES[mode]}")
            return await self._send_command(ATTR_MODE, mode)
        return False
    
    async def set_mode_by_name(self, mode_name: str):
        if mode_name in MODE_VALUES:
            return await self.set_mode(MODE_VALUES[mode_name])
        return False


class MQTTBridge:
    """MQTT bridge for multiple Jebao pumps"""
    
    def __init__(self, config_path: str):
        self.config = self._load_config(config_path)
        self.pumps: dict[str, JebaoPump] = {}
        self.mqtt_client: Optional[mqtt.Client] = None
        self._running = False
        self._loop: Optional[asyncio.AbstractEventLoop] = None
        
    def _load_config(self, path: str) -> dict:
        """Load configuration from YAML file"""
        with open(path) as f:
            return yaml.safe_load(f)
    
    def _get_mqtt_config(self) -> dict:
        """Get MQTT configuration with defaults"""
        mqtt_config = self.config.get('mqtt', {})
        return {
            'host': mqtt_config.get('host', 'localhost'),
            'port': mqtt_config.get('port', 1883),
            'username': mqtt_config.get('username'),
            'password': mqtt_config.get('password'),
            'client_id': mqtt_config.get('client_id', 'jebao_mqtt_bridge'),
            'discovery_prefix': mqtt_config.get('discovery_prefix', 'homeassistant'),
            'topic_prefix': mqtt_config.get('topic_prefix', 'jebao'),
        }
    
    def _on_mqtt_connect(self, client, userdata, flags, rc, properties=None):
        """Handle MQTT connection"""
        if rc == 0:
            logger.info("Connected to MQTT broker")
            # Subscribe to command topics for all pumps
            for pump_id in self.pumps:
                self._subscribe_pump_commands(pump_id)
            # Publish discovery and state for all pumps
            for pump in self.pumps.values():
                self._publish_discovery(pump)
                self._publish_state(pump)
        else:
            logger.error(f"MQTT connection failed: {rc}")
    
    def _on_mqtt_message(self, client, userdata, msg):
        """Handle incoming MQTT messages"""
        topic = msg.topic
        payload = msg.payload.decode('utf-8')
        
        logger.debug(f"MQTT message: {topic} = {payload}")
        
        # Parse topic: jebao/{pump_id}/{entity}/set
        parts = topic.split('/')
        if len(parts) < 4 or parts[-1] != 'set':
            return
            
        mqtt_config = self._get_mqtt_config()
        if parts[0] != mqtt_config['topic_prefix']:
            return
            
        pump_id = parts[1]
        entity = parts[2]
        
        if pump_id not in self.pumps:
            logger.warning(f"Unknown pump: {pump_id}")
            return
            
        pump = self.pumps[pump_id]
        
        # Schedule the async command in the main event loop (thread-safe)
        if self._loop is not None:
            asyncio.run_coroutine_threadsafe(
                self._handle_command(pump, entity, payload),
                self._loop
            )
    
    async def _handle_command(self, pump: JebaoPump, entity: str, payload: str):
        """Handle a command for a pump"""
        try:
            if entity == 'power':
                await pump.set_power(payload.lower() in ('on', 'true', '1'))
            elif entity == 'feed':
                await pump.set_feed(payload.lower() in ('on', 'true', '1'))
            elif entity == 'flow':
                await pump.set_flow(int(float(payload)))
            elif entity == 'frequency':
                await pump.set_frequency(int(float(payload)))
            elif entity == 'mode':
                await pump.set_mode_by_name(payload)
        except Exception as e:
            logger.error(f"Command failed: {e}")
    
    def _subscribe_pump_commands(self, pump_id: str):
        """Subscribe to command topics for a pump"""
        mqtt_config = self._get_mqtt_config()
        prefix = mqtt_config['topic_prefix']
        
        topics = ['power', 'feed', 'flow', 'frequency', 'mode']
        for topic in topics:
            self.mqtt_client.subscribe(f"{prefix}/{pump_id}/{topic}/set")
    
    def _publish_discovery(self, pump: JebaoPump):
        """Publish Home Assistant MQTT discovery messages"""
        mqtt_config = self._get_mqtt_config()
        discovery_prefix = mqtt_config['discovery_prefix']
        topic_prefix = mqtt_config['topic_prefix']
        pump_id = pump.config.id
        
        device_info = {
            "identifiers": [f"jebao_{pump_id}"],
            "name": pump.config.name,
            "manufacturer": "Jebao",
            "model": "DMP-65",
        }
        
        # Power switch
        self._publish_discovery_entity(
            discovery_prefix, "switch", pump_id, "power",
            {
                "name": "Power",
                "command_topic": f"{topic_prefix}/{pump_id}/power/set",
                "state_topic": f"{topic_prefix}/{pump_id}/power/state",
                "payload_on": "ON",
                "payload_off": "OFF",
                "icon": "mdi:power",
                "device": device_info,
                "unique_id": f"jebao_{pump_id}_power",
            }
        )
        
        # Feed switch
        self._publish_discovery_entity(
            discovery_prefix, "switch", pump_id, "feed",
            {
                "name": "Feed Mode",
                "command_topic": f"{topic_prefix}/{pump_id}/feed/set",
                "state_topic": f"{topic_prefix}/{pump_id}/feed/state",
                "payload_on": "ON",
                "payload_off": "OFF",
                "icon": "mdi:fish",
                "device": device_info,
                "unique_id": f"jebao_{pump_id}_feed",
            }
        )
        
        # Flow number - with statistics support
        self._publish_discovery_entity(
            discovery_prefix, "number", pump_id, "flow",
            {
                "name": "Flow",
                "command_topic": f"{topic_prefix}/{pump_id}/flow/set",
                "state_topic": f"{topic_prefix}/{pump_id}/flow/state",
                "min": pump.config.flow_min,
                "max": pump.config.flow_max,
                "step": 1,
                "unit_of_measurement": "%",
                "icon": "mdi:waves",
                "device": device_info,
                "unique_id": f"jebao_{pump_id}_flow",
            }
        )
        
        # Flow sensor (for statistics/graphs)
        self._publish_discovery_entity(
            discovery_prefix, "sensor", pump_id, "flow_sensor",
            {
                "name": "Flow Level",
                "state_topic": f"{topic_prefix}/{pump_id}/flow/state",
                "unit_of_measurement": "%",
                "icon": "mdi:waves",
                "device": device_info,
                "unique_id": f"jebao_{pump_id}_flow_sensor",
                "state_class": "measurement",  # Enables long-term statistics
            }
        )
        
        # Frequency number - with statistics support
        self._publish_discovery_entity(
            discovery_prefix, "number", pump_id, "frequency",
            {
                "name": "Frequency",
                "command_topic": f"{topic_prefix}/{pump_id}/frequency/set",
                "state_topic": f"{topic_prefix}/{pump_id}/frequency/state",
                "min": pump.config.frequency_min,
                "max": pump.config.frequency_max,
                "step": 1,
                "unit_of_measurement": "s",
                "icon": "mdi:timer",
                "device": device_info,
                "unique_id": f"jebao_{pump_id}_frequency",
            }
        )
        
        # Frequency sensor (for statistics/graphs)
        self._publish_discovery_entity(
            discovery_prefix, "sensor", pump_id, "frequency_sensor",
            {
                "name": "Frequency Level",
                "state_topic": f"{topic_prefix}/{pump_id}/frequency/state",
                "unit_of_measurement": "s",
                "icon": "mdi:timer",
                "device": device_info,
                "unique_id": f"jebao_{pump_id}_frequency_sensor",
                "state_class": "measurement",  # Enables long-term statistics
            }
        )
        
        # Runtime counter (tracks total ON time)
        self._publish_discovery_entity(
            discovery_prefix, "sensor", pump_id, "runtime",
            {
                "name": "Runtime Today",
                "state_topic": f"{topic_prefix}/{pump_id}/runtime/state",
                "unit_of_measurement": "h",
                "icon": "mdi:timer-outline",
                "device": device_info,
                "unique_id": f"jebao_{pump_id}_runtime",
                "state_class": "total_increasing",  # Tracks cumulative value
            }
        )
        
        # Mode select
        self._publish_discovery_entity(
            discovery_prefix, "select", pump_id, "mode",
            {
                "name": "Mode",
                "command_topic": f"{topic_prefix}/{pump_id}/mode/set",
                "state_topic": f"{topic_prefix}/{pump_id}/mode/state",
                "options": list(MODES.values()),
                "icon": "mdi:waves-arrow-right",
                "device": device_info,
                "unique_id": f"jebao_{pump_id}_mode",
            }
        )
        
        # Connected binary sensor
        self._publish_discovery_entity(
            discovery_prefix, "binary_sensor", pump_id, "connected",
            {
                "name": "Connected",
                "state_topic": f"{topic_prefix}/{pump_id}/connected/state",
                "payload_on": "ON",
                "payload_off": "OFF",
                "device_class": "connectivity",
                "device": device_info,
                "unique_id": f"jebao_{pump_id}_connected",
            }
        )
        
        logger.info(f"[{pump.config.name}] Published MQTT discovery")
    
    def _publish_discovery_entity(self, discovery_prefix: str, component: str, 
                                   pump_id: str, entity: str, config: dict):
        """Publish a single discovery entity"""
        topic = f"{discovery_prefix}/{component}/jebao_{pump_id}/{entity}/config"
        self.mqtt_client.publish(topic, json.dumps(config), retain=True)
    
    def _publish_state(self, pump: JebaoPump):
        """Publish current state for a pump"""
        if not self.mqtt_client or not self.mqtt_client.is_connected():
            return
            
        mqtt_config = self._get_mqtt_config()
        prefix = mqtt_config['topic_prefix']
        pump_id = pump.config.id
        
        # Always publish connected status
        self.mqtt_client.publish(
            f"{prefix}/{pump_id}/connected/state",
            "ON" if pump.state.connected else "OFF",
            retain=True
        )
        
        # Don't publish other values until we've received actual state from the pump
        if not pump.state.state_initialized:
            logger.debug(f"[{pump.config.name}] Waiting for initial state from pump")
            return
        
        # Reset runtime daily
        today = date.today().isoformat()
        if pump.state.last_runtime_reset != today:
            pump.state.runtime_today = 0.0
            pump.state.last_runtime_reset = today
        
        # Calculate current runtime including active session
        runtime = pump.state.runtime_today
        if pump.state.power and pump.state.power_on_time > 0:
            runtime += (time.time() - pump.state.power_on_time) / 3600
        
        self.mqtt_client.publish(
            f"{prefix}/{pump_id}/power/state",
            "ON" if pump.state.power else "OFF",
            retain=True
        )
        self.mqtt_client.publish(
            f"{prefix}/{pump_id}/feed/state",
            "ON" if pump.state.feed else "OFF",
            retain=True
        )
        self.mqtt_client.publish(
            f"{prefix}/{pump_id}/flow/state",
            str(pump.state.flow),
            retain=True
        )
        self.mqtt_client.publish(
            f"{prefix}/{pump_id}/frequency/state",
            str(pump.state.frequency),
            retain=True
        )
        self.mqtt_client.publish(
            f"{prefix}/{pump_id}/mode/state",
            MODES.get(pump.state.mode, "Unknown"),
            retain=True
        )
        self.mqtt_client.publish(
            f"{prefix}/{pump_id}/runtime/state",
            f"{runtime:.2f}",
            retain=True
        )
    
    def _on_pump_state_change(self, pump: JebaoPump):
        """Callback when pump state changes"""
        self._publish_state(pump)
    
    async def start(self):
        """Start the bridge"""
        self._running = True
        self._loop = asyncio.get_running_loop()
        
        # Setup MQTT
        mqtt_config = self._get_mqtt_config()
        
        self.mqtt_client = mqtt.Client(
            client_id=mqtt_config['client_id'],
            callback_api_version=mqtt.CallbackAPIVersion.VERSION2
        )
        
        if mqtt_config['username']:
            self.mqtt_client.username_pw_set(
                mqtt_config['username'],
                mqtt_config['password']
            )
        
        self.mqtt_client.on_connect = self._on_mqtt_connect
        self.mqtt_client.on_message = self._on_mqtt_message
        
        # Connect to MQTT
        logger.info(f"Connecting to MQTT broker at {mqtt_config['host']}:{mqtt_config['port']}")
        self.mqtt_client.connect(mqtt_config['host'], mqtt_config['port'])
        self.mqtt_client.loop_start()
        
        # Create pump instances
        for index, pump_config in enumerate(self.config.get('pumps', [])):
            pc = PumpConfig(**pump_config)
            pump = JebaoPump(pc, self._on_pump_state_change, pump_index=index)
            self.pumps[pc.id] = pump
            logger.info(f"Configured pump: {pc.name} ({pc.mac})")
        
        # Connect to all pumps (staggered to avoid BLE contention)
        for index, pump in enumerate(self.pumps.values()):
            if index > 0:
                await asyncio.sleep(2)  # 2 second delay between initial connections
            asyncio.create_task(pump.connect())
        
        # Start periodic state publisher for better graphs
        asyncio.create_task(self._periodic_state_publisher())
        
        # Keep running
        while self._running:
            await asyncio.sleep(1)
    
    async def _periodic_state_publisher(self):
        """Publish state periodically for better historical graphs"""
        while self._running:
            await asyncio.sleep(STATE_PUBLISH_INTERVAL)
            for pump in self.pumps.values():
                if pump.state.connected:
                    self._publish_state(pump)
    
    async def stop(self):
        """Stop the bridge"""
        self._running = False
        
        # Disconnect all pumps
        for pump in self.pumps.values():
            await pump.disconnect()
        
        # Disconnect MQTT
        if self.mqtt_client:
            self.mqtt_client.loop_stop()
            self.mqtt_client.disconnect()
        
        logger.info("Bridge stopped")


async def main():
    parser = argparse.ArgumentParser(description='Jebao Pump MQTT Bridge')
    parser.add_argument(
        '--config', '-c',
        default='config.yaml',
        help='Path to configuration file'
    )
    parser.add_argument(
        '--debug', '-d',
        action='store_true',
        help='Enable debug logging'
    )
    args = parser.parse_args()
    
    if args.debug:
        logging.getLogger().setLevel(logging.DEBUG)
    
    # Check config file exists
    if not Path(args.config).exists():
        logger.error(f"Config file not found: {args.config}")
        logger.info("Creating example config file...")
        example_config = """# Jebao MQTT Bridge Configuration

mqtt:
  host: localhost          # MQTT broker host
  port: 1883               # MQTT broker port
  username: null           # Optional: MQTT username
  password: null           # Optional: MQTT password
  discovery_prefix: homeassistant  # HA discovery prefix
  topic_prefix: jebao      # Topic prefix for pump data

pumps:
  - name: "Wavemaker 1"    # Friendly name
    mac: "XX:XX:XX:XX:XX:XX"  # BLE MAC address
    # Optional overrides:
    # flow_min: 30
    # flow_max: 100
    # frequency_min: 5
    # frequency_max: 20
    
  # Add more pumps:
  # - name: "Wavemaker 2"
  #   mac: "YY:YY:YY:YY:YY:YY"
"""
        with open(args.config, 'w') as f:
            f.write(example_config)
        logger.info(f"Example config written to {args.config}")
        logger.info("Please edit the config file and restart")
        sys.exit(1)
    
    bridge = MQTTBridge(args.config)
    
    # Handle shutdown signals
    loop = asyncio.get_event_loop()
    for sig in (signal.SIGINT, signal.SIGTERM):
        loop.add_signal_handler(sig, lambda: asyncio.create_task(bridge.stop()))
    
    try:
        await bridge.start()
    except Exception as e:
        logger.error(f"Bridge error: {e}")
        await bridge.stop()


if __name__ == '__main__':
    asyncio.run(main())