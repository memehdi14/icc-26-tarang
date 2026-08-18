import serial
import serial.tools.list_ports
import time

BAUD_RATES = [9600, 19200, 38400, 57600, 115200, 230400, 460800, 921600, 1000000]
PORT = "COM11"

print(f"Scanning baud rates on {PORT}...")

for baud in BAUD_RATES:
    try:
        ser = serial.Serial(PORT, baud, timeout=0.5, rtscts=True)
        ser.rts = True
        ser.dtr = True
        ser.reset_input_buffer()
        time.sleep(0.5)
        raw = ser.read(500)
        ser.close()
        
        # Test how much valid ASCII text is decoded
        text = raw.decode('utf-8', errors='ignore')
        
        ascii_chars = sum(1 for c in text if 32 <= ord(c) <= 126 or c in '\r\n\t')
        ratio = (ascii_chars / len(text)) if text else 0
        
        preview = text.replace('\r', ' ').replace('\n', ' ')[:60]
        print(f"Baud {baud:7d} -> Read {len(raw):3d} bytes | Valid ASCII: {ratio*100:5.1f}% | Preview: {preview}")
        if "ECG" in text or "PPG" in text or "IMU" in text or "TARANG" in text:
            print(f"\n>>> MATCH FOUND! Correct Baud Rate is: {baud} <<<\n")
            break
    except Exception as e:
        print(f"Baud {baud:7d} -> Error: {e}")
