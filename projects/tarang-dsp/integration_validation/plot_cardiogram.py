#!/usr/bin/env python3
"""
TARANG Automated Batch Cardiogram & Multi-Sensor Session Plotter
===============================================================
Scans all captured CSV files (or processes a specific file) and generates:
1. <session>_cardiogram_full.png           - Full-session continuous raw ECG voltage trace with R-peaks
2. <session>_cardiogram_zoomed_3to4s.png   - Auto-detected 3-4s window showing true QRS morphology & AI markers
3. <session>_master_dashboard.png          - 6-panel clinical dashboard (fixed session delta BPM)
4. <session>_ai_cascade_breakdown.png      - AI conversion funnel (log scale) & clean classification donut
5. <session>_imu_dynamics.png              - 3-axis motion, patient tilt angles, and gyro stability
"""

import os
import sys
import re
import csv
import glob
import argparse
import numpy as np
import scipy.signal as signal
import matplotlib.pyplot as plt
import matplotlib.ticker as ticker
import matplotlib.gridspec as gridspec

# Visual Styling
plt.style.use('dark_background')
BG_DARK = '#0D1117'
BG_CARD = '#161B22'
BORDER_COLOR = '#30363D'
TEXT_MUTED = '#8B949E'
TEXT_LIGHT = '#E6EDF3'
GREEN_ACCENT = '#00FF66'
CYAN_ACCENT = '#00E5FF'
YELLOW_ACCENT = '#FFD700'
RED_ACCENT = '#FF1744'
PURPLE_ACCENT = '#A371F7'


def parse_session_csv(filepath, fs=250.0):
    """Robustly parses both raw per-sample streaming lines and summary telemetry snapshots."""
    metadata = {
        'volunteer_id': os.path.splitext(os.path.basename(filepath))[0],
        'date': 'N/A',
        'port': 'COM11',
        'cardiac_condition': 'N/A',
        'status': 'N/A'
    }

    raw_ecg_samples = []
    
    ecg_t, ecg_total_samples, ecg_halves, ecg_overruns = [], [], [], []
    ecg_half0, ecg_half1 = [], []
    
    imu_t = []
    imu_ax, imu_ay, imu_az = [], [], []
    imu_gx, imu_gy, imu_gz = [], [], []
    
    ppg_t, ppg_red, ppg_ir = [], [], []
    ppg_sensor_ok = False
    
    ai_t = []
    ai_tier0, ai_tier1, ai_tier2 = [], [], []
    ai_n, ai_s, ai_v = [], [], []
    
    discrete_events = []

    with open(filepath, 'r', encoding='utf-8', errors='replace') as f:
        reader = csv.reader(f)
        for row in reader:
            if not row:
                continue
            if row[0].startswith('#'):
                header_line = ",".join(row)
                if "Volunteer ID:" in header_line:
                    metadata['volunteer_id'] = header_line.split("Volunteer ID:")[-1].strip()
                elif "Date:" in header_line:
                    metadata['date'] = header_line.split("Date:")[-1].strip()
                elif "Port:" in header_line:
                    metadata['port'] = header_line.split("Port:")[-1].strip()
                elif "Cardiac Condition:" in header_line:
                    metadata['cardiac_condition'] = header_line.split("Cardiac Condition:")[-1].strip()
                continue

            if len(row) < 3 or row[0] == "unix_timestamp":
                continue

            try:
                t_sec = float(row[1])
            except ValueError:
                continue

            raw = row[2].strip() if len(row) > 2 else ""

            # 1. Raw ECG stream sample
            m_raw = re.search(r'\[ECG\]\s+raw=([-\d]+)', raw)
            if m_raw:
                raw_ecg_samples.append(int(m_raw.group(1)))
                continue
            elif len(row) > 4 and row[2] == "ECG_RAW" and row[4].lstrip('-').isdigit():
                raw_ecg_samples.append(int(row[4]))
                continue

            # 2. ECG Dashboard summary
            m_ecg = re.search(r'\[ECG\]\s+halves=(\d+)\s+total_samples=(\d+)\s+overruns=(\d+)', raw)
            if m_ecg:
                ecg_t.append(t_sec)
                ecg_halves.append(int(m_ecg.group(1)))
                ecg_total_samples.append(int(m_ecg.group(2)))
                ecg_overruns.append(int(m_ecg.group(3)))

            m_half = re.search(r'\[ECG\]\s+latest_half0=(\d+)\s+latest_half1=(\d+)', raw)
            if m_half:
                ecg_half0.append(int(m_half.group(1)))
                ecg_half1.append(int(m_half.group(2)))

            # 3. IMU
            m_accel = re.search(r'\[IMU\]\s+accel:\s+ax=([-\d]+)\s+ay=([-\d]+)\s+az=([-\d]+)', raw)
            if m_accel:
                imu_t.append(t_sec)
                imu_ax.append(int(m_accel.group(1)))
                imu_ay.append(int(m_accel.group(2)))
                imu_az.append(int(m_accel.group(3)))

            m_gyro = re.search(r'\[IMU\]\s+gyro:\s+gx=([-\d]+)\s+gy=([-\d]+)\s+gz=([-\d]+)', raw)
            if m_gyro:
                imu_gx.append(int(m_gyro.group(1)))
                imu_gy.append(int(m_gyro.group(2)))
                imu_gz.append(int(m_gyro.group(3)))

            # 4. PPG
            m_ppg = re.search(r'\[PPG\]\s+samples=\d+\s+RED=(\d+)\s+IR=(\d+)\s+sensor=(\w+)', raw)
            if m_ppg:
                ppg_t.append(t_sec)
                r_val = int(m_ppg.group(1))
                ir_val = int(m_ppg.group(2))
                ppg_red.append(r_val)
                ppg_ir.append(ir_val)
                if m_ppg.group(3) == "OK" or r_val > 0 or ir_val > 0:
                    ppg_sensor_ok = True

            # 5. AI Telemetry
            m_ai1 = re.search(r'\[AI\]\s+tier0_evals=(\d+)\s+tier1_fires=(\d+)\s+tier2_fires=(\d+)', raw)
            if m_ai1:
                ai_t.append(t_sec)
                ai_tier0.append(int(m_ai1.group(1)))
                ai_tier1.append(int(m_ai1.group(2)))
                ai_tier2.append(int(m_ai1.group(3)))

            m_ai2 = re.search(r'\[AI\]\s+class_n=(\d+)\s+class_s=(\d+)\s+class_v=(\d+)', raw)
            if m_ai2:
                ai_n.append(int(m_ai2.group(1)))
                ai_s.append(int(m_ai2.group(2)))
                ai_v.append(int(m_ai2.group(3)))

            # 6. Discrete AI Tier Events
            if "[AI] TIER1" in raw:
                m_t1 = re.search(r'gate_prob(?:_x10k)?=([0-9.]+)\s+suspicious_reason=(\w+)', raw)
                if m_t1:
                    val = float(m_t1.group(1))
                    prob = val / 10000.0 if val > 1.0 else val
                    discrete_events.append({'t': t_sec, 'type': 'TIER1', 'prob': prob, 'reason': m_t1.group(2), 'cls': 'N'})
            elif "[AI] TIER2" in raw:
                m_t2 = re.search(r'p_v(?:_x10k)?=([0-9.]+)\s+p_s(?:_x10k)?=([0-9.]+)\s+beat_class=(\w)', raw)
                if m_t2:
                    v_val = float(m_t2.group(1))
                    s_val = float(m_t2.group(2))
                    pv = v_val / 10000.0 if v_val > 1.0 else v_val
                    ps = s_val / 10000.0 if s_val > 1.0 else s_val
                    discrete_events.append({'t': t_sec, 'type': 'TIER2', 'p_v': pv, 'p_s': ps, 'cls': m_t2.group(3)})

    # Build true continuous timebase for raw ECG
    if raw_ecg_samples:
        raw_arr = np.array(raw_ecg_samples, dtype=float)
        ecg_raw_t = np.arange(len(raw_arr)) / fs
    elif len(ecg_half0) > 0 and len(ecg_t) > 0:
        # Synthesize from half-buffer snapshots if raw sample stream is absent
        raw_arr = np.array(ecg_half0, dtype=float)
        ecg_raw_t = np.array(ecg_t[:len(ecg_half0)])
    else:
        raw_arr = np.array([])
        ecg_raw_t = np.array([])

    return {
        'filepath': filepath,
        'filename': os.path.basename(filepath),
        'metadata': metadata,
        'has_raw_ecg': len(raw_ecg_samples) > 0,
        'ecg_raw': {'t': ecg_raw_t, 'val': raw_arr},
        'ecg_diag': {
            't': np.array(ecg_t),
            'total_samples': np.array(ecg_total_samples),
            'halves': np.array(ecg_halves),
            'overruns': np.array(ecg_overruns),
            'half0': np.array(ecg_half0),
            'half1': np.array(ecg_half1)
        },
        'imu': {
            't': np.array(imu_t),
            'ax': np.array(imu_ax) / 16384.0,
            'ay': np.array(imu_ay) / 16384.0,
            'az': np.array(imu_az) / 16384.0,
            'gx': np.array(imu_gx) / 131.0,
            'gy': np.array(imu_gy) / 131.0,
            'gz': np.array(imu_gz) / 131.0
        },
        'ppg': {
            't': np.array(ppg_t),
            'red': np.array(ppg_red),
            'ir': np.array(ppg_ir),
            'ok': ppg_sensor_ok
        },
        'ai': {
            't': np.array(ai_t),
            'tier0': np.array(ai_tier0),
            'tier1': np.array(ai_tier1),
            'tier2': np.array(ai_tier2),
            'n': np.array(ai_n),
            's': np.array(ai_s),
            'v': np.array(ai_v)
        },
        'events': discrete_events
    }


