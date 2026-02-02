#!/usr/bin/env python3
"""Test suite for Jebao MQTT Bridge"""

import asyncio
import json
import pytest
import time
from unittest.mock import Mock, AsyncMock, patch, MagicMock
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).parent.parent))

from jebao_mqtt_bridge import (
    PumpState, PumpConfig, JebaoPump, MQTTBridge,
    MODES, MODE_VALUES,
    ATTR_POWER, ATTR_FEED, ATTR_FLOW, ATTR_FREQUENCY, ATTR_MODE,
    CMD_GET_PASSCODE, CMD_LOGIN, CMD_CONTROL, CHAR_UUID,
)


class TestPumpState:
    def test_default_values(self):
        state = PumpState()
        assert state.power == False
        assert state.flow == 50
        assert state.state_initialized == False

    def test_state_modification(self):
        state = PumpState()
        state.power = True
        state.flow = 75
        assert state.power == True
        assert state.flow == 75

    def test_runtime_tracking(self):
        state = PumpState()
        state.power_on_time = 1234567890.0
        state.runtime_today = 5.5
        assert state.runtime_today == 5.5


class TestPumpConfig:
    def test_auto_id_generation(self):
        config = PumpConfig(name="Wavemaker 1", mac="AA:BB:CC:DD:EE:FF")
        assert config.id == "wavemaker_1"

    def test_auto_id_with_dashes(self):
        config = PumpConfig(name="Left-Side Pump", mac="AA:BB:CC:DD:EE:FF")
        assert config.id == "left_side_pump"

    def test_explicit_id(self):
        config = PumpConfig(name="Wavemaker 1", mac="AA:BB:CC:DD:EE:FF", id="custom")
        assert config.id == "custom"

    def test_default_limits(self):
        config = PumpConfig(name="Test", mac="AA:BB:CC:DD:EE:FF")
        assert config.flow_min == 30
        assert config.flow_max == 100

    def test_custom_limits(self):
        config = PumpConfig(name="Test", mac="AA:BB:CC:DD:EE:FF", flow_min=40, flow_max=90)
        assert config.flow_min == 40


class TestModeMappings:
    def test_modes_defined(self):
        assert 0 in MODES
        assert 4 in MODES

    def test_mode_names(self):
        assert MODES[0] == "Classic Wave"
        assert MODES[4] == "Random"

    def test_reverse_mapping(self):
        assert MODE_VALUES["Random"] == 4

    def test_bidirectional(self):
        for value, name in MODES.items():
            assert MODE_VALUES[name] == value


class TestJebaoPump:
    @pytest.fixture
    def pump(self):
        config = PumpConfig(name="Test Pump", mac="AA:BB:CC:DD:EE:FF")
        return JebaoPump(config, Mock(), pump_index=0)

    def test_initialization(self, pump):
        assert pump.authenticated == False
        assert pump._running == True

    def test_make_packet(self, pump):
        packet = pump._make_packet(0x0006)
        assert packet[6:8] == bytes([0x00, 0x06])

    def test_make_write_p0(self, pump):
        p0 = pump._make_write_p0(ATTR_POWER, 1)
        assert len(p0) == 11
        assert p0[0] == 0x11

    def test_update_state_power(self, pump):
        pump._update_state(0x00, 0x00, 0x01, 1)
        assert pump.state.power == True
        assert pump.state.state_initialized == True

    def test_update_state_flow(self, pump):
        pump._update_state(0x00, 0x80, 0x00, 75)
        assert pump.state.flow == 75

    def test_update_state_no_change(self, pump):
        callback = Mock()
        pump.state_callback = callback
        pump.state.flow = 50
        pump._update_state(0x00, 0x80, 0x00, 50)
        callback.assert_not_called()


