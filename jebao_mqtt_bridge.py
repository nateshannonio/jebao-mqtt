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
import os
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

# DMP Attribute definitions (type, attr_hi, attr_lo)
ATTR_POWER = (0x00, 0x00, 0x01)
ATTR_FEED = (0x00, 0x00, 0x04)
ATTR_MODE = (0x00, 0x10, 0x02)
ATTR_FLOW = (0x00, 0x80, 0x00)
ATTR_FREQUENCY = (0x01, 0x00, 0x00)

# MDP Attribute definitions (Gizwits bitmap flags)
MDP_ATTR_POWER = 0  # SwitchON - bit 0
MDP_ATTR_FEED = 1   # Feed mode - bit 1
MDP_ATTR_SPEED = 5  # Motor_Speed - uint8 value follows flags

# Mode mappings (BLE value -> Display name) - DMP only
DMP_MODES = {
    0: "Classic Wave",   # Mode 1 on controller
    1: "Cross-flow",     # Mode 5 on controller
    2: "Sine Wave",      # Mode 2 on controller
    4: "Random",         # Mode 4 on controller
    6: "Constant",       # Mode 3 on controller
}
DMP_MODE_VALUES = {v: k for k, v in DMP_MODES.items()}

# MDP doesn't have modes - just speed control
# Maintain compatibility
MODES = DMP_MODES
MODE_VALUES = DMP_MODE_VALUES

# Pump type enum
PUMP_TYPE_DMP = "DMP"
PUMP_TYPE_MDP = "MDP"

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
    # Feed mode tracking (MDP)
    feed_end_time: float = 0.0  # Timestamp when feed mode should end
    pre_feed_flow: int = 50  # Speed before feed mode started
    last_runtime_reset: str = ""  # Date of last reset (YYYY-MM-DD)
    # Track if we've received actual state from pump
    state_initialized: bool = False
    

@dataclass 
class PumpConfig:
    """Configuration for a single pump"""
    name: str
    mac: str
    pump_type: str = PUMP_TYPE_DMP  # DMP or MDP
    id: str = ""
    flow_min: int = 30
    flow_max: int = 100
    frequency_min: int = 5
    frequency_max: int = 20
    model: str = ""  # e.g., "DMP-65", "MDP-5000"
    control_mode: str = ""  # "read_only" or "full" (default depends on pump_type)
    poll_interval: int = 60  # Status poll interval in seconds

    def __post_init__(self):
        if not self.id:
            # Generate ID from name
            self.id = self.name.lower().replace(" ", "_").replace("-", "_")

        # Set default model if not specified
        if not self.model:
            if self.pump_type == PUMP_TYPE_MDP:
                self.model = "MDP-5000"
            else:
                self.model = "DMP-65"

        # Set default control_mode based on pump type
        if not self.control_mode:
            if self.pump_type == PUMP_TYPE_MDP:
                self.control_mode = "read_only"  # MDP write protocol is still a TODO
            else:
                self.control_mode = "full"

        # Adjust defaults for MDP pumps
        if self.pump_type == PUMP_TYPE_MDP:
            # MDP pumps have different speed ranges
            if self.flow_min == 30:  # Default wasn't overridden
                self.flow_min = 30  # MDP speed range 30-100
            # MDP doesn't have frequency control
            self.frequency_min = 0
            self.frequency_max = 0