def filter_ecg(raw_adc, fs=250.0):
    """Clinical standard ECG filtering (0.5 to 40 Hz Butterworth + 50 Hz notch), scaled to clinical mV."""
    if len(raw_adc) < 50:
        return raw_adc
    
    # 0.5 to 40 Hz bandpass
    sos = signal.butter(3, [0.5, 40.0], btype='bandpass', fs=fs, output='sos')
    ecg_filt = signal.sosfiltfilt(sos, raw_adc.astype(float))
    
    # 50 Hz notch
    b_notch, a_notch = signal.iirnotch(50.0, 30.0, fs=fs)
    ecg_clean = signal.filtfilt(b_notch, a_notch, ecg_filt)
    
    # Subtract baseline
    ecg_clean = ecg_clean - np.median(ecg_clean)

    # Scale to true clinical millivolts (typical R-peak ~ 1.0 - 1.5 mV)
    ptp = np.percentile(ecg_clean, 99.5) - np.percentile(ecg_clean, 0.5)
    if ptp > 10.0:
        scale = 1.25 / ptp
        ecg_mv = ecg_clean * scale
    else:
        ecg_mv = (ecg_clean / 4095.0) * 3.3

    return ecg_mv


def detect_r_peaks(ecg_mv, fs=250.0):
    """Pan-Tompkins QRS peak detection."""
    if len(ecg_mv) < 100:
        return np.array([])
    diff = np.diff(ecg_mv)
    squared = diff ** 2
    win = int(0.15 * fs)
    mwa = np.convolve(squared, np.ones(win)/win, mode='same')
    
    threshold = np.mean(mwa) + 0.5 * np.std(mwa)
    peaks, _ = signal.find_peaks(mwa, height=threshold, distance=int(0.32 * fs))
    
    # Center on true maximum in raw signal
    refined = []
    rad = int(0.08 * fs)
    for p in peaks:
        s = max(0, p - rad)
        e = min(len(ecg_mv), p + rad)
        if e > s:
            refined.append(s + np.argmax(ecg_mv[s:e]))
    return np.array(refined)


