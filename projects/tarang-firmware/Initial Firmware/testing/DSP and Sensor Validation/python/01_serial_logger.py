#!/usr/bin/env python3
"""
01_serial_logger.py — Tarang bring-up Stage 6
Read CSV stream from ESP32 over USB serial, save timestamped CSV.

Usage:
    python3 01_serial_logger.py /dev/ttyUSB0 921600
    python3 01_serial_logger.py                        # defaults below

Output:
    ~/tarang_data/tarang_YYYYMMDD_HHMMSS.csv
"""
import serial, csv, sys, time, os
from datetime import datetime

PORT = sys.argv[1] if len(sys.argv) > 1 else '/dev/ttyUSB0'
BAUD = int(sys.argv[2]) if len(sys.argv) > 2 else 921600
OUT_DIR = os.path.expanduser('~/tarang_data')
os.makedirs(OUT_DIR, exist_ok=True)

HEADER = ['t_us','ecg_idx','imu_idx','ecg_raw','ecg_mv',
          'ax','ay','az','imu_mag','lo+']

def main():
    fname = os.path.join(OUT_DIR, f'tarang_{datetime.now():%Y%m%d_%H%M%S}.csv')
    print(f'[Tarang] Opening {PORT} @ {BAUD} -> {fname}')
    ser = serial.Serial(PORT, BAUD, timeout=1)
    time.sleep(0.5)  # let ESP32 reset settle if DTR toggled
    ser.reset_input_buffer()

    n = 0
    t0 = time.time()
    print('[Tarang] Logging. Ctrl-C to stop.')
    try:
        with open(fname, 'w', newline='') as f:
            w = csv.writer(f)
            w.writerow(HEADER)
            for raw in ser:
                line = raw.decode('ascii', errors='ignore').strip()
                if not line:
                    continue
                if line.startswith('#'):
                    print(f'  HDR: {line}')
                    continue
                fields = line.split(',')
                if len(fields) < len(HEADER):
                    continue
                w.writerow(fields)
                n += 1
                if n % 500 == 0:
                    f.flush()
                    elapsed = time.time() - t0
                    rate = n / elapsed if elapsed > 0 else 0
                    print(f'  {n} rows | {rate:6.1f} rows/s | '
                          f'{os.path.getsize(fname)/1024:6.1f} KB')
    except KeyboardInterrupt:
        print('\n[Tarang] Stopped by user.')
    finally:
        ser.close()
    print(f'[Tarang] Saved {n} rows to {fname}')
    print(f'[Tarang] Next: python3 02_live_plot.py {fname}')

if __name__ == '__main__':
    main()
