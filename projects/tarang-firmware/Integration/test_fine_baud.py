import serial
import time

PORT = "COM11"
# Test rates around 230400
TEST_BAUDS = [200000, 230400, 250000, 256000, 300000]

print("Fine-tuning baud rate detection...\n")

best_baud = None
best_ratio = 0

for baud in TEST_BAUDS:
    print(f"Trying {baud} baud:")
    try:
        ser = serial.Serial(PORT, baud, timeout=0.5)
        ser.reset_input_buffer()
        time.sleep(0.3)
        raw = ser.read(300)
        ser.close()
        
        if len(raw) > 10:
            # Try to decode
            text = raw.decode('utf-8', errors='replace')
            # Count readable characters
            readable = sum(1 for c in text if c.isprintable() or c in '\r\n\t')
            ratio = (readable / len(text)) * 100 if len(text) > 0 else 0
            
            # Show preview
            preview = text.replace('\r', '\\r').replace('\n', '\\n')[:100]
            print(f"  Read {len(raw)} bytes | {ratio:.1f}% readable")
            print(f"  Preview: {preview}")
            
            # Track best match
            if ratio > best_ratio:
                best_ratio = ratio
                best_baud = baud
            
            # Look for expected keywords
            keywords = ["BOOT", "ECG", "PPG", "IMU", "init", "OK", "ERROR", "TARANG", "app_", "sl_"]
            found = [w for w in keywords if w in text]
            if found:
                print(f"  ✓✓✓ FOUND: {', '.join(found)} ✓✓✓")
        else:
            print(f"  Only {len(raw)} bytes received")
        print()
    except Exception as e:
        print(f"  Error: {e}\n")

print(f"\n{'='*60}")
print(f"BEST MATCH: {best_baud} baud with {best_ratio:.1f}% readable")
print(f"{'='*60}")
