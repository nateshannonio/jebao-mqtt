# MDP-5000 BLE Protocol Research

## Current Status
**BLE writes partially working — exact format still TBD.**

Writes DO affect the pump state, but we haven't nailed the correct byte format yet. The device responds with 183-byte packets after writes that likely reveal the correct format — next step is to decode them.

---

## What Works
- BLE connect and authenticate (Gizwits cmd 0x06/0x08)
- Read pump status (cmd 0x93, action 0x02)
- Parse speed from status response (position 27 in P0 data)
- Packet reassembly for fragmented BLE notifications (20-byte MTU)

## BLE Protocol Overview

### Connection
- Service UUID: `0000abf0-0000-1000-8000-00805f9b34fb`
- Characteristic UUID: `0000abf7-0000-1000-8000-00805f9b34fb` (notify + write-without-response)
- Only ONE characteristic on the device

### Packet Format
```
[00 00 00 03] [length] [flags=00] [cmd_hi cmd_lo] [payload...]
```
- Header: always `00 00 00 03`
- Length: variable-length encoded (single byte if <128, multi-byte otherwise)
- Flags: `0x00` for normal packets
- Cmd: 2 bytes big-endian

### Command Table
| Cmd    | Direction | Description |
|--------|-----------|-------------|
| 0x0006 | App→Dev   | Request passcode |
| 0x0007 | Dev→App   | Passcode response |
| 0x0008 | App→Dev   | Login with passcode |
| 0x0009 | Dev→App   | Login response (byte[8]=0x00 = success) |
| 0x0062 | Dev→App   | Device status after login (9 bytes) |
| 0x0090 | App→Dev   | WiFi-style control (gets 0x0091 ACK) |
| 0x0093 | App→Dev   | BLE control/status (payload: sn(4B) + P0) |
| 0x0094 | Dev→App   | ACK for 0x0093 |
| 0x0100 | Dev→App   | Full status response (211 bytes) |

### Authentication Sequence
1. Send cmd 0x0006 (empty payload) → receive passcode in cmd 0x0007
2. Send cmd 0x0008 with passcode → receive cmd 0x0009 (login OK)
3. Receive cmd 0x0062 (device ready notification)

### Status Read
- Send: cmd 0x0093, payload = `sn(4B) + [0x02, 0x00]`
- Response: cmd 0x0100, 211 bytes total

---

## Status Response Structure (cmd 0x0100, 211 bytes)

```
Bytes 0-3:   Header [00 00 00 03]
Byte 4:      Length (0xCE = 206)
Byte 5:      Flags (0x02)
Bytes 6-7:   Cmd (0x0100)
Bytes 8-11:  Command serial number (4 bytes)
Bytes 12+:   P0 data (199 bytes)
```

### P0 Data Layout (199 bytes)
```
P0[0]:       Dynamic byte (changes each read — NOT an action byte)
P0[1-2]:     Length prefix (0x00, 0x16 = 22)
P0[3-24]:    Product key: "nBdiUnCvuxLP1SQAUmy6mq" (22 bytes ASCII)
P0[25-198]:  Device data (174 bytes)
```

### Device Data Layout (P0[25:], 174 bytes)
```
Offset  Description         Example
[0]     Action byte         0x03 (status report)
[1]     Packed bools/enum   0x11 or 0x21
[2]     Motor_Speed         0x4B (75%)
[3]     FeedTime            0x0A (10)
[4]     AutoGears           0x1E (30)
[5]     AutoFeedTime        varies
[6-9]   YMDData             4 bytes
[10-13] HMSData             4 bytes
[14+]   AutoTime slots      6 bytes × 48 slots
...     Fault flags at end
```

### Bools Byte (Device Data offset 1)
```
Bit 0: SwitchON      (power on/off)
Bit 1: Mode          
Bit 2: FeedSwitch    (feed mode)
Bit 3: TimerON       
Bits 4-5: AutoMode   (2-bit enum, values 0-3)
Bits 6-7: unused
```

Example: `0x11 = 00010001` → SwitchON=ON, AutoMode=1
Example: `0x21 = 00100001` → SwitchON=ON, AutoMode=2

---

## Data Point Schema (from APK productConfig)

Decompiled from: `assets/productConfig/02039876751049deb404d1d89221ec4b.json`
Product name: 水族泵_有AP校时 (Aquarium pump with AP time sync)

| ID | Name (Chinese)    | Name (English)   | Type   | ByteOff | BitOff | Len |
|----|-------------------|------------------|--------|---------|--------|-----|
| 0  | 开机/关机          | SwitchON         | bool   | 0       | 0      | 1 bit |
| 1  | 模式              | Mode             | bool   | 0       | 1      | 1 bit |
| 2  | 喂食开关           | FeedSwitch       | bool   | 0       | 2      | 1 bit |
| 3  | 定时开关           | TimerON          | bool   | 0       | 3      | 1 bit |
| 4  | 当前定时模式        | AutoMode         | enum   | 0       | 4      | 2 bits |
| 5  | 设定电机转速        | Motor_Speed      | uint8  | 1       | 0      | 1 byte |
| 6  | 喂食时长           | FeedTime         | uint8  | 2       | 0      | 1 byte |
| 7  | 当前定时档位        | AutoGears        | uint8  | 3       | 0      | 1 byte |
| 8  | 当前定时喂食时间     | AutoFeedTime     | uint8  | 4       | 0      | 1 byte |
| 9  | 日期数据           | YMDData          | binary | 5       | 0      | 4 bytes |
| 10 | 时间数据           | HMSData          | binary | 9       | 0      | 4 bytes |
| 11-58 | 自动时间点00-47  | AutoTime00-47    | binary | 13-295  | 0      | 6 bytes each |
| 59 | 电机过流           | Fault_Overcurrent | bool  | 301     | 0      | 1 bit |
| 60 | 电机过压           | Fault_Overvoltage | bool  | 301     | 1      | 1 bit |
| 61 | 温度过高           | Fault_OverTemp   | bool   | 301     | 2      | 1 bit |
| 62 | 电机欠压           | Fault_Undervoltage | bool | 301     | 3      | 1 bit |
| 63 | 电机堵转           | Fault_Lockedrotor | bool  | 301     | 4      | 1 bit |
| 64 | 空载              | Fault_no_liveload | bool  | 301     | 5      | 1 bit |
| 65 | 串口连接故障        | Fault_UART       | bool   | 301     | 6      | 1 bit |

