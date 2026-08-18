import serial
import time

PORT = "COM11"
TEST_BAUDS = [115200, 230400, 460800, 921600]

print("Testing actual baud rate with live data...\n")

for baud in TEST_BAUDS:
    print(f"Trying {baud} baud:")
    try:
        ser = serial.Serial(PORT, baud, timeout=0.5)
        ser.reset_input_buffer()
        time.sleep(0.3)
        raw = ser.read(200)
        ser.close()
        
        if len(raw) > 0:
            # Try to decode
            text = raw.decode('utf-8', errors='replace')
            # Count readable characters
            readable = sum(1 for c in text if c.isprintable() or c in '\r\n\t')
            ratio = (readable / len(text)) * 100 if len(text) > 0 else 0
            
            # Show preview
            preview = text.replace('\r', '').replace('\n', ' ')[:80]
            print(f"  Read {len(raw)} bytes | {ratio:.1f}% readable")
            print(f"  Preview: {preview}")
            
            # Look for expected keywords
            if any(word in text for word in ["BOOT", "ECG", "PPG", "IMU", "init", "OK", "ERROR", "TARANG"]):
                print(f"  ✓✓✓ FOUND KEYWORDS! This is likely the correct baud rate! ✓✓✓")
        else:
            print(f"  No data received")
        print()
    except Exception as e:
        print(f"  Error: {e}\n")

print("\nInstructions:")
print("1. If a baud rate shows high % readable and recognizable text, that's your answer")
print("2. Update SL_IOSTREAM_EUSART_VCOM_BAUDRATE in config/sl_iostream_eusart_vcom_config.h")
print("3. Rebuild and reflash the firmware")