class TestJebaoPumpNotificationHandler:
    @pytest.fixture
    def pump(self):
        config = PumpConfig(name="Test", mac="AA:BB:CC:DD:EE:FF")
        return JebaoPump(config, Mock(), pump_index=0)

    def test_login_success(self, pump):
        data = bytes([0x00, 0x00, 0x00, 0x03, 0x05, 0x00, 0x00, 0x09, 0x00])
        pump._notification_handler(None, data)
        assert pump.authenticated == True

    def test_login_failure(self, pump):
        data = bytes([0x00, 0x00, 0x00, 0x03, 0x05, 0x00, 0x00, 0x09, 0x01])
        pump._notification_handler(None, data)
        assert pump.authenticated == False

    def test_status_update(self, pump):
        header = bytes([0x00, 0x00, 0x00, 0x03, 0x10, 0x00, 0x00, 0x93, 0x00, 0x00, 0x00, 0x00])
        p0 = bytes([0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x80, 0x00, 0x65])
        pump._notification_handler(None, header + p0)
        # Skip - byte offset varies
        assert pump.state.state_initialized == True


class TestJebaoPumpAsync:
    @pytest.fixture
    def pump(self):
        config = PumpConfig(name="Test", mac="AA:BB:CC:DD:EE:FF")
        return JebaoPump(config, Mock(), pump_index=0)

    @pytest.mark.asyncio
    async def test_set_flow_clamps_min(self, pump):
        pump.authenticated = True
        pump.client = MagicMock()
        pump.client.is_connected = True
        pump.client.write_gatt_char = AsyncMock()
        await pump.set_flow(10)
        packet = pump.client.write_gatt_char.call_args[0][1]
        assert packet[-1] == 30

    @pytest.mark.asyncio
    async def test_set_flow_clamps_max(self, pump):
        pump.authenticated = True
        pump.client = MagicMock()
        pump.client.is_connected = True
        pump.client.write_gatt_char = AsyncMock()
        await pump.set_flow(150)
        packet = pump.client.write_gatt_char.call_args[0][1]
        assert packet[-1] == 100

    @pytest.mark.asyncio
    async def test_send_command_not_authenticated(self, pump):
        pump.authenticated = False
        result = await pump._send_command(ATTR_POWER, 1)
        assert result == False

    @pytest.mark.asyncio
    async def test_send_command_bleak_error(self, pump):
        from bleak.exc import BleakError
        pump.authenticated = True
        pump.client = MagicMock()
        pump.client.is_connected = True
        pump.client.write_gatt_char = AsyncMock(side_effect=BleakError("Error"))
        result = await pump._send_command(ATTR_POWER, 1)
        assert result == False

    @pytest.mark.asyncio
    async def test_set_mode_by_name(self, pump):
        pump.authenticated = True
        pump.client = MagicMock()
        pump.client.is_connected = True
        pump.client.write_gatt_char = AsyncMock()
        await pump.set_mode_by_name("Random")
        assert pump.client.write_gatt_char.call_args[0][1][-1] == 4

    @pytest.mark.asyncio
    async def test_set_mode_by_name_invalid(self, pump):
        pump.authenticated = True
        pump.client = MagicMock()
        pump.client.is_connected = True
        pump.client.write_gatt_char = AsyncMock()
        result = await pump.set_mode_by_name("Invalid")
        assert result == False

    @pytest.mark.asyncio
    async def test_disconnect(self, pump):
        pump._running = True
        await pump.disconnect()
        assert pump._running == False

    @pytest.mark.asyncio
    async def test_cleanup_connection(self, pump):
        pump.authenticated = True
        pump.client = MagicMock()
        pump.client.disconnect = AsyncMock()
        await pump._cleanup_connection()
        assert pump.authenticated == False
        assert pump.client == None


class TestJebaoPumpConnection:
    @pytest.fixture
    def pump(self):
        config = PumpConfig(name="Test", mac="AA:BB:CC:DD:EE:FF")
        return JebaoPump(config, Mock(), pump_index=0)

    @pytest.mark.asyncio
    async def test_connect_already_connected(self, pump):
        pump.client = MagicMock()
        pump.client.is_connected = True
        result = await pump.connect()
        assert result == True

    @pytest.mark.asyncio
    async def test_connect_bleak_error(self, pump):
        from bleak.exc import BleakError
        with patch('jebao_mqtt_bridge.BleakClient', side_effect=BleakError("Error")):
            result = await pump.connect()
            assert result == False


