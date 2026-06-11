# Jebao Aqua APK reverse-engineering notes

Session notes from decompiling the Jebao Aqua Android app (`com.jebao.android`,
v3.3.23) to map the remaining BLE protocol attributes. The bridge currently
recognizes 5 attributes (Power, Mode, Flow, Frequency, Feed) plus a stub
diagnostic capture. There are at least 60 more.

## Major findings

### 1. Jebao uses the Gizwits IoT SDK

The BLE protocol isn't custom to Jebao — they use the **Gizwits IoT SDK**
(`com.gizwits.gizwifisdk.api.*`). That means:

- The protocol is documented (somewhat) at gizwits.com
- Each Jebao pump model has a "product config" JSON describing its
  attribute schema
- The SDK includes BLE parsing via `BluetoothChannelEngine.java` and
  `GizJsProtocol.java`
- Other Jebao app teardowns and Gizwits-based device research apply
  here too

### 2. Product config schemas are bundled in the APK

The decompiled APK has 43 product config JSONs at:

```
resources/assets/productConfig/*.json
```

10+ of them are pump-shaped (contain `Motor_Speed` and `SwitchON`) with
66 attributes each. A canonical aquarium-pump config is saved at
`docs/gizwits-schema/aquarium-pump.json` for offline reference.

The product key `ef4649b70d9a4c0aac513df7c4803a2d` (蓝牙水族泵 / "Bluetooth
Aquarium Pump") was used as the reference. Other candidates with same
66-attr shape:

| Product key | Chinese name | Likely model |
|---|---|---|
| `ef4649b70d9a4c0aac513df7c4803a2d` | 蓝牙水族泵 | aquarium pump |
| `e7b4649fdf8d413ba0a60d57fdde7101` | 蓝牙户外水泵 | outdoor pump |
| `b9b1a9dfd90c49b08b88be84e7df9e6b` | 蓝牙水泵调速器 | pump speed controller |
| `90b603b450c14b55b41e90724020203c` | 缸外过滤器WiFi_BLE | external filter |
| `64236a674d8342fcba0ffc5eb3965083` | 蓝牙缸外过滤器 | external filter (BLE) |
| `6a5c47b3ea364ecb841b47f5997a1775` | 水族泵WIFI_BLE | aquarium pump (Wi-Fi) |

If reverse-engineering a different model (DMP vs MDP), check the
corresponding product config — attribute IDs are likely the same for the
operational basics (0-15) but `AutoTime*` and other extension blocks
may vary.

### 3. The full attribute schema (66 attrs)

The first 16 attributes are the operational state — everything beyond is
scheduling (`AutoTime00` through `AutoTime47`, 6 bytes each, defining
on/off windows + per-window mode).

| ID | Name | Type | Description |
|---|---|---|---|
| 0 | `SwitchON` | bool | Power button |
| 1 | `Mode` | bool | 0:AP control, 1:Wireless control |
| 2 | `FeedSwitch` | bool | Feed mode toggle |
| **3** | **`Fault_Overcurrent`** | bool | Motor overcurrent / short circuit |
| **4** | **`Fault_Overvoltage`** | bool | Motor overvoltage |
| **5** | **`Fault_OverTemp`** | bool | Motor overtemperature |
| **6** | **`Fault_Undervoltage`** | bool | Motor undervoltage |
| **7** | **`Fault_Lockedrotor`** | bool | Locked rotor (impeller stuck) |
| **8** | **`Fault_no_liveload`** | bool | No-load (running dry) |
| **9** | **`Fault_UART`** | bool | Module ↔ mainboard comms failure |
| 10 | `TimerON` | bool | 0:timer off, 1:timer on |
| 11 | `AutoMode` | enum | 0:stop, 1:auto, 2:feed |
| 12 | `Motor_Speed` | uint8 | Motor gear, range 30-100, 0=stop |
| 13 | `FeedTime` | uint8 | Feed duration |
| 14 | `AutoGears` | uint8 | Currently-scheduled gear |
| 15 | `AutoFeedTime` | uint8 | Currently-scheduled feed time |
| 16 | `YMDData` | binary(4) | Y/M/D — byte0/1: year, byte2: month, byte3: day |
| 17 | `HMSData` | binary(4) | H/M/S — byte0 padding, byte1: h, byte2: m, byte3: s |
| 18-65 | `AutoTime00`-`AutoTime47` | binary(6) | 48 timer slots: start_h, start_m, end_h, end_m, mode, ... |

The 7 fault flags at IDs 3-9 **exactly match the bridge's
`MDP_FAULT_FLAGS` dict** (just shifted by 3 in bit numbering because IDs
0/1/2 pack first). The bridge's MDP fault detection is correct; it just
can't fire today because the polled `0x0100` response is too short to
reach byte 301 where the bit field lives.

## The bridge's wire format is a different abstraction

The bridge currently decodes the BLE notification stream into a custom
`(type_byte, attr_hi, attr_lo)` 3-tuple format, NOT into Gizwits
data-point IDs:

| Bridge attribute | type | hi | lo |
|---|---|---|---|
| Power | 0x00 | 0x00 | 0x01 |
| Feed | 0x00 | 0x00 | 0x04 |
| Mode | 0x00 | 0x10 | 0x02 |
| Flow | 0x00 | 0x80 | 0x00 |
| Frequency | 0x01 | 0x00 | 0x00 |

The bridge only recognizes `type=0x00` and `type=0x01`. Anything with a
different type byte falls through to the "unknown attribute" capture and
is published to `sensor.<pump>_last_unknown_code`.

### Observed unknown — `0x0c0000=0x28`

Captured from `dmp-65-right` on 2026-06-11 00:59:55. Type `0x0c` is an
entirely new "section" the bridge hasn't decoded — there could be 10+
more like it. Value 40 with no observable state change at the time.

Hypothesis ideas:
- Motor RPM ÷ 100 (40 → 4000 RPM, plausible)
- Motor temperature in °C (40°C, plausible for a running pump)
- A periodic heartbeat or counter
- Internal status flags

Need controlled-change observation to confirm — see "Mapping experiment"
below.

## Mapping experiment: `(type, hi, lo)` → Gizwits attribute ID

Method to systematically map the bridge's tuples to the schema:

1. On a test pump, note current bridge state: power, mode, flow, frequency.
2. Tail bridge logs:
   ```sh
   journalctl -fu jebao-mqtt.service | grep -E 'Unrecognized|Power|Flow|Mode|Frequency|Feed|attribute'
   ```
3. Open the Jebao Aqua app, change **exactly one attribute**:
   - Motor_Speed (slider) → expect tuple change
   - AutoMode (mode dropdown) → expect tuple change
   - TimerON toggle → ...
   - Per-slot AutoTimeN edit → ...
4. Watch which tuple's value changed. Record the mapping.
5. Restore, repeat for the next attribute.

A clean run through 10-15 attributes gives a good chunk of the schema
mapped, which then lets `_update_state_dmp` decode them all by name
instead of emitting `last_unknown_code` warnings.

Worth automating later: a small "tuple sniffer" mode in the bridge that
logs **every** `(type, hi, lo, value)` it sees (not just unknown ones)
to a separate file, with a timestamp. Combined with the experiment
above, mapping becomes trivial.

## Decompilation reproducibility

```sh
# XAPK source
~/Downloads/Jebao\ Aqua_3.3.23_APKPure\ \(1\).xapk

# Unwrap (XAPK is just a zip)
unzip -o ~/Downloads/Jebao\ Aqua_3.3.23_APKPure\ \(1\).xapk -d /tmp/jebao_apk

# Main APK
/tmp/jebao_apk/com.jebao.android.apk    # ~56 MB

# Decompile (jadx 1.5.3, ~2-3 minutes on M-series Mac)
brew install jadx
jadx --threads-count $(sysctl -n hw.ncpu) -d /tmp/jebao_src /tmp/jebao_apk/com.jebao.android.apk
```

Key paths under `/tmp/jebao_src/`:

| Path | Content |
|---|---|
| `resources/assets/productConfig/*.json` | 43 Gizwits product configs |
| `sources/com/gizwits/gizwifisdk/api/BluetoothChannelEngine.java` | BLE channel handler |
| `sources/com/gizwits/gizwifisdk/api/GizJsProtocol.java` | Universal product-config-driven parser |
| `sources/com/gizwits/gizwifisdk/api/Utils.java` | Helpers (includes `attr_vals` references) |
| `sources/com/gizwits/gizwifisdk/api/Constant.java` | Protocol constants |

The /tmp paths are ephemeral (vanish on reboot). Re-decompile from the
saved XAPK if needed.

## Next steps when you circle back

1. **Run the mapping experiment** for at least Motor_Speed, AutoMode,
   TimerON, FeedSwitch. Add the resulting tuples to the bridge's
   `_update_state_dmp`.
2. **Decode `type=0x0c`** specifically — value 40 was seen during steady
   state; watch whether it tracks Motor_Speed, internal temp, or runtime.
3. **Look at Gizwits `BluetoothChannelEngine.java`** more carefully —
   the parser there reads from product config and may give the exact
   byte→ID mapping rule. If found, the bridge can switch from manual
   tuple maintenance to a generic config-driven decoder.
4. **Consider adding a "fault flags" subscriber** on the bridge that
   uses the Gizwits schema directly — once a long-enough packet is
   received (or if a different polling command returns the full state),
   all 7 fault flags become visible. The dashboard fault precedence we
   added will then surface MDP faults automatically.
