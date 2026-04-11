#!/usr/bin/env python3
"""
Analyze the Test4 response which returned a large data packet
This might be a status/config response that reveals protocol details
"""

# Test4 response data from the logs
response_hex = """
00000003ce0201009469d878d800166e42646955
6e437675784c5031535141556d79366d71031148
0a1e00141a040900150239000000282ccaeeeeee
eeeeeeeeeeeeeeeeee00402cca3fffffffff402c
ca3ff824010009000000000000eeeeeeeeeeee2c
ca3f542ccaeeeeeeeeeeee00000000000000ffff
000300eeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeee
ee48434f42450000000000000000000000000000
0000000000000000000000372ebeb8372e000000
0000000000000000000000000000000000000000
00000000000000000000000000eeeeeeeeeeeeee
eeeeeeeeee0014010000012cca3f000000000000
000000000000000000eeeeeeeeeeeeeeeeeeeeee
ee006c1fcd3f0000000000000000000000000000
0000000000000000000000000000000000000000
000000000000000000000000000000eeeeeeeeee
ee000000000000000000000000eeeeeeeeeeee00
""".replace('\n', '')

# Convert to bytes
data = bytes.fromhex(response_hex)
print("📊 Analyzing Test4 Response Data")
print("="*60)
print(f"Total bytes: {len(data)}")
print()

# Parse Gizwits header
header = data[:6]
cmd_type = int.from_bytes(data[6:8], 'big')
print(f"Header: {header.hex()}")
print(f"Command type: 0x{cmd_type:04x}")

# Skip to payload after cmd_sn
payload_start = 12
payload = data[payload_start:]

print(f"\nPayload analysis ({len(payload)} bytes):")
print("-"*40)

# Look for patterns
print("\n🔍 Searching for meaningful values:")

# Check for speed value (72% = 0x48)
if b'\x48' in payload:
    positions = [i for i, byte in enumerate(payload) if byte == 0x48]
    print(f"Found value 72 (0x48) at positions: {positions}")

# Check for speed value (80% = 0x50)  
if b'\x50' in payload:
    positions = [i for i, byte in enumerate(payload) if byte == 0x50]
    print(f"Found value 80 (0x50) at positions: {positions}")

# Look for ASCII text
print("\n📝 ASCII text found:")
ascii_text = ""
for byte in payload:
    if 32 <= byte <= 126:  # Printable ASCII
        ascii_text += chr(byte)
    else:
        if len(ascii_text) > 3:  # Print if we have 4+ chars
            print(f"  '{ascii_text}'")
        ascii_text = ""
if ascii_text and len(ascii_text) > 3:
    print(f"  '{ascii_text}'")

# Check specific byte positions that might be status
print("\n🎯 Potential status bytes:")
print(f"Byte 37: 0x{payload[37]:02x} ({payload[37]})")  # Often speed in protocols
print(f"Byte 38: 0x{payload[38]:02x} ({payload[38]})")
print(f"Byte 39: 0x{payload[39]:02x} ({payload[39]})")

# Look for float values (common in IoT)
print("\n🔢 Potential float values (little-endian):")
import struct
for i in range(0, len(payload)-3, 4):
    try:
        float_val = struct.unpack('<f', payload[i:i+4])[0]
        if 0.0 < float_val < 100.0:  # Reasonable range for pump values
            print(f"  Offset {i}: {float_val:.2f}")
    except:
        pass

# Display hex dump of interesting sections
print("\n📋 Hex dump of first 100 bytes of payload:")
for i in range(0, min(100, len(payload)), 16):
    hex_str = ' '.join(f'{b:02x}' for b in payload[i:i+16])
    ascii_str = ''.join(chr(b) if 32 <= b <= 126 else '.' for b in payload[i:i+16])
    print(f"  {i:04x}: {hex_str:<48} | {ascii_str}")

print("\n💡 Observations:")
print("- Response starts with standard Gizwits header")
print("- Command 0x0194 appears to be a status/config response")
print("- Contains 'HCOBE' text (might be part of config)")
print("- Contains many 0xee bytes (padding or uninitialized)")
print("- Current pump speed (72%) might be encoded somewhere")