**Total: 66 data points, 302 bytes attr_vals**

---

## App Commands (from JS decompilation)

Decompiled from: `assets/templates/dcd5f9d3a6660349e3d8ebf6ec19c0ff/com.gizwits.jiebao.rn.shuibeng/index.js`

The app calls `sendCmd()` with JSON objects. The Gizwits SDK converts these to P0 bytes.

```javascript
// Power toggle
sendCmd({SwitchON: true})
sendCmd({SwitchON: false})

// Speed change (often combined with timer control)
sendCmd({Motor_Speed: 80, TimerON: false})

// Feed mode ON
sendCmd({FeedSwitch: true, TimerON: false, FeedTime: 1})

// Feed mode OFF (restore speed)
sendCmd({FeedSwitch: false, TimerON: false, FeedTime: 1, Motor_Speed: 75})

// Set date/time
sendCmd({YMDData: [year_hi, year_lo, month, day], HMSData: [0, hour, min, sec]})
```

---

## Write Testing Results Summary

### Confirmed Working
- **Writes DO affect the pump** (rounds 3, 6, 7 all changed state)
- BLE control is possible (user confirmed app works with WiFi disabled)

### Format Observations
| P0 Size | Result | Example |
|---------|--------|---------|
| 3 bytes | Usually DISCONNECTS | `[0x01, 0x11, 0x50]` |
| 4 bytes | Changes state (incorrectly) | `[0x01, 0x20, 0x21, 0x50]` |
| 5 bytes (with flags=0x20) | NO CHANGE (ignored) | `[0x01, 0x20, 0x11, 0x50, 0x0a]` |
| 174 bytes (full echo) | NO CHANGE (ignored) | Full devdata with action=0x01 |
| 312 bytes (9B flags + 302B vals) | NO CHANGE (36B ACK) | Proper Gizwits format |

### Key Observation: 183-byte Response
After writes, the device sends 183-byte packets with cmd 0x0000. This is exactly:
- 1 (action) + 9 (attr_flags) + 173 (attr_vals) = 183

**This may be the device echoing the correct write format.** Decoding this response is the #1 next step.

### Key Observation: 36-byte ACK
Normal ACKs are 9 bytes. After our larger writes, ACKs are 36 bytes. The extra 27 bytes may contain:
- Error codes explaining why the write was rejected
- The correct P0 format the device expects

---

## Current Implementation

Read-only MDP support is implemented in `jebao_mqtt_bridge.py`:
- BLE connect, authenticate, and poll status every `poll_interval` seconds
- Packet reassembly for fragmented BLE notifications (20-byte MTU)
- Parse full data point schema (SwitchON, Speed, FeedSwitch, AutoMode, faults)
- Publish to MQTT with HA auto-discovery (binary sensors + speed sensor, no controls)
- Config option `control_mode: read_only` (default for MDP)

## Next Steps for Write Support

1. **Try WiFi protocol** — `tests/test-mdp-wifi.py` can sniff app traffic over TCP (no single-connection limit)
2. **Android HCI log** — Enable Bluetooth HCI snoop log on phone, use app to control pump, capture exact bytes
3. **Decode 183-byte response** — The device sends 183B packets after writes that may reveal the expected format
4. When write protocol is figured out, change `control_mode` to `full` to enable controls

## Important Safety Notes
- Bad writes put pump in FEED+30%+OFF state requiring power cycle
- Use speed values 50-80% for testing (30% is minimum)
- Always include restore logic in test scripts
- Pump only allows ONE BLE connection at a time

## Test Scripts

All test scripts are in the `tests/` directory.

| Script | Purpose | Status |
|--------|---------|--------|
| `test-gizwits-write8.py` | Capture response hex dumps | Ran, decoded ACK + 183B response |
| `test-gizwits-write9.py` | Flag byte + product key tests | Ran, B1 got proper ACK |
| `test-gizwits-write10.py` | DID + Gizwits P0 format | Ran, no effect |
| `test-gizwits-write7.py` | 4+ byte write formats | Ran, no success |
| `test-gizwits-write6.py` | 1-byte flags mapping | Found Motor_Speed = bit 5 |
| `test-gizwits-write5.py` | Full Gizwits format (9B flags) | ACKed but no effect |
| `test-mdp-wifi.py` | WiFi TCP protocol test | Ready, not run |
| `read-status-only.py` | Verify status reading | Working |
| `analyze-test4-response.py` | Response data analysis | Complete |

## APK Extraction
- XAPK: `Jebao Aqua_3.3.23_APKPure.xapk`
- Extracted: `apk-extract/`
- Decompiled: `apk-decompiled/`
- Key JS: `apk-extract/assets/templates/dcd5f9d3a6660349e3d8ebf6ec19c0ff/com.gizwits.jiebao.rn.shuibeng/index.js`
- Key JSON: `apk-extract/assets/productConfig/02039876751049deb404d1d89221ec4b.json`