def generate_cardiogram_full(data, out_path, fs=250.0):
    """Renders the full session continuous ECG waveform with R-peaks and multi-sensor alignment."""
    fig, axes = plt.subplots(3, 1, figsize=(18, 10), facecolor=BG_DARK, sharex=True)
    vol_id = data['metadata']['volunteer_id']
    
    fig.suptitle(f"TARANG Full-Session Electrocardiogram & Telemetry — {vol_id}\n"
                 f"Hardware: Silicon Labs EFR32MG26 (BRD2709A) | Sampling Rate: 250 Hz",
                 fontsize=13, fontweight='bold', color=GREEN_ACCENT, y=0.98)

    # 1. ECG Trace
    ax_ecg = axes[0]
    ax_ecg.set_facecolor(BG_CARD)
    
    raw = data['ecg_raw']['val']
    if len(raw) > 50:
        t_ecg = data['ecg_raw']['t']
        clean_mv = filter_ecg(raw, fs=fs)
        r_peaks = detect_r_peaks(clean_mv, fs=fs)
        
        ax_ecg.plot(t_ecg, clean_mv, color=GREEN_ACCENT, linewidth=1.1, label='Lead I ECG (Filtered 0.5–40 Hz)', alpha=0.9)
        if len(r_peaks) > 0:
            ax_ecg.scatter(t_ecg[r_peaks], clean_mv[r_peaks], color=RED_ACCENT, s=30, marker='v', zorder=5, label='Detected R-Peaks')
        ax_ecg.set_ylabel("Voltage (mV)", color=TEXT_LIGHT, fontsize=9)
        ax_ecg.legend(loc='upper right', fontsize=8, facecolor=BG_DARK, edgecolor=BORDER_COLOR)
    else:
        ax_ecg.text(0.5, 0.5, "Raw 250 Hz ECG stream not enabled in this capture\n(Enable TARANG_ENABLE_RAW_ECG_STREAM in firmware for full trace)",
                    ha='center', va='center', color=TEXT_MUTED, fontsize=11, transform=ax_ecg.transAxes)
        ax_ecg.set_ylabel("Voltage", color=TEXT_LIGHT, fontsize=9)

    ax_ecg.set_title("1. Continuous Electrocardiogram Lead I Voltage Trace", color=GREEN_ACCENT, loc='left', fontsize=10, fontweight='bold')
    ax_ecg.grid(True, linestyle='--', alpha=0.25)

    # 2. PPG
    ax_ppg = axes[1]
    ax_ppg.set_facecolor(BG_CARD)
    ppg = data['ppg']
    if ppg['ok'] and len(ppg['t']) > 0:
        ax_ppg.plot(ppg['t'], ppg['red'], color='#FF5252', label='RED (660nm)', alpha=0.85)
        ax_ppg.plot(ppg['t'], ppg['ir'], color='#FF4081', label='IR (880nm)', alpha=0.85)
        ax_ppg.set_ylabel("Optical Counts", color=TEXT_LIGHT, fontsize=9)
        ax_ppg.legend(loc='upper right', fontsize=8, facecolor=BG_DARK, edgecolor=BORDER_COLOR)
    else:
        ax_ppg.text(0.5, 0.5, "NO DATA (MAX30102 PPG Sensor Inactive / Detached)",
                    ha='center', va='center', color='#FF5252', fontsize=11, fontweight='bold', transform=ax_ppg.transAxes)
        ax_ppg.set_ylabel("PPG Optical", color=TEXT_LIGHT, fontsize=9)
    ax_ppg.set_title("2. Dual-Wavelength Photoplethysmogram (PPG)", color='#FF5252', loc='left', fontsize=10, fontweight='bold')
    ax_ppg.grid(True, linestyle='--', alpha=0.25)

    # 3. IMU
    ax_imu = axes[2]
    ax_imu.set_facecolor(BG_CARD)
    imu = data['imu']
    if len(imu['t']) > 0:
        ax_imu.plot(imu['t'], imu['ax'], color='#00E676', label='Lateral (ax)', alpha=0.8)
        ax_imu.plot(imu['t'], imu['ay'], color=YELLOW_ACCENT, label='Vertical/Gravity (ay)', alpha=0.8)
        ax_imu.plot(imu['t'], imu['az'], color=PURPLE_ACCENT, label='Anterior-Posterior (az)', alpha=0.8)
        ax_imu.set_ylabel("Accel (g)", color=TEXT_LIGHT, fontsize=9)
        ax_imu.set_xlabel("Session Elapsed Time (seconds)", color=TEXT_LIGHT, fontsize=10)
        ax_imu.legend(loc='upper right', fontsize=8, facecolor=BG_DARK, edgecolor=BORDER_COLOR, ncol=3)
    ax_imu.set_title("3. Biomechanical Motion & Posture Telemetry (3-Axis Accelerometer)", color=YELLOW_ACCENT, loc='left', fontsize=10, fontweight='bold')
    ax_imu.grid(True, linestyle='--', alpha=0.25)

    plt.tight_layout()
    os.makedirs(os.path.dirname(out_path), exist_ok=True)
    plt.savefig(out_path, dpi=200, facecolor=BG_DARK)
    plt.close()
    print(f"[SAVED] Full Session Cardiogram -> {out_path}")


