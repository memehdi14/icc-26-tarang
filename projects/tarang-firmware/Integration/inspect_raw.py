import serial
import time
import struct

PORT = "COM11"
BAUD = 115200

print(f"Reading raw hex bytes from {PORT} @ {BAUD}...")
try:
    ser = serial.Serial(PORT, BAUD, timeout=1)
    time.sleep(0.5)
    raw = ser.read(128)
    ser.close()
    
    print(f"Read {len(raw)} bytes:")
    print("HEX:", " ".join(f"{b:02X}" for b in raw[:64]))
    print("ASCII:", "".join(chr(b) if 32 <= b <= 126 else "." for b in raw[:64]))
except Exception as e:
    print(f"Error: {e}")
