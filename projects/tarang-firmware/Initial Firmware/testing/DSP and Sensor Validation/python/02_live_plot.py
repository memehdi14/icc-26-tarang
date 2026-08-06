#!/usr/bin/env python3
"""
02_live_plot.py — Tarang bring-up Stage 7
Live plot ECG (top) and IMU magnitude (bottom) from a CSV log file
or live from a serial port.

Usage (offline, from saved CSV):
    python3 02_live_plot.py tarang_20250630_153000.csv

Usage (live from serial):
    python3 02_live_plot.py --live /dev/ttyUSB0 921600
"""
import sys, os, time
import numpy as np
import matplotlib.pyplot as plt
import matplotlib.animation as animation

ECG_HZ = 250
IMU_HZ = 100
WINDOW_SEC = 4.0

def load_csv(path):
    print(f'[Tarang] Loading {path} ...')
    rows = []
    header = None
    with open(path, 'r', encoding='ascii', errors='ignore') as f:
        for line in f:
            s = line.strip()
            if not s:
                continue
            if s.startswith('#'):
                continue
            fields = s.split(',')
            if header is None:
                # First non-comment, non-empty line is the header
                header = fields
                continue
            if len(fields) < 10:
                continue
            try:
                rows.append([
                    float(fields[0]),   # t_us
                    float(fields[1]),   # ecg_idx
                    float(fields[2]),   # imu_idx
                    float(fields[3]),   # ecg_raw
                    float(fields[4]),   # ecg_mv
                    float(fields[5]),   # ax
                    float(fields[6]),   # ay
                    float(fields[7]),   # az
                    float(fields[8]),   # imu_mag
                    float(fields[9]),   # lo+
                ])
            except (ValueError, IndexError):
                continue
    if not rows:
        raise SystemExit('CSV has no data rows after header')
    arr = np.array(rows, dtype=np.float64)
    # Return as structured access via dict for compatibility with rest of code
    return {
        't_us':    arr[:, 0],
        'ecg_idx': arr[:, 1],
        'imu_idx': arr[:, 2],
        'ecg_raw': arr[:, 3],
        'ecg_mv':  arr[:, 4],
        'ax':      arr[:, 5],
        'ay':      arr[:, 6],
        'az':      arr[:, 7],
        'imu_mag': arr[:, 8],
        'lo+':     arr[:, 9],
    }

def plot_offline(path):
    data = load_csv(path)
    t_us   = data['t_us']
    ecg_mv = data['ecg_mv']
    imu_mag= data['imu_mag']
    t = (t_us - t_us[0]) / 1e3  # ms

    fig, (ax1, ax2) = plt.subplots(2, 1, figsize=(12, 6), sharex=True,
                                    constrained_layout=True)
    ax1.plot(t, ecg_mv, lw=0.6, color='crimson')
    ax1.set_ylabel('ECG (mV)')
    ax1.set_title(f'Tarang — {os.path.basename(path)}')
    ax1.grid(alpha=0.3)
    ax1.axhline(0, color='k', lw=0.5)

    ax2.plot(t, imu_mag, lw=0.6, color='navy')
    ax2.set_ylabel('|a| (LSB)')
    ax2.set_xlabel('Time (ms)')
    ax2.grid(alpha=0.3)
    ax2.axhline(16384, color='g', ls='--', lw=0.5, label='1g baseline')
    ax2.legend(loc='upper right')

    plt.savefig(path.replace('.csv','_preview.png'), dpi=120)
    plt.show()

def plot_live(port, baud):
    import serial
    ser = serial.Serial(port, baud, timeout=1)
    ser.reset_input_buffer()

    n_win = int(ECG_HZ * WINDOW_SEC)
    ecg_buf = np.zeros(n_win)
    imu_buf = np.zeros(n_win)
    t_buf   = np.arange(n_win) / ECG_HZ

    fig, (ax1, ax2) = plt.subplots(2, 1, figsize=(12, 6), sharex=True,
                                    constrained_layout=True)
    line_ecg, = ax1.plot(t_buf, ecg_buf, lw=0.6, color='crimson')
    ax1.set_ylim(-1500, 1500)
    ax1.set_ylabel('ECG (mV)')
    ax1.set_title(f'Tarang LIVE — {port}')
    ax1.grid(alpha=0.3); ax1.axhline(0, color='k', lw=0.5)

    line_imu, = ax2.plot(t_buf, imu_buf, lw=0.6, color='navy')
    ax2.set_ylim(15000, 18000)
    ax2.set_ylabel('|a| (LSB)')
    ax2.set_xlabel('Time (s)')
    ax2.grid(alpha=0.3)
    ax2.axhline(16384, color='g', ls='--', lw=0.5)

    def update(frame):
        # Drain available serial lines, push into buffer
        while ser.in_waiting > 0:
            try:
                raw = ser.readline().decode('ascii', errors='ignore').strip()
            except Exception:
                break
            if not raw or raw.startswith('#') or ',' not in raw:
                continue
            f = raw.split(',')
            try:
                ecg_mv = float(f[4])
                imu_mag = float(f[8])
            except (IndexError, ValueError):
                continue
            ecg_buf[:-1] = ecg_buf[1:];  ecg_buf[-1] = ecg_mv
            imu_buf[:-1] = imu_buf[1:];  imu_buf[-1] = imu_mag
        line_ecg.set_ydata(ecg_buf)
        line_imu.set_ydata(imu_buf)
        # autoscale ECG a little
        emin, emax = float(np.min(ecg_buf)), float(np.max(ecg_buf))
        pad = max(100, (emax - emin) * 0.1)
        ax1.set_ylim(emin - pad, emax + pad)
        return line_ecg, line_imu

    ani = animation.FuncAnimation(fig, update, interval=40, blit=False,
                                  cache_frame_data=False)
    plt.show()
    ser.close()

def main():
    if '--live' in sys.argv:
        i = sys.argv.index('--live')
        port = sys.argv[i+1] if i+1 < len(sys.argv) else '/dev/ttyUSB0'
        baud = int(sys.argv[i+2]) if i+2 < len(sys.argv) else 921600
        plot_live(port, baud)
    elif len(sys.argv) > 1:
        plot_offline(sys.argv[1])
    else:
        print(__doc__)

if __name__ == '__main__':
    main()