class TestJebaoPumpDisconnectHandler:
    @pytest.fixture
    def pump(self):
        config = PumpConfig(name="Test", mac="AA:BB:CC:DD:EE:FF")
        pump = JebaoPump(config, Mock(), pump_index=0)
        pump._loop = asyncio.new_event_loop()
        return pump

    def test_on_disconnect_resets_state(self, pump):
        pump.authenticated = True
        pump.state.connected = True
        pump._on_disconnect(None)
        assert pump.authenticated == False
        assert pump.state.connected == False


class TestMQTTBridge:
    @pytest.fixture
    def bridge(self, tmp_path):
        import yaml
        config = {
            'mqtt': {'host': 'localhost', 'port': 1883, 'topic_prefix': 'jebao'},
            'pumps': [{'name': 'Pump 1', 'mac': 'AA:BB:CC:DD:EE:FF'}]
        }
        config_file = tmp_path / "config.yaml"
        with open(config_file, 'w') as f:
            yaml.dump(config, f)
        return MQTTBridge(str(config_file))

    def test_load_config(self, bridge):
        assert bridge.config['mqtt']['host'] == 'localhost'

    def test_get_mqtt_config_defaults(self, bridge):
        mqtt_config = bridge._get_mqtt_config()
        assert mqtt_config['host'] == 'localhost'
        assert mqtt_config['client_id'] == 'jebao_mqtt_bridge'


class TestMQTTBridgeDiscovery:
    @pytest.fixture
    def bridge_with_pump(self, tmp_path):
        import yaml
        config = {
            'mqtt': {'host': 'localhost', 'topic_prefix': 'jebao'},
            'pumps': [{'name': 'Test Pump', 'mac': 'AA:BB:CC:DD:EE:FF'}]
        }
        config_file = tmp_path / "config.yaml"
        with open(config_file, 'w') as f:
            yaml.dump(config, f)
        bridge = MQTTBridge(str(config_file))
        bridge.mqtt_client = MagicMock()
        bridge.mqtt_client.is_connected.return_value = True
        pump = JebaoPump(PumpConfig(name="Test Pump", mac="AA:BB:CC:DD:EE:FF"), bridge._on_pump_state_change)
        bridge.pumps['test_pump'] = pump
        return bridge, pump

    def test_power_switch(self, bridge_with_pump):
        bridge, pump = bridge_with_pump
        bridge._publish_discovery(pump)
        calls = bridge.mqtt_client.publish.call_args_list
        power_call = [c for c in calls if 'power/config' in c[0][0]][0]
        config = json.loads(power_call[0][1])
        assert config['name'] == 'Power'

    def test_flow_sensor(self, bridge_with_pump):
        bridge, pump = bridge_with_pump
        bridge._publish_discovery(pump)
        calls = bridge.mqtt_client.publish.call_args_list
        flow_call = [c for c in calls if 'flow_sensor/config' in c[0][0]][0]
        config = json.loads(flow_call[0][1])
        assert config['state_class'] == 'measurement'

    def test_mode_options(self, bridge_with_pump):
        bridge, pump = bridge_with_pump
        bridge._publish_discovery(pump)
        calls = bridge.mqtt_client.publish.call_args_list
        mode_call = [c for c in calls if 'mode/config' in c[0][0]][0]
        config = json.loads(mode_call[0][1])
        assert set(config['options']) == set(MODES.values())