class JebaoPump:
    """Handles BLE communication with a single Jebao pump"""

    # Shared lock across all pump instances - only one BLE connection attempt at a time
    _ble_adapter_lock: Optional[asyncio.Lock] = None

    @classmethod
    def get_ble_lock(cls) -> asyncio.Lock:
        if cls._ble_adapter_lock is None:
            cls._ble_adapter_lock = asyncio.Lock()
        return cls._ble_adapter_lock

    # MDP status response layout (from APK product config schema)
    MDP_P0_START = 12        # P0 starts at byte 12 of reassembled packet
    MDP_DEVDATA_START = 25   # Device data starts at P0[25] (after product key prefix)
    # Device data byte offsets (after action byte):
    #   [0] action, [1] bools, [2] Motor_Speed, [3] FeedTime, [4] AutoGears, [5] AutoFeedTime
    # Bools byte bits: 0=SwitchON, 1=Mode, 2=FeedSwitch, 3=TimerON, 4-5=AutoMode

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
        self._poll_task = None  # MDP status polling task
        # MDP packet reassembly (BLE notifications are fragmented at 20-byte MTU)
        self._reassemble_buffer = bytearray()
        self._reassemble_expected = 0
        
    def _make_packet(self, cmd: int, payload: bytes = b'') -> bytes:
        """Build a Gizwits protocol packet"""
        length = 3 + len(payload)
        return bytes([0x00, 0x00, 0x00, 0x03, length, 0x00]) + \
               cmd.to_bytes(2, 'big') + payload
    
    def _make_write_p0(self, attr: tuple, value: int) -> bytes:
        """Build P0 data for writing an attribute (DMP format)"""
        p0 = bytearray(11)
        p0[0] = 0x11  # Write action
        p0[7] = attr[0]  # Type
        p0[8] = attr[1]  # Attr hi
        p0[9] = attr[2]  # Attr lo
        p0[10] = value
        return bytes(p0)
    
    def _make_write_p0_mdp(self, attrs: dict) -> bytes:
        """Build P0 data for writing attributes (MDP Gizwits format)"""
        action = 0x01  # Write action
        
        # Use the simple, stable format discovered through testing
        # Format 1-4 from test-mdp-formats.py were successful
        
        # Build flag byte from attributes
        flag_byte = 0x00
        
        if 'power' in attrs and attrs['power']:
            flag_byte |= (1 << MDP_ATTR_POWER)  # Set power bit
            
        if 'feed' in attrs and attrs['feed']:
            flag_byte |= (1 << MDP_ATTR_FEED)   # Set feed mode bit
        
        # Handle different command types
        if 'feed' in attrs:
            # Feed mode command - simple flag-based
            if attrs['feed']:
                # Enable feed mode
                payload = bytes([action, flag_byte])
            else:
                # Disable feed mode - clear feed bit but preserve power
                power_bit = (1 << MDP_ATTR_POWER) if self.state.power else 0
                payload = bytes([action, power_bit])
        elif 'power' in attrs and 'speed' not in attrs:
            # Power-only command - use simple format
            payload = bytes([action, flag_byte])
        elif 'speed' in attrs:
            # Speed command - use format 1 from tests (most reliable)
            # action + flag + speed_value
            if 'power' not in attrs:
                # Keep current power state when changing speed
                flag_byte = (1 << MDP_ATTR_POWER) if self.state.power else 0
            payload = bytes([action, flag_byte, attrs['speed']])
        else:
            # Fallback - minimal command
            payload = bytes([action, flag_byte])
        
        return payload
    
    def _reassemble_feed(self, data: bytes) -> list:
        """Feed a BLE notification into the reassembly buffer.
        Returns list of completed Gizwits packets (may be empty)."""
        completed = []
        if not self._reassemble_buffer:
            if len(data) >= 5 and data[:4] == bytes([0x00, 0x00, 0x00, 0x03]):
                self._reassemble_expected = 5 + data[4]
                self._reassemble_buffer.extend(data)
            else:
                return completed
        else:
            self._reassemble_buffer.extend(data)

        if len(self._reassemble_buffer) >= self._reassemble_expected > 0:
            packet = bytes(self._reassemble_buffer[:self._reassemble_expected])
            completed.append(packet)
            remainder = bytes(self._reassemble_buffer[self._reassemble_expected:])
            self._reassemble_buffer = bytearray()
            self._reassemble_expected = 0
            if remainder:
                completed.extend(self._reassemble_feed(remainder))
        return completed

    def _notification_handler(self, sender, data: bytes):
        """Handle incoming BLE notifications"""
        if self.config.pump_type == PUMP_TYPE_MDP:
            # MDP responses can be >20 bytes and arrive fragmented
            packets = self._reassemble_feed(data)
            for packet in packets:
                self._handle_mdp_packet(packet)
            return

        # DMP: packets fit in a single notification
        if len(data) < 8:
            return
        self._handle_packet(data)

    def _handle_packet(self, data: bytes):
        """Handle a complete Gizwits packet (DMP path)"""
        cmd = int.from_bytes(data[6:8], 'big')

        if cmd == 0x0007 and len(data) > 8:
            self.passcode = data[8:]
            logger.debug(f"[{self.config.name}] Received passcode")
            asyncio.create_task(self._send_login())

        elif cmd == 0x0009:
            if len(data) > 8 and data[8] == 0x00:
                logger.info(f"[{self.config.name}] Login successful")
                self.authenticated = True
                self.state.connected = True
                self.state_callback(self)
                # Start DMP status polling
                if self._poll_task is None or self._poll_task.done():
                    self._poll_task = asyncio.create_task(self._dmp_poll_loop())
            else:
                logger.warning(f"[{self.config.name}] Login failed")

        elif cmd == 0x0093:
            if len(data) >= 12:
                p0 = data[12:]
                if len(p0) >= 11:
                    self._update_state_dmp(p0[7], p0[8], p0[9], p0[10])

        elif cmd == 0x0094:
            # Check if this is a read response (action 0x13) with state data
            if len(data) >= 23:
                p0 = data[12:]
                if len(p0) >= 11 and p0[0] == 0x13:
                    self._update_state_dmp(p0[7], p0[8], p0[9], p0[10])
                    return
            logger.debug(f"[{self.config.name}] Command acknowledged")

    def _handle_mdp_packet(self, data: bytes):
        """Handle a complete reassembled Gizwits packet (MDP path)"""
        if len(data) < 8:
            return
        cmd = int.from_bytes(data[6:8], 'big')
        logger.debug(f"[{self.config.name}] MDP cmd=0x{cmd:04x} ({len(data)}B)")

        if cmd == 0x0007 and len(data) > 8:
            self.passcode = data[8:]
            logger.debug(f"[{self.config.name}] Received passcode")
            asyncio.create_task(self._send_login())

        elif cmd == 0x0009:
            if len(data) > 8 and data[8] == 0x00:
                logger.info(f"[{self.config.name}] Login successful")
                self.authenticated = True
                self.state.connected = True
                self.state_callback(self)
                # Start MDP status polling
                if self._poll_task is None or self._poll_task.done():
                    self._poll_task = asyncio.create_task(self._mdp_poll_loop())
            else:
                logger.warning(f"[{self.config.name}] Login failed")

        elif cmd == 0x0100:
            # Full status response (211 bytes) — parse device data
            self._parse_mdp_status(data)

        elif cmd == 0x0062:
            logger.debug(f"[{self.config.name}] MDP device ready notification")

        elif cmd == 0x0094:
            logger.debug(f"[{self.config.name}] Command acknowledged")
    
    def _update_state_dmp(self, type_byte: int, attr_hi: int, attr_lo: int, value: int):
        """Update state from received attribute (DMP format)"""
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
    
    def _parse_mdp_status(self, data: bytes):
        """Parse MDP status from a reassembled 0x0100 response packet.

        Status response structure (211 bytes total):
          data[0:12]  - Gizwits header (4B header + 1B length + 1B flags + 2B cmd + 4B sn)
          data[12:37] - P0 prefix: [dynamic, 0x00, 0x16, <22-byte product key>]
          data[37:]   - Device data: [action, bools, speed, feedtime, autogears, ...]

        Device data bools byte (from APK product config schema):
          bit 0: SwitchON, bit 1: Mode, bit 2: FeedSwitch, bit 3: TimerON, bits 4-5: AutoMode
        """
        dd_offset = self.MDP_P0_START + self.MDP_DEVDATA_START  # 12 + 25 = 37
        if len(data) < dd_offset + 6:
            logger.debug(f"[{self.config.name}] MDP status too short: {len(data)}B")
            return

        devdata = data[dd_offset:]
        bools_byte = devdata[1]
        speed = devdata[2]
        feedtime = devdata[3]

        power_on = bool(bools_byte & 0x01)     # bit 0: SwitchON
        feed_mode = bool(bools_byte & 0x04)    # bit 2: FeedSwitch
        auto_mode = (bools_byte >> 4) & 0x03   # bits 4-5: AutoMode

        changed = False

        # Update power
        if self.state.power != power_on:
            now = time.time()
            if power_on:
                self.state.power_on_time = now
            elif self.state.power_on_time > 0:
                self.state.runtime_today += (now - self.state.power_on_time) / 3600
                self.state.power_on_time = 0
            self.state.power = power_on
            changed = True
            logger.info(f"[{self.config.name}] Power: {'ON' if power_on else 'OFF'}")

        # Update feed mode
        if self.state.feed != feed_mode:
            self.state.feed = feed_mode
            changed = True
            logger.info(f"[{self.config.name}] Feed: {'ON' if feed_mode else 'OFF'}")

        # Update speed
        if self.state.flow != speed and 0 <= speed <= 100:
            self.state.flow = speed
            changed = True
            logger.info(f"[{self.config.name}] Speed: {speed}%")

        # Update mode (AutoMode enum)
        if self.state.mode != auto_mode:
            self.state.mode = auto_mode
            changed = True
            logger.debug(f"[{self.config.name}] AutoMode: {auto_mode}")

        if changed or not self.state.state_initialized:
            self.state.state_initialized = True
            self.state_callback(self)
            logger.debug(f"[{self.config.name}] Status: power={power_on} speed={speed}% feed={feed_mode}")

    async def _mdp_poll_loop(self):
        """Periodically poll MDP pump status via BLE"""
        interval = self.config.poll_interval
        logger.info(f"[{self.config.name}] Starting MDP status polling (every {interval}s)")
        while self._running and self.authenticated:
            try:
                await self._mdp_request_status()
            except Exception as e:
                logger.debug(f"[{self.config.name}] Poll error: {e}")
            await asyncio.sleep(interval)
        logger.debug(f"[{self.config.name}] MDP poll loop ended")

    async def _mdp_request_status(self):
        """Send a status read request to MDP pump (cmd 0x93, action 0x02)"""
        if not self.authenticated or not self.client or not self.client.is_connected:
            return
        payload = self.command_sn.to_bytes(4, 'big') + bytes([0x02, 0x00])
        packet = self._make_packet(CMD_CONTROL, payload)
        self.command_sn += 1
        try:
            await self.client.write_gatt_char(CHAR_UUID, packet, response=False)
        except BleakError as e:
            logger.debug(f"[{self.config.name}] Status request failed: {e}")
    
    async def _dmp_poll_loop(self):
        """Periodically poll DMP pump status via BLE"""
        interval = self.config.poll_interval
        logger.info(f"[{self.config.name}] Starting DMP status polling (every {interval}s)")
        while self._running and self.authenticated:
            try:
                await self._dmp_request_status()
            except Exception as e:
                logger.debug(f"[{self.config.name}] DMP poll error: {e}")
            await asyncio.sleep(interval)
        logger.debug(f"[{self.config.name}] DMP poll loop ended")

    async def _dmp_request_status(self):
        """Send status read requests for each DMP attribute"""
        if not self.authenticated or not self.client or not self.client.is_connected:
            return
        # Request each attribute individually using read action (0x12)
        for attr in [ATTR_POWER, ATTR_FEED, ATTR_MODE, ATTR_FLOW, ATTR_FREQUENCY]:
            p0 = bytearray(11)
            p0[0] = 0x12  # Read action
            p0[7] = attr[0]  # type
            p0[8] = attr[1]  # attr_hi
            p0[9] = attr[2]  # attr_lo
            payload = self.command_sn.to_bytes(4, 'big') + bytes(p0)
            packet = self._make_packet(CMD_CONTROL, payload)
            self.command_sn += 1
            try:
                await self.client.write_gatt_char(CHAR_UUID, packet, response=False)
                await asyncio.sleep(1)  # Delay between requests to avoid overwhelming the pump
            except BleakError as e:
                logger.debug(f"[{self.config.name}] DMP status request failed: {e}")
                break

    async def _send_login(self):
        """Send login packet with passcode"""
        if self.client and self.client.is_connected:
            packet = self._make_packet(CMD_LOGIN, self.passcode)
            await self.client.write_gatt_char(CHAR_UUID, packet, response=False)
    
    async def _send_command(self, attr: tuple, value: int):
        """Send a control command (DMP format)"""
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
    
    async def _send_command_mdp(self, attrs: dict):
        """Send a control command (MDP Gizwits format)"""
        if not self.authenticated or not self.client or not self.client.is_connected:
            logger.warning(f"[{self.config.name}] Cannot send - not connected")
            return False
            
        p0 = self._make_write_p0_mdp(attrs)
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
        """Connect to the pump (serialized across all pumps via shared BLE lock)"""
        async with JebaoPump.get_ble_lock():
            if self.client and self.client.is_connected:
                return True
            
            # Store event loop reference for callbacks
            self._loop = asyncio.get_running_loop()
                
            try:
                logger.info(f"[{self.config.name}] Connecting to {self.config.mac}...")

                # Clean up any stale BlueZ state from previous connection
                if self.client:
                    try:
                        await self.client.disconnect()
                    except Exception:
                        pass
                    self.client = None

                # Force-disconnect via a throwaway client to clear InProgress state
                try:
                    stale = BleakClient(self.config.mac)
                    await stale.disconnect()
                    await asyncio.sleep(3)  # Give BlueZ time to fully release the device
                except Exception:
                    pass

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
            except EOFError:
                logger.critical(f"[{self.config.name}] D-Bus connection lost (BlueZ crashed?) - exiting for systemd restart")
                os._exit(1)
            except Exception as e:
                if "Bad file descriptor" in str(e) or "EOFError" in str(type(e).__mro__):
                    logger.critical(f"[{self.config.name}] D-Bus connection broken - exiting for systemd restart")
                    os._exit(1)
                logger.error(f"[{self.config.name}] Unexpected error during connect: {type(e).__name__}: {e}")
                await self._cleanup_connection()
                return False
    
    async def _cleanup_connection(self):
        """Clean up connection state and give BlueZ time to release resources"""
        self.authenticated = False
        self.state.connected = False
        if self.client:
            try:
                await self.client.disconnect()
            except Exception:
                pass
            self.client = None
        await asyncio.sleep(2)  # Give BlueZ time to clean up
    
    def _on_disconnect(self, client):
        """Handle disconnection - called from BLE callback"""
        # Debounce: ignore if we already know we're disconnected
        if not self.authenticated and not self.state.connected:
            return
        logger.warning(f"[{self.config.name}] Disconnected")
        self.authenticated = False
        self.state.connected = False
        # Reset reassembly buffer
        self._reassemble_buffer = bytearray()
        self._reassemble_expected = 0
        
        # Notify state change
        try:
            self.state_callback(self)
        except Exception as e:
            logger.error(f"[{self.config.name}] Error in state callback: {e}")
        
        # Schedule reconnect in the event loop
        if self._loop is not None and self._running:
            try:
                # Only schedule if no reconnect task is active
                # The reconnect loop checks self.authenticated, so if we
                # reconnected briefly and disconnected again, the still-running
                # loop will see authenticated=False and continue retrying
                task_running = (self._reconnect_task is not None
                               and not self._reconnect_task.done())
                if not task_running:
                    self._reconnect_task = asyncio.run_coroutine_threadsafe(
                        self._reconnect_loop(), self._loop
                    )
            except Exception as e:
                logger.error(f"[{self.config.name}] Failed to schedule reconnect: {e}")
    
    async def _reconnect_loop(self):
        """Attempt to reconnect with backoff"""
        delay = 10
        max_delay = 300  # Max 5 minutes between attempts
        max_attempts = 0  # 0 = infinite
        attempts = 0

        # Stagger reconnection attempts for multiple pumps to avoid BLE adapter contention
        stagger_delay = self._pump_index * 8 + random.uniform(2, 5)
        logger.info(f"[{self.config.name}] Staggering reconnect by {stagger_delay:.0f}s")
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
                    # Wait briefly and verify connection held before declaring success
                    await asyncio.sleep(5)
                    if self.authenticated:
                        logger.info(f"[{self.config.name}] Reconnection successful")
                        break
                    else:
                        logger.warning(f"[{self.config.name}] Connection lost shortly after reconnect, retrying...")
                        delay = 5  # Reset backoff on brief connections
                        continue
            except Exception as e:
                logger.error(f"[{self.config.name}] Reconnection attempt failed: {e}")

            # Exponential backoff with jitter to prevent synchronized retries
            jitter = random.uniform(0, delay * 0.1)  # Up to 10% jitter
            delay = min(delay * 2 + jitter, max_delay)

        logger.debug(f"[{self.config.name}] Reconnect loop ended")
    
    async def disconnect(self):
        """Disconnect from the pump"""
        self._running = False

        if self._poll_task and not self._poll_task.done():
            self._poll_task.cancel()

        if self._reconnect_task:
            try:
                if hasattr(self._reconnect_task, 'cancel'):
                    self._reconnect_task.cancel()
            except Exception:
                pass

        await self._cleanup_connection()
    
    # Control methods
    def _is_read_only(self) -> bool:
        return self.config.control_mode == "read_only"

    async def set_power(self, on: bool):
        logger.info(f"[{self.config.name}] Setting power: {'ON' if on else 'OFF'}")
        if self.config.pump_type == PUMP_TYPE_MDP:
            if self._is_read_only():
                logger.warning(f"[{self.config.name}] Control not available (read_only mode)")
                return False
            # TODO: MDP write protocol not yet implemented
            return await self._send_command_mdp({'power': on})
        else:
            return await self._send_command(ATTR_POWER, 1 if on else 0)

    async def set_feed(self, on: bool):
        logger.info(f"[{self.config.name}] Setting feed: {'ON' if on else 'OFF'}")
        if self.config.pump_type == PUMP_TYPE_MDP:
            if self._is_read_only():
                logger.warning(f"[{self.config.name}] Control not available (read_only mode)")
                return False
            if on:
                return await self._start_feed_mode_mdp()
            else:
                return await self._end_feed_mode_mdp()
        else:
            if on:
                return await self._start_feed_mode_dmp()
            else:
                return await self._end_feed_mode_dmp()

    async def _start_feed_mode_dmp(self) -> bool:
        """Start DMP feed mode - power off pump with auto-resume timer"""
        feed_duration = self.config.feed_time if hasattr(self.config, 'feed_time') else 600
        logger.info(f"[{self.config.name}] Starting feed mode ({feed_duration // 60} min timer)")
        await self._send_command(ATTR_FEED, 1)
        success = await self._send_command(ATTR_POWER, 0)
        if success:
            self.state.feed = True
            self.state.feed_end_time = time.time() + feed_duration
            asyncio.create_task(self._feed_timer_dmp())
        return success

    async def _end_feed_mode_dmp(self) -> bool:
        """End DMP feed mode - resume pump"""
        logger.info(f"[{self.config.name}] Ending feed mode")
        self.state.feed_end_time = 0.0
        await self._send_command(ATTR_FEED, 0)
        success = await self._send_command(ATTR_POWER, 1)
        if success:
            self.state.feed = False
        return success

    async def _feed_timer_dmp(self):
        """Background timer for DMP feed mode auto-resume"""
        try:
            while self.state.feed_end_time > time.time() and self.state.feed:
                remaining = int(self.state.feed_end_time - time.time())
                if remaining > 0 and remaining % 60 == 0:
                    logger.info(f"[{self.config.name}] Feed mode: {remaining // 60} min remaining")
                await asyncio.sleep(1.0)
            if self.state.feed:
                logger.info(f"[{self.config.name}] Feed timer expired, resuming pump")
                await self._end_feed_mode_dmp()
        except Exception as e:
            logger.error(f"[{self.config.name}] Feed timer error: {e}")

    async def set_flow(self, percent: int):
        percent = max(self.config.flow_min, min(self.config.flow_max, percent))
        if self.config.pump_type == PUMP_TYPE_MDP:
            if self._is_read_only():
                logger.warning(f"[{self.config.name}] Control not available (read_only mode)")
                return False
            # TODO: MDP write protocol not yet implemented
            logger.info(f"[{self.config.name}] Setting speed: {percent}%")
            return await self._send_command_mdp({'speed': percent})
        else:
            logger.info(f"[{self.config.name}] Setting flow: {percent}%")
            return await self._send_command(ATTR_FLOW, percent)

    async def set_frequency(self, seconds: int):
        if self.config.pump_type == PUMP_TYPE_MDP:
            logger.warning(f"[{self.config.name}] MDP pumps don't support frequency control")
            return False
        else:
            seconds = max(self.config.frequency_min, min(self.config.frequency_max, seconds))
            logger.info(f"[{self.config.name}] Setting frequency: {seconds}s")
            return await self._send_command(ATTR_FREQUENCY, seconds)

    async def set_mode(self, mode: int):
        if self.config.pump_type == PUMP_TYPE_MDP:
            logger.warning(f"[{self.config.name}] MDP pumps don't support mode control")
            return False
        else:
            if mode in MODES:
                logger.info(f"[{self.config.name}] Setting mode: {MODES[mode]}")
                return await self._send_command(ATTR_MODE, mode)
            return False

    async def set_mode_by_name(self, mode_name: str):
        if self.config.pump_type == PUMP_TYPE_MDP:
            logger.warning(f"[{self.config.name}] MDP pumps don't support mode control")
            return False
        else:
            if mode_name in MODE_VALUES:
                return await self.set_mode(MODE_VALUES[mode_name])
            return False

    async def _start_feed_mode_mdp(self) -> bool:
        """Start MDP feed mode - stops pump for 2 minutes"""
        logger.info(f"[{self.config.name}] Starting feed mode (2 min timer)")
        
        # Store current speed to restore later
        self.state.pre_feed_flow = self.state.flow
        
        # Set feed end time (2 minutes from now)
        self.state.feed_end_time = time.time() + 120  # 2 minutes
        
        # Send feed mode command (our current command that stops the pump)
        success = await self._send_command_mdp({'feed': True})
        
        if success:
            # Update state immediately
            self.state.feed = True
            self.state.power = False  # Pump stops during feed mode
            
            # Schedule automatic resume
            asyncio.create_task(self._feed_timer_mdp())
            
        return success
    
    async def _end_feed_mode_mdp(self) -> bool:
        """End MDP feed mode early - resume normal operation"""
        logger.info(f"[{self.config.name}] Ending feed mode early")
        
        # Clear feed timer
        self.state.feed_end_time = 0.0
        
        # Resume with previous speed
        success = await self._send_command_mdp({
            'power': True, 
            'speed': self.state.pre_feed_flow
        })
        
        if success:
            self.state.feed = False
            self.state.power = True
            self.state.flow = self.state.pre_feed_flow
            
        return success
    
    async def _feed_timer_mdp(self):
        """Background timer for MDP feed mode"""
        try:
            # Wait until feed time expires
            while self.state.feed_end_time > time.time() and self.state.feed:
                await asyncio.sleep(1.0)
            
            # If feed mode is still active, end it automatically
            if self.state.feed and self.state.feed_end_time > 0:
                logger.info(f"[{self.config.name}] Feed timer expired, resuming pump")
                await self._end_feed_mode_mdp()
                
        except Exception as e:
            logger.error(f"[{self.config.name}] Feed timer error: {e}")


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

        pump = self.pumps.get(pump_id)
        if not pump:
            return

        # Read-only pumps don't need command subscriptions
        if pump.config.control_mode == "read_only":
            logger.debug(f"[{pump.config.name}] Read-only mode, skipping command subscriptions")
            return

        topics = ['power', 'flow']

        if pump.config.pump_type == PUMP_TYPE_DMP:
            topics.extend(['feed', 'frequency', 'mode'])
        elif pump.config.pump_type == PUMP_TYPE_MDP:
            topics.append('feed')

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
            "model": pump.config.model,
        }
        
        read_only = pump.config.control_mode == "read_only"

        if read_only:
            # Read-only: publish power and feed as binary_sensor (no control)
            self._publish_discovery_entity(
                discovery_prefix, "binary_sensor", pump_id, "power",
                {
                    "name": "Power",
                    "state_topic": f"{topic_prefix}/{pump_id}/power/state",
                    "payload_on": "ON",
                    "payload_off": "OFF",
                    "icon": "mdi:power",
                    "device": device_info,
                    "unique_id": f"jebao_{pump_id}_power",
                }
            )
            self._publish_discovery_entity(
                discovery_prefix, "binary_sensor", pump_id, "feed",
                {
                    "name": "Feed Mode",
                    "state_topic": f"{topic_prefix}/{pump_id}/feed/state",
                    "payload_on": "ON",
                    "payload_off": "OFF",
                    "icon": "mdi:fish",
                    "device": device_info,
                    "unique_id": f"jebao_{pump_id}_feed",
                }
            )
        else:
            # Full control: publish power and feed as switches
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
            if pump.config.pump_type in [PUMP_TYPE_DMP, PUMP_TYPE_MDP]:
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

        # Flow/Speed - sensor for read_only, number for full control
        flow_name = "Speed" if pump.config.pump_type == PUMP_TYPE_MDP else "Flow"
        flow_icon = "mdi:speedometer" if pump.config.pump_type == PUMP_TYPE_MDP else "mdi:waves"

        if read_only:
            # Read-only: just a sensor, no command topic
            pass  # The flow_sensor below handles this
        else:
            self._publish_discovery_entity(
                discovery_prefix, "number", pump_id, "flow",
                {
                    "name": flow_name,
                    "command_topic": f"{topic_prefix}/{pump_id}/flow/set",
                    "state_topic": f"{topic_prefix}/{pump_id}/flow/state",
                    "min": pump.config.flow_min,
                    "max": pump.config.flow_max,
                    "step": 1,
                    "unit_of_measurement": "%",
                    "icon": flow_icon,
                    "device": device_info,
                    "unique_id": f"jebao_{pump_id}_flow",
                }
            )
        
        # Flow/Speed sensor (for statistics/graphs)
        sensor_name = "Speed Level" if pump.config.pump_type == PUMP_TYPE_MDP else "Flow Level"
        
        self._publish_discovery_entity(
            discovery_prefix, "sensor", pump_id, "flow_sensor",
            {
                "name": sensor_name,
                "state_topic": f"{topic_prefix}/{pump_id}/flow/state",
                "unit_of_measurement": "%",
                "icon": flow_icon,
                "device": device_info,
                "unique_id": f"jebao_{pump_id}_flow_sensor",
                "state_class": "measurement",  # Enables long-term statistics
            }
        )
        
        # Frequency number and sensor (DMP only)
        if pump.config.pump_type == PUMP_TYPE_DMP:
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
        
        # Mode select (DMP only)
        if pump.config.pump_type == PUMP_TYPE_DMP:
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
        
        # Power state (all pumps)
        self.mqtt_client.publish(
            f"{prefix}/{pump_id}/power/state",
            "ON" if pump.state.power else "OFF",
            retain=True
        )
        
        # Feed state (both DMP and MDP)
        if pump.config.pump_type in [PUMP_TYPE_DMP, PUMP_TYPE_MDP]:
            self.mqtt_client.publish(
                f"{prefix}/{pump_id}/feed/state",
                "ON" if pump.state.feed else "OFF",
                retain=True
            )
        
        # Flow/Speed state (all pumps)
        self.mqtt_client.publish(
            f"{prefix}/{pump_id}/flow/state",
            str(pump.state.flow),
            retain=True
        )
        
        # Frequency state (DMP only)
        if pump.config.pump_type == PUMP_TYPE_DMP:
            self.mqtt_client.publish(
                f"{prefix}/{pump_id}/frequency/state",
                str(pump.state.frequency),
                retain=True
            )
        
        # Mode state (DMP only)
        if pump.config.pump_type == PUMP_TYPE_DMP:
            self.mqtt_client.publish(
                f"{prefix}/{pump_id}/mode/state",
                MODES.get(pump.state.mode, "Unknown"),
                retain=True
            )
        
        # Runtime state (all pumps)
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
        
        # Connect to all pumps sequentially to avoid BLE adapter contention
        for index, pump in enumerate(self.pumps.values()):
            if index > 0:
                await asyncio.sleep(8)
            connected = False
            try:
                connected = await asyncio.wait_for(pump.connect(), timeout=60)
            except (asyncio.TimeoutError, Exception) as e:
                msg = "timed out" if isinstance(e, asyncio.TimeoutError) else str(e)
                logger.warning(f"[{pump.config.name}] Initial connection failed ({msg})")
            if not connected:
                logger.info(f"[{pump.config.name}] Scheduling reconnect")
                await pump._cleanup_connection()
                pump._loop = asyncio.get_running_loop()
                pump._reconnect_task = asyncio.run_coroutine_threadsafe(
                    pump._reconnect_loop(), pump._loop
                )
        
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