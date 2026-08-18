import serial
import serial.tools.list_ports
import time
import sys

PORT = "COM11"
FIRMWARE_BAUD = 115200

print(f"=== Serial Port Diagnostic Tool ===\n")

# List all available ports
print("Available COM ports:")
for port in serial.tools.list_ports.comports():
    print(f"  {port.device}: {port.description}")
    if port.device == PORT:
        print(f"    -> Manufacturer: {port.manufacturer}")
        print(f"    -> Serial Number: {port.serial_number}")
        print(f"    -> Product: {port.product}")
print()

# Try to open the port
print(f"Attempting to open {PORT} at {FIRMWARE_BAUD} baud...")
try:
    ser = serial.Serial(
        port=PORT,
        baudrate=FIRMWARE_BAUD,
        timeout=2.0,
        parity=serial.PARITY_NONE,
        stopbits=serial.STOPBITS_ONE,
        bytesize=serial.EIGHTBITS,
        rtscts=False,
        dsrdtr=False
    )
    print(f"✓ Port opened successfully!")
    print(f"  Baudrate: {ser.baudrate}")
    print(f"  Parity: {ser.parity}")
    print(f"  Stop bits: {ser.stopbits}")
    print(f"  RTS/CTS: {ser.rtscts}")
    print()
    
    # Clear any stale data
    ser.reset_input_buffer()
    ser.reset_output_buffer()
    
    print("Listening for data (10 seconds)...")
    start_time = time.time()
    total_bytes = 0
    
    while time.time() - start_time < 10.0:
        if ser.in_waiting > 0:
            data = ser.read(ser.in_waiting)
            total_bytes += len(data)
            try:
                text = data.decode('utf-8', errors='replace')
                print(text, end='', flush=True)
            except:
                print(f"[{len(data)} bytes binary data]", flush=True)
        time.sleep(0.1)
    
    print(f"\n\nTotal bytes received: {total_bytes}")
    
    if total_bytes == 0:
        print("\n⚠ No data received. Possible causes:")
        print("  1. Firmware is not running or crashed during init")
        print("  2. Device is not powered or not connected")
        print("  3. Baud rate mismatch (configured for 115200 baud)")
        print("  4. Reset the device and try again immediately")
    
    ser.close()
    
except serial.SerialException as e:
    print(f"✗ Failed to open port: {e}")
    print("\nThis usually means:")
    print("  1. Another program has the port open (check VS Code terminals)")
    print("  2. Permission denied")
    print("  3. Port does not exist or is disconnected")
    sys.exit(1)