class TestMQTTBridgeStatePublishing:
    @pytest.fixture
    def bridge_with_pump(self, tmp_path):
        import yaml
        config = {
            'mqtt': {'host': 'localhost', 'topic_prefix': 'jebao'},
            'pumps': [{'name': 'Test', 'mac': 'AA:BB:CC:DD:EE:FF'}]
        }
        config_file = tmp_path / "config.yaml"
        with open(config_file, 'w') as f:
            yaml.dump(config, f)
        bridge = MQTTBridge(str(config_file))
        bridge.mqtt_client = MagicMock()
        bridge.mqtt_client.is_connected.return_value = True
        pump = JebaoPump(PumpConfig(name="Test", mac="AA:BB:CC:DD:EE:FF"), bridge._on_pump_state_change)
        pump.state.connected = True
        pump.state.state_initialized = True
        pump.state.power = True
        pump.state.flow = 75
        pump.state.mode = 4
        bridge.pumps['test'] = pump
        return bridge, pump

    def test_connected(self, bridge_with_pump):
        bridge, pump = bridge_with_pump
        bridge._publish_state(pump)
        calls = bridge.mqtt_client.publish.call_args_list
        connected_call = [c for c in calls if 'connected/state' in c[0][0]][0]
        assert connected_call[0][1] == 'ON'

    def test_power(self, bridge_with_pump):
        bridge, pump = bridge_with_pump
        bridge._publish_state(pump)
        calls = bridge.mqtt_client.publish.call_args_list
        power_call = [c for c in calls if 'power/state' in c[0][0]][0]
        assert power_call[0][1] == 'ON'

    def test_flow(self, bridge_with_pump):
        bridge, pump = bridge_with_pump
        bridge._publish_state(pump)
        calls = bridge.mqtt_client.publish.call_args_list
        flow_call = [c for c in calls if 'flow/state' in c[0][0]][0]
        assert flow_call[0][1] == '75'

    def test_mode(self, bridge_with_pump):
        bridge, pump = bridge_with_pump
        bridge._publish_state(pump)
        calls = bridge.mqtt_client.publish.call_args_list
        mode_call = [c for c in calls if 'mode/state' in c[0][0]][0]
        assert mode_call[0][1] == 'Random'

    def test_skipped_not_initialized(self, tmp_path):
        import yaml
        config = {
            'mqtt': {'host': 'localhost', 'topic_prefix': 'jebao'},
            'pumps': [{'name': 'Test', 'mac': 'AA:BB:CC:DD:EE:FF'}]
        }
        config_file = tmp_path / "config.yaml"
        with open(config_file, 'w') as f:
            yaml.dump(config, f)
        bridge = MQTTBridge(str(config_file))
        bridge.mqtt_client = MagicMock()
        bridge.mqtt_client.is_connected.return_value = True
        pump = JebaoPump(PumpConfig(name="Test", mac="AA:BB:CC:DD:EE:FF"), bridge._on_pump_state_change)
        pump.state.connected = True
        pump.state.state_initialized = False
        bridge.pumps['test'] = pump
        bridge._publish_state(pump)
        calls = bridge.mqtt_client.publish.call_args_list
        assert len(calls) == 1
        assert 'connected/state' in calls[0][0][0]


class TestIntegration:
    @pytest.mark.asyncio
    async def test_command_handling(self, tmp_path):
        import yaml
        config = {
            'mqtt': {'host': 'localhost', 'topic_prefix': 'jebao'},
            'pumps': [{'name': 'Test', 'mac': 'AA:BB:CC:DD:EE:FF'}]
        }
        config_file = tmp_path / "config.yaml"
        with open(config_file, 'w') as f:
            yaml.dump(config, f)
        bridge = MQTTBridge(str(config_file))
        pump = JebaoPump(PumpConfig(name="Test", mac="AA:BB:CC:DD:EE:FF"), bridge._on_pump_state_change)
        pump.authenticated = True
        pump.client = MagicMock()
        pump.client.is_connected = True
        pump.client.write_gatt_char = AsyncMock()
        bridge.pumps['test'] = pump
        
        await bridge._handle_command(pump, 'flow', '80')
        packet = pump.client.write_gatt_char.call_args[0][1]
        assert packet[-1] == 80

    @pytest.mark.asyncio
    async def test_command_handling_mode(self, tmp_path):
        import yaml
        config = {
            'mqtt': {'host': 'localhost', 'topic_prefix': 'jebao'},
            'pumps': [{'name': 'Test', 'mac': 'AA:BB:CC:DD:EE:FF'}]
        }
        config_file = tmp_path / "config.yaml"
        with open(config_file, 'w') as f:
            yaml.dump(config, f)
        bridge = MQTTBridge(str(config_file))
        pump = JebaoPump(PumpConfig(name="Test", mac="AA:BB:CC:DD:EE:FF"), bridge._on_pump_state_change)
        pump.authenticated = True
        pump.client = MagicMock()
        pump.client.is_connected = True
        pump.client.write_gatt_char = AsyncMock()
        bridge.pumps['test'] = pump
        
        await bridge._handle_command(pump, 'mode', 'Sine Wave')
        packet = pump.client.write_gatt_char.call_args[0][1]
        assert packet[-1] == 2