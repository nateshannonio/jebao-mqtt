# MDP Pump Testing Notes

## Test Environment
- **Pump Model**: MDP-5000
- **MAC Address**: 7725528E-75A8-F1C3-71E6-CEF9A6EDA5EE
- **Name**: Jebao_WiFi-b17c
- **Current State**: Running at 75% speed
- **MQTT Broker**: 192.168.254.195:1883

## Key Discoveries

### 1. BLE Protocol Structure
- Service UUID: `0000abf0-0000-1000-8000-00805f9b34fb`
- Characteristic UUID: `0000abf7-0000-1000-8000-00805f9b34fb`
- Uses Gizwits IoT platform protocol
- Authentication successful with commands 0x06 (get passcode) and 0x08 (login)

### 2. Status Reading - WORKING ✅
- **Command**: 0x93 with action byte 0x02
- **Response**: Command 0x0100 with 328 bytes of data
- **Speed Location**: Position 27 in payload (position 39 in full packet)
- **Verified**: Changed pump from 72% to 75%, confirmed byte changed from 0x48 to 0x4B

### 3. Control Commands - NOT WORKING ❌
Tested numerous command formats, all receive ACK but don't control pump:

#### Command 0x93 variations tested:
- Simple speed value: `[speed]`
- Action + speed: `[0x01, speed]`
- Action + flags + speed: `[0x01, 0x00, speed]`
- Attribute + speed: `[0x05, speed]`
- Different action codes: `[0x00-0x04, speed]`

#### Other command codes tested:
- 0x91, 0x92, 0x95, 0x96 - All safe but no control

#### Disconnection-causing formats:
- `[0x01, 0x05, speed]` - Causes immediate disconnection
- `[0x01, 0x00, speed]` with certain command serial numbers

### 4. Single BLE Connection Limitation
- Pump only allows ONE BLE connection at a time
- Cannot simultaneously connect with script and app
- This blocks capturing actual working commands from the app
- Physical controller uses IR/RF, not BLE

### 5. Protocol Analysis from Test4 Response
Test4 (action 0x02) returns full status/config dump:
- Contains ASCII text: "nBdiUnCvuxLP1SQAUmy6mq" and "HCOBE"
- Many 0xee bytes (likely padding/uninitialized)
- Current speed confirmed at position 27
- Possible configuration data throughout

## Current Status

**Read-only monitoring is implemented and working in the MQTT bridge.**
Write control is still under investigation — see `MDP_PROTOCOL_RESEARCH.md` for the full protocol analysis.

## What Works
- ✅ BLE connection, discovery, and authentication
- ✅ Reading pump status (power, speed, feed mode, AutoMode)
- ✅ Parsing full data point schema (from APK decompilation)
- ✅ Packet reassembly for fragmented BLE responses (20-byte MTU)
- ✅ MQTT bridge with HA auto-discovery (read-only sensors)
- ✅ Periodic status polling (configurable interval)

## What Doesn't Work Yet
- ❌ Write/control commands (speed change, power on/off, feed mode)
- ❌ Exact BLE write byte format still unknown despite extensive testing

## Remaining Blockers for Write Support

1. **Unknown write protocol** - Writes are ACKed but don't affect pump state. Extensive format testing (10+ rounds) has not found the correct format.
2. **Single BLE connection** - Cannot simultaneously sniff app traffic via BLE
3. **Potential paths forward**: WiFi protocol sniffing, Android HCI log capture

## Test Scripts

All test scripts have been moved to the `tests/` directory. See `MDP_PROTOCOL_RESEARCH.md` for a table of scripts and their status.

## Summary
Read-only MDP support is fully implemented. The bridge connects via BLE, authenticates, polls status every 30 seconds, and publishes power/speed/feed state to Home Assistant via MQTT. Write control requires further reverse-engineering of the Gizwits BLE write protocol.