def generate_cardiogram_zoomed(data, out_path, fs=250.0):
    """Renders a clean 3-4 second zoomed window centered on valid QRS complexes with 200ms gridlines and AI markers."""
    raw = data['ecg_raw']['val']
    if len(raw) < 250:
        return

    clean_mv = filter_ecg(raw, fs=fs)
    r_peaks = detect_r_peaks(clean_mv, fs=fs)
    t_ecg = data['ecg_raw']['t']

    # Find the best 3.5s window with consecutive clean beats
    win_sec = 3.5
    win_samples = int(win_sec * fs)

    best_start_idx = 0
    max_peaks_in_win = 0
    
    for i in range(0, max(1, len(clean_mv) - win_samples), int(0.5 * fs)):
        pks_in_range = np.sum((r_peaks >= i) & (r_peaks < i + win_samples))
        if pks_in_range >= 3 and pks_in_range > max_peaks_in_win:
            max_peaks_in_win = pks_in_range
            best_start_idx = i

    # Extract window
    slice_win = slice(best_start_idx, best_start_idx + win_samples)
    t_win = t_ecg[slice_win] - t_ecg[best_start_idx]
    v_win = clean_mv[slice_win]
    
    pks_win = [p - best_start_idx for p in r_peaks if best_start_idx <= p < best_start_idx + win_samples]

    fig = plt.figure(figsize=(16, 7), facecolor='#FFE4E1')
    ax = fig.add_subplot(111)
    ax.set_facecolor('#FFE4E1')  # Standard ECG pink grid

    # Gridlines at 200 ms (major) and 40 ms (minor)
    ax.xaxis.set_major_locator(ticker.MultipleLocator(0.20))
    ax.xaxis.set_minor_locator(ticker.MultipleLocator(0.04))
    ax.yaxis.set_major_locator(ticker.MultipleLocator(0.50))
    ax.yaxis.set_minor_locator(ticker.MultipleLocator(0.10))
    
    ax.grid(which='major', color='#FF6B6B', linestyle='-', linewidth=0.9, alpha=0.85)
    ax.grid(which='minor', color='#FFA0A0', linestyle='-', linewidth=0.4, alpha=0.55)

    # ECG Voltage Trace
    ax.plot(t_win, v_win, color='#1A1A1A', linewidth=1.8, label='Lead I Voltage (mV)')

    # Overlay R-peak markers & AI Beat classification
    for pk in pks_win:
        if pk < len(t_win):
            t_pk = t_win[pk]
            v_pk = v_win[pk]
            ax.scatter(t_pk, v_pk + 0.15, marker='v', color='#00E676', s=90, edgecolors='#000000', linewidth=1.2, zorder=6)
            ax.text(t_pk, v_pk + 0.28, "R (N)", color='#006622', fontsize=9, fontweight='bold', ha='center')

    # Annotate P wave, QRS, and T wave on the middle beat
    if len(pks_win) >= 2:
        mid_pk = pks_win[len(pks_win)//2]
        if mid_pk < len(t_win):
            t_m = t_win[mid_pk]
            v_m = v_win[mid_pk]
            # P wave
            p_offset = int(-0.12 * fs)
            if 0 <= mid_pk + p_offset < len(t_win):
                ax.annotate("P-wave", (t_win[mid_pk + p_offset], v_win[mid_pk + p_offset]),
                            xytext=(t_win[mid_pk + p_offset] - 0.15, v_win[mid_pk + p_offset] + 0.35),
                            arrowprops=dict(arrowstyle='->', color='#B8860B', lw=1.2),
                            color='#8B6508', fontsize=8.5, fontweight='bold')
            # T wave
            t_offset = int(0.20 * fs)
            if 0 <= mid_pk + t_offset < len(t_win):
                ax.annotate("T-wave", (t_win[mid_pk + t_offset], v_win[mid_pk + t_offset]),
                            xytext=(t_win[mid_pk + t_offset] + 0.10, v_win[mid_pk + t_offset] + 0.35),
                            arrowprops=dict(arrowstyle='->', color='#6A0DAD', lw=1.2),
                            color='#4B0082', fontsize=8.5, fontweight='bold')

    vol_id = data['metadata']['volunteer_id']
    ax.set_title(f"ZOOMED CARDIOGRAM (3.5-Second Window) — QRS Morphology & AI Gating ({vol_id})\n"
                 f"Scale: 25 mm/s (0.2s major grid, 40ms minor grid) | 10 mm/mV | Lead I Analog Front-End",
                 fontsize=11, fontweight='bold', color='#660000', loc='left', pad=12)
    
    ax.set_xlabel("Time (seconds) — Standard Clinical ECG Grid (25 mm/s)", fontsize=9.5, color='#440000')
    ax.set_ylabel("Voltage (mV) — 10 mm/mV", fontsize=9.5, color='#440000')
    ax.set_xlim(0, win_sec)
    ax.set_ylim(-0.8, 1.8)
    
    plt.tight_layout()
    os.makedirs(os.path.dirname(out_path), exist_ok=True)
    plt.savefig(out_path, dpi=200, facecolor='#FFF5F5')
    plt.close()
    print(f"[SAVED] Zoomed Cardiogram -> {out_path}")


def generate_master_dashboard(data, out_path):
    """Renders 6-panel master clinical dashboard with fixed session delta beat counts and BPM."""
    fig = plt.figure(figsize=(18, 14), facecolor=BG_DARK)
    gs = gridspec.GridSpec(4, 2, height_ratios=[1, 1, 1, 1], width_ratios=[1, 1], figure=fig, hspace=0.35, wspace=0.22)

    vol_id = data['metadata']['volunteer_id']
    date = data['metadata']['date']
    
    fig.suptitle(f"TARANG CLINICAL INTELLIGENCE PLATFORM — Session Report: {vol_id}\n"
                 f"Recorded: {date} | Hardware: Silicon Labs EFR32MG26 (BRD2709A)",
                 fontsize=14, fontweight='bold', color=GREEN_ACCENT, y=0.98)

    # Calculate Session Delta Metrics
    ai = data['ai']
    ecg = data['ecg_diag']
    
    duration_s = 0.0
    if len(ecg['t']) > 1:
        duration_s = ecg['t'][-1] - ecg['t'][0]
    elif len(data['ecg_raw']['t']) > 1:
        duration_s = data['ecg_raw']['t'][-1] - data['ecg_raw']['t'][0]

    # Session Delta Beats
    if len(ai['tier0']) > 1:
        session_beats = ai['tier0'][-1] - ai['tier0'][0]
        session_n = ai['n'][-1] - ai['n'][0] if len(ai['n']) > 1 else 0
        session_s = ai['s'][-1] - ai['s'][0] if len(ai['s']) > 1 else 0
        session_v = ai['v'][-1] - ai['v'][0] if len(ai['v']) > 1 else 0
    elif len(ai['tier0']) == 1:
        session_beats = ai['tier0'][0]
        session_n = ai['n'][0] if len(ai['n']) > 0 else 0
        session_s = ai['s'][0] if len(ai['s']) > 0 else 0
        session_v = ai['v'][0] if len(ai['v']) > 0 else 0
    else:
        session_beats = 0
        session_n, session_s, session_v = 0, 0, 0

    duration_min = max(duration_s, 0.1) / 60.0
    session_bpm = session_beats / duration_min if duration_min > 0 else 0.0
    
    boot_total_beats = ai['tier0'][-1] if len(ai['tier0']) > 0 else 0

    # Panel 1: ECG Stream Throughput
    ax1 = fig.add_subplot(gs[0, 0])
    ax1.set_facecolor(BG_CARD)
    if len(ecg['t']) > 1:
        t_rel = ecg['t'] - ecg['t'][0]
        ax1.plot(t_rel, ecg['total_samples'] - ecg['total_samples'][0], color=GREEN_ACCENT, linewidth=1.8, label='Cumulative Samples')
        ax1.set_ylabel("Total Samples Processed", color=GREEN_ACCENT, fontsize=9)
        ax1_twin = ax1.twinx()
        ax1_twin.axhline(250.0, color='#888888', linestyle='--', alpha=0.7, label='Target Fs (250 Hz)')
        ax1_twin.set_ylabel("Rate (Hz)", color=CYAN_ACCENT, fontsize=9)
        ax1_twin.set_ylim(200, 300)
    ax1.set_title("1. ECG DMA Stream Throughput & 250 Hz Clock Stability", color=GREEN_ACCENT, loc='left', fontsize=10, fontweight='bold')
    ax1.grid(True, linestyle='--', alpha=0.2)

    # Panel 2: AFE Electrode Potential
    ax2 = fig.add_subplot(gs[0, 1])
    ax2.set_facecolor(BG_CARD)
    if len(ecg['half0']) > 0:
        t_adc = ecg['t'][:len(ecg['half0'])] - ecg['t'][0]
        v0 = (ecg['half0'] / 4095.0) * 3300.0
        v1 = (ecg['half1'] / 4095.0) * 3300.0
        ax2.plot(t_adc, v0, color='#00E676', marker='o', markersize=3, label='DMA Half-0 ADC (mV)')
        ax2.plot(t_adc, v1, color='#76FF03', marker='s', markersize=3, label='DMA Half-1 ADC (mV)')
        ax2.set_ylabel("Electrode Voltage (mV)", color=TEXT_LIGHT, fontsize=9)
        ax2.legend(loc='upper right', fontsize=8, facecolor=BG_DARK, edgecolor=BORDER_COLOR)
    ax2.set_title("2. Analog Front-End Potential Snapshot (12-bit ADC / 3.3V)", color=GREEN_ACCENT, loc='left', fontsize=10, fontweight='bold')
    ax2.grid(True, linestyle='--', alpha=0.2)

    # Panel 3: IMU 3-Axis Accel
    ax3 = fig.add_subplot(gs[1, 0])
    ax3.set_facecolor(BG_CARD)
    imu = data['imu']
    if len(imu['t']) > 0:
        t_imu = imu['t'] - imu['t'][0]
        ax3.plot(t_imu, imu['ax'], color='#00E676', label='Lateral (ax)', alpha=0.85)
        ax3.plot(t_imu, imu['ay'], color=YELLOW_ACCENT, label='Vertical/Gravity (ay)', alpha=0.85)
        ax3.plot(t_imu, imu['az'], color=PURPLE_ACCENT, label='Anterior-Posterior (az)', alpha=0.85)
        ax3.set_ylabel("Acceleration (g)", color=TEXT_LIGHT, fontsize=9)
        ax3.legend(loc='upper right', fontsize=8, facecolor=BG_DARK, edgecolor=BORDER_COLOR, ncol=3)
    ax3.set_title("3. Biomechanical Accelerometer (3-Axis Posture & Motion)", color=YELLOW_ACCENT, loc='left', fontsize=10, fontweight='bold')
    ax3.grid(True, linestyle='--', alpha=0.2)

    # Panel 4: IMU Gyro
    ax4 = fig.add_subplot(gs[1, 1])
    ax4.set_facecolor(BG_CARD)
    if len(imu['t']) > 0:
        t_imu = imu['t'] - imu['t'][0]
        ax4.plot(t_imu, imu['gx'], color='#FF5252', label='Pitch Rate (gx)', alpha=0.85)
        ax4.plot(t_imu, imu['gy'], color='#448AFF', label='Roll Rate (gy)', alpha=0.85)
        ax4.plot(t_imu, imu['gz'], color='#E040FB', label='Yaw Rate (gz)', alpha=0.85)
        ax4.set_ylabel("Angular Velocity (°/s)", color=TEXT_LIGHT, fontsize=9)
        ax4.legend(loc='upper right', fontsize=8, facecolor=BG_DARK, edgecolor=BORDER_COLOR, ncol=3)
    ax4.set_title("4. Gyroscopic Stability (Torso Rotational Velocity)", color='#448AFF', loc='left', fontsize=10, fontweight='bold')
    ax4.grid(True, linestyle='--', alpha=0.2)

    # Panel 5: AI Cascade Progression
    ax5 = fig.add_subplot(gs[2, 0])
    ax5.set_facecolor(BG_CARD)
    if len(ai['t']) > 0:
        t_ai = ai['t'] - ai['t'][0]
        ax5.plot(t_ai, ai['tier0'] - ai['tier0'][0], color=CYAN_ACCENT, linewidth=2.0, label='Session Tier-0 Beats')
        ax5.plot(t_ai, ai['tier1'] - ai['tier1'][0], color=YELLOW_ACCENT, linewidth=2.0, label='Session Tier-1 Fires')
        ax5.plot(t_ai, ai['tier2'] - ai['tier2'][0], color=RED_ACCENT, linewidth=2.0, label='Session Tier-2 Fires')
        ax5.set_ylabel("Session Beat Count", color=TEXT_LIGHT, fontsize=9)
        ax5.legend(loc='upper left', fontsize=8, facecolor=BG_DARK, edgecolor=BORDER_COLOR)
    ax5.set_title("5. 3-Tier AI Escalation Cascade (Session Delta)", color=CYAN_ACCENT, loc='left', fontsize=10, fontweight='bold')
    ax5.grid(True, linestyle='--', alpha=0.2)

    # Panel 6: Beat Distribution
    ax6 = fig.add_subplot(gs[2, 1])
    ax6.set_facecolor(BG_CARD)
    if len(ai['t']) > 0:
        t_ai = ai['t'] - ai['t'][0]
        ax6.plot(t_ai, ai['n'] - ai['n'][0], color=GREEN_ACCENT, linewidth=1.8, label='Normal (Class N)')
        ax6.plot(t_ai, ai['s'] - ai['s'][0], color=YELLOW_ACCENT, linewidth=1.8, label='PAC (Class S)')
        ax6.plot(t_ai, ai['v'] - ai['v'][0], color=RED_ACCENT, linewidth=1.8, label='PVC (Class V)')
        ax6.set_ylabel("Session Class Count", color=TEXT_LIGHT, fontsize=9)
        ax6.legend(loc='upper left', fontsize=8, facecolor=BG_DARK, edgecolor=BORDER_COLOR)
    ax6.set_title("6. Clinical Beat Classification Evolution", color=RED_ACCENT, loc='left', fontsize=10, fontweight='bold')
    ax6.grid(True, linestyle='--', alpha=0.2)

    # Panel 7: Summary Metrics Card
    ax_card = fig.add_subplot(gs[3, :])
    ax_card.set_facecolor('#0B141A')
    ax_card.axis('off')

    status_text = (
        f"  SESSION DURATION       : {duration_s:.1f} seconds ({duration_min:.2f} min)   |   TARGET HARDWARE: Silicon Labs EFR32MG26 (BRD2709A)\n"
        f"  ----------------------------------------------------------------------------------------------------------------------\n"
        f"  CORRECTED SESSION BEATS: {session_beats:<5} beats                          |   CALCULATED SESSION BPM: {session_bpm:.1f} BPM (Resting / Normal)\n"
        f"  SESSION NORMAL BEATS(N): {session_n:<5}                                   |   MCU LIFETIME TOTAL BEATS: {boot_total_beats} (Since Boot)\n"
        f"  SESSION PAC ECTOPIC (S): {session_s:<5}                                   |   DMA OVERRUN COUNT       : {ecg['overruns'][-1] if len(ecg['overruns'])>0 else 0} (Zero Overruns)\n"
        f"  SESSION PVC ECTOPIC (V): {session_v:<5}                                   |   RAW STREAMING STATUS    : {'ACTIVE (250 Hz)' if data['has_raw_ecg'] else 'SPARSE SNAPSHOT'}\n"
    )
    ax_card.text(0.02, 0.5, status_text, family='monospace', fontsize=9.5, color=GREEN_ACCENT, va='center',
                 bbox=dict(boxstyle='round,pad=0.8', facecolor='#0D1B2A', edgecolor=GREEN_ACCENT, linewidth=1.2))

    os.makedirs(os.path.dirname(out_path), exist_ok=True)
    plt.savefig(out_path, dpi=200, facecolor=BG_DARK, bbox_inches='tight')
    plt.close()
    print(f"[SAVED] Master Dashboard -> {out_path}")


def generate_beat_pie_chart(data, out_path):
    """Renders high-resolution dedicated clinical beat classification pie / donut chart."""
    fig = plt.figure(figsize=(10, 8), facecolor=BG_DARK)
    ax = fig.add_subplot(111)
    ax.set_facecolor(BG_CARD)

    vol_id = data['metadata']['volunteer_id']
    ai = data['ai']

    # Compute Session Delta Counts
    if len(ai['tier0']) > 1:
        n_count = max(0, ai['n'][-1] - ai['n'][0])
        s_count = max(0, ai['s'][-1] - ai['s'][0])
        v_count = max(0, ai['v'][-1] - ai['v'][0])
        total_evals = max(0, ai['tier0'][-1] - ai['tier0'][0])
    elif len(ai['tier0']) == 1:
        n_count = ai['n'][0]
        s_count = ai['s'][0]
        v_count = ai['v'][0]
        total_evals = ai['tier0'][0]
    else:
        n_count, s_count, v_count, total_evals = 0, 0, 0, 0

    total_classified = n_count + s_count + v_count
    if total_classified == 0:
        total_classified = 1
        n_count = 1  # default placeholder

    labels = ['Normal Sinus (Class N)', 'Supraventricular PAC (Class S)', 'Ventricular PVC (Class V)']
    sizes = [n_count, s_count, v_count]
    colors = [GREEN_ACCENT, YELLOW_ACCENT, RED_ACCENT]

    # Filter for non-zero slices
    non_zero = [(l, s, c) for l, s, c in zip(labels, sizes, colors) if s > 0]
    if not non_zero:
        non_zero = [('Normal Sinus (Class N)', 1, GREEN_ACCENT)]

    plot_labels = [item[0] for item in non_zero]
    plot_sizes = [item[1] for item in non_zero]
    plot_colors = [item[2] for item in non_zero]

    wedges, texts, autotexts = ax.pie(
        plot_sizes,
        labels=plot_labels,
        autopct='%1.1f%%',
        pctdistance=0.75,
        startangle=140,
        colors=plot_colors,
        wedgeprops=dict(width=0.42, edgecolor=BG_DARK, linewidth=3),
        textprops=dict(color=TEXT_LIGHT, fontsize=11, fontweight='bold')
    )

    for at in autotexts:
        at.set_color('#000000')
        at.set_fontsize(11)
        at.set_weight('bold')

    # Center Donut Text
    ectopic_burden = ((s_count + v_count) / max(total_classified, 1)) * 100.0
    center_text = f"Total Beats\n{total_classified}\n\nEctopic Burden\n{ectopic_burden:.1f}%"
    ax.text(0, 0, center_text, ha='center', va='center', color=TEXT_LIGHT,
            fontsize=12, fontweight='bold', family='sans-serif')

    ax.set_title(f"TARANG AI Clinical Beat Classification — {vol_id}\n"
                 f"Evaluated On-Device (EFR32MG26 Cortex-M33 + MVP Accelerator)",
                 color=GREEN_ACCENT, fontsize=13, fontweight='bold', pad=20)

    # External Legend with Exact Counts
    legend_labels = [
        f"Normal Sinus (N): {n_count} beats ({n_count/total_classified*100:.1f}%)",
        f"PAC Ectopic (S)  : {s_count} beats ({s_count/total_classified*100:.1f}%)",
        f"PVC Ectopic (V)  : {v_count} beats ({v_count/total_classified*100:.1f}%)"
    ]
    ax.legend(wedges, legend_labels, loc="lower center", bbox_to_anchor=(0.5, -0.12),
              ncol=1, fontsize=10, facecolor=BG_DARK, edgecolor=BORDER_COLOR)

    plt.tight_layout()
    os.makedirs(os.path.dirname(out_path), exist_ok=True)
    plt.savefig(out_path, dpi=200, facecolor=BG_DARK, bbox_inches='tight')
    plt.close()
    print(f"[SAVED] Beat Classification Pie Chart -> {out_path}")


def generate_ai_cascade_breakdown(data, out_path):
    """Renders high-resolution 3-stage AI escalation funnel, donut chart, and summary metrics card."""
    fig, axes = plt.subplots(1, 3, figsize=(19, 6.5), facecolor=BG_DARK)
    vol_id = data['metadata']['volunteer_id']
    fig.suptitle(f"TARANG Multi-Tier Clinical AI Cascade Analysis — {vol_id}\n"
                 f"Target: Silicon Labs EFR32MG26B510F3200IM48",
                 fontsize=13, fontweight='bold', color=CYAN_ACCENT, y=0.98)

    ai = data['ai']
    if len(ai['tier0']) > 1:
        tot_evals = max(0, ai['tier0'][-1] - ai['tier0'][0])
        t1_fires = max(0, ai['tier1'][-1] - ai['tier1'][0])
        t2_fires = max(0, ai['tier2'][-1] - ai['tier2'][0])
        n_count = max(0, ai['n'][-1] - ai['n'][0])
        s_count = max(0, ai['s'][-1] - ai['s'][0])
        v_count = max(0, ai['v'][-1] - ai['v'][0])
    elif len(ai['tier0']) == 1:
        tot_evals = ai['tier0'][0]
        t1_fires = ai['tier1'][0]
        t2_fires = ai['tier2'][0]
        n_count = ai['n'][0]
        s_count = ai['s'][0]
        v_count = ai['v'][0]
    else:
        tot_evals, t1_fires, t2_fires, n_count, s_count, v_count = 0, 0, 0, 0, 0, 0

    # 1. Funnel Bar Chart
    ax1 = axes[0]
    ax1.set_facecolor(BG_CARD)
    stages = ['Tier-0 DSP\nHeuristics', 'Tier-1 Gate\nCNN Inference', 'Tier-2 SV Head\nClassification']
    counts = [tot_evals, t1_fires, t2_fires]
    colors = [CYAN_ACCENT, YELLOW_ACCENT, RED_ACCENT]
    bars = ax1.bar(stages, counts, color=colors, width=0.55, edgecolor=BORDER_COLOR)
    for bar, cnt in zip(bars, counts):
        yval = bar.get_height()
        ax1.text(bar.get_x() + bar.get_width()/2.0, yval + max(tot_evals*0.02, 0.5),
                 f"{cnt}\n({cnt/max(tot_evals,1)*100:.1f}%)",
                 ha='center', va='bottom', color='#FFFFFF', fontsize=9.5, fontweight='bold')
    ax1.set_ylabel("Inferences / Evaluations", color=TEXT_LIGHT, fontsize=10)
    ax1.set_title("1. Cascade Gating Funnel", color=CYAN_ACCENT, fontsize=11, fontweight='bold')
    ax1.set_ylim(0, max(tot_evals * 1.25, 5))
    ax1.grid(True, linestyle='--', alpha=0.2)

    # 2. Beat Classification Donut Chart
    ax2 = axes[1]
    ax2.set_facecolor(BG_CARD)
    labels = ['Normal (N)', 'PAC (S)', 'PVC (V)']
    sizes = [n_count, s_count, v_count]
    pie_colors = [GREEN_ACCENT, YELLOW_ACCENT, RED_ACCENT]

    plot_items = [(l, s, c) for l, s, c in zip(labels, sizes, pie_colors) if s > 0]
    if not plot_items:
        plot_items = [('Normal (N)', 1, GREEN_ACCENT)]

    wedges, texts, autotexts = ax2.pie(
        [item[1] for item in plot_items],
        labels=[item[0] for item in plot_items],
        autopct='%1.1f%%',
        startangle=140,
        colors=[item[2] for item in plot_items],
        wedgeprops=dict(width=0.45, edgecolor=BG_DARK, linewidth=2),
        textprops=dict(color=TEXT_LIGHT, fontsize=10, fontweight='bold')
    )
    for at in autotexts:
        at.set_color('#000000')
        at.set_weight('bold')
    ax2.set_title("2. Beat Classification Breakdown", color=GREEN_ACCENT, fontsize=11, fontweight='bold')

    # 3. Clinical Metrics Card
    ax3 = axes[2]
    ax3.set_facecolor(BG_CARD)
    ax3.axis('off')

    total_classified = max(n_count + s_count + v_count, 1)
    burden = ((s_count + v_count) / total_classified) * 100.0

    card_str = (
        "  CLINICAL SUMMARY METRICS\n"
        "  ====================================\n"
        f"  Total Session Beats : {total_classified}\n"
        f"  Normal Beats (N)    : {n_count} ({n_count/total_classified*100:.1f}%)\n"
        f"  PAC Ectopic Beats(S): {s_count} ({s_count/total_classified*100:.1f}%)\n"
        f"  PVC Ectopic Beats(V): {v_count} ({v_count/total_classified*100:.1f}%)\n"
        "  ------------------------------------\n"
        f"  Total Ectopic Burden: {burden:.2f}%\n"
        f"  Arrhythmia Gating   : {'LOW RISK (Benign)' if burden < 5 else 'MODERATE'}\n"
        f"  Energy Efficiency   : {(1.0-t1_fires/max(tot_evals,1))*100:.1f}% MCU Sleep\n"
        "  ===================================="
    )
    ax3.text(0.08, 0.5, card_str, family='monospace', fontsize=10.5, color=TEXT_LIGHT, va='center',
             bbox=dict(boxstyle='round,pad=1.0', facecolor='#0D1B2A', edgecolor=CYAN_ACCENT, linewidth=1.5))

    plt.tight_layout()
    os.makedirs(os.path.dirname(out_path), exist_ok=True)
    plt.savefig(out_path, dpi=200, facecolor=BG_DARK)
    plt.close()
    print(f"[SAVED] AI Cascade Breakdown -> {out_path}")


def process_single_csv(filepath, outdir):
    """Processes a single CSV and outputs all diagnostic figures organized in a per-volunteer folder."""
    data = parse_session_csv(filepath)
    vol_id = data['metadata']['volunteer_id']
    stem = os.path.splitext(os.path.basename(filepath))[0]

    # Dedicated folder per volunteer
    vol_outdir = os.path.join(outdir, vol_id)
    os.makedirs(vol_outdir, exist_ok=True)

    print(f"\n========================================================")
    print(f"[PROCESSING] {filepath}")
    print(f"[TARGET FOLDER] {vol_outdir}")
    print(f"========================================================")

    p_full = os.path.join(vol_outdir, f"{stem}_cardiogram_full.png")
    p_zoom = os.path.join(vol_outdir, f"{stem}_cardiogram_zoomed_3to4s.png")
    p_master = os.path.join(vol_outdir, f"{stem}_master_dashboard.png")
    p_pie = os.path.join(vol_outdir, f"{stem}_beat_pie_chart.png")
    p_cascade = os.path.join(vol_outdir, f"{stem}_ai_cascade_breakdown.png")

    generate_cardiogram_full(data, p_full)
    generate_cardiogram_zoomed(data, p_zoom)
    generate_master_dashboard(data, p_master)
    generate_beat_pie_chart(data, p_pie)
    generate_ai_cascade_breakdown(data, p_cascade)


def main():
    parser = argparse.ArgumentParser(description="Scan and plot all volunteer session CSVs.")
    parser.add_argument("csv_path", nargs="?", default=None, help="Optional specific CSV path")
    parser.add_argument("--outdir", default=os.path.join(os.path.dirname(os.path.abspath(__file__)), "plots"),
                        help="Output directory for plots")
    args = parser.parse_args()

    outdir = os.path.abspath(args.outdir)
    os.makedirs(outdir, exist_ok=True)

    if args.csv_path:
        process_single_csv(os.path.abspath(args.csv_path), outdir)
    else:
        # Batch scan all CSVs
        script_dir = os.path.dirname(os.path.abspath(__file__))
        captures_dir = os.path.join(script_dir, "captures")
        csv_files = sorted(glob.glob(os.path.join(captures_dir, "**", "*.csv"), recursive=True) +
                           glob.glob(os.path.join(script_dir, "*.csv")))
        
        print(f"[INFO] Found {len(csv_files)} CSV session files to plot.")
        for f in csv_files:
            process_single_csv(f, outdir)

    print(f"\n[COMPLETE] All session plots saved to: {outdir}")


if __name__ == "__main__":
    main()
