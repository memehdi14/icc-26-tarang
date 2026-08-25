#!/usr/bin/env python3
"""
Zoom in on a 5-second ECG segment and a single P-QRS-T beat from a TARANG capture.
"""

import sys
import os
from pathlib import Path
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np

# Local imports
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from vcom_stream import VCOMTelemetryStream, ECGFrame, BeatEvent
from scipy.signal import butter, sosfilt

def main():
    csv_path = Path("projects/tarang-dsp/integration_validation/captures/KEDARDEMO/KEDARDEMO_ecg_20260825_203106.csv")
    if not csv_path.exists():
        print(f"File not found: {csv_path}")
        return

    stream = VCOMTelemetryStream(replay_file=str(csv_path))
    stream.open()

    timestamps = []
    raw_samples = []
    beats = []

    for line in stream.stream_lines():
        ecg_frames, _, _, beat, _, _ = stream.parse_line(line)
        if ecg_frames:
            for f in ecg_frames:
                timestamps.append(f.timestamp_ms / 1000.0)
                raw_samples.append(f.raw_adc)
        if beat:
            beats.append((beat.timestamp_ms / 1000.0, beat.hr_bpm))

    t = np.array(timestamps)
    raw = np.array(raw_samples)
    if len(t) == 0:
        print("No ECG samples found!")
        return

    # Relative time from 0
    t_rel = t - t[0]

    # Apply 0.5 - 40 Hz 4th order Butterworth bandpass + baseline removal
    fs = 250.0
    nyq = fs / 2.0
    sos_bp = butter(4, [0.5 / nyq, 40.0 / nyq], btype="band", output="sos")
    clean = sosfilt(sos_bp, raw - np.mean(raw))

    # Pick a clean 5-second window (e.g. t = 95.0s to 100.0s)
    t_start = 95.0
    t_end = 100.0
    idx_5s = (t_rel >= t_start) & (t_rel <= t_end)

    if not np.any(idx_5s):
        # Fallback to middle 5 seconds
        mid = t_rel[-1] / 2.0
        t_start = mid - 2.5
        t_end = mid + 2.5
        idx_5s = (t_rel >= t_start) & (t_rel <= t_end)

    t_5s = t_rel[idx_5s]
    clean_5s = clean[idx_5s]
    raw_5s = raw[idx_5s]

    # Find the highest R-peak in this 5-second window
    peaks_in_window = [b for b in beats if t_start <= (b[0] - t[0]) <= t_end]
    
    # Locate one prominent R-peak in the middle of this window for single beat view
    max_idx_5s = np.argmax(clean_5s[125:-125]) + 125
    r_peak_time = t_5s[max_idx_5s]
    
    # 0.8s single-beat window centered on R-peak (-0.3s to +0.5s)
    idx_beat = (t_rel >= (r_peak_time - 0.3)) & (t_rel <= (r_peak_time + 0.5))
    t_beat = t_rel[idx_beat] - r_peak_time  # Centered at 0 (ms)
    t_beat_ms = t_beat * 1000.0
    clean_beat = clean[idx_beat]

    # Plot
    fig, axes = plt.subplots(2, 1, figsize=(12, 8), gridspec_kw={'height_ratios': [1.2, 1.5]})
    fig.patch.set_facecolor('#0f172a')

    # Top Plot: 5-Second Zoom Window
    ax0 = axes[0]
    ax0.set_facecolor('#1e293b')
    ax0.plot(t_5s - t_5s[0], clean_5s, color='#38bdf8', lw=1.8, label='Cleaned ECG (0.5–40 Hz)')
    ax0.set_title("5-Second Zoomed ECG Segment (Consecutive Heartbeats @ 250 Hz)", color='#f8fafc', fontsize=13, pad=10, weight='bold')
    ax0.set_xlabel("Time in Window (seconds)", color='#94a3b8', fontsize=10)
    ax0.set_ylabel("Amplitude (Counts)", color='#94a3b8', fontsize=10)
    ax0.tick_params(colors='#94a3b8')
    ax0.grid(True, color='#334155', alpha=0.6, linestyle='--')
    ax0.axvspan(r_peak_time - t_5s[0] - 0.3, r_peak_time - t_5s[0] + 0.5, color='#f59e0b', alpha=0.25, label='Single Beat Zoomed Below')
    ax0.legend(facecolor='#1e293b', edgecolor='#475569', labelcolor='#f8fafc', loc='upper right')

    # Bottom Plot: Single Beat P-QRS-T Anatomy Close-up
    ax1 = axes[1]
    ax1.set_facecolor('#1e293b')
    ax1.plot(t_beat_ms, clean_beat, color='#4ade80', lw=2.4, label='Single Beat Morphology')
    ax1.set_title("Single Cardiac Cycle: High-Resolution P-QRS-T Complex Anatomy", color='#f8fafc', fontsize=13, pad=10, weight='bold')
    ax1.set_xlabel("Time Relative to R-Peak (milliseconds)", color='#94a3b8', fontsize=10)
    ax1.set_ylabel("Amplitude (Counts)", color='#94a3b8', fontsize=10)
    ax1.tick_params(colors='#94a3b8')
    ax1.grid(True, color='#334155', alpha=0.6, linestyle='--')

    # Annotate P, Q, R, S, T components
    r_val = clean_beat[np.argmin(np.abs(t_beat_ms))]
    ax1.scatter([0], [r_val], color='#ef4444', s=100, zorder=5)
    ax1.annotate('R-Peak\n(Ventricular Depol)', xy=(0, r_val), xytext=(0, r_val + (r_val*0.15 if r_val>0 else 200)),
                 arrowprops=dict(facecolor='#ef4444', shrink=0.08, width=1.5, headwidth=6),
                 color='#ef4444', weight='bold', ha='center', fontsize=10)

    # Q point (dip before R)
    q_mask = (t_beat_ms >= -80) & (t_beat_ms <= -10)
    if np.any(q_mask):
        q_idx = np.argmin(clean_beat[q_mask])
        q_time = t_beat_ms[q_mask][q_idx]
        q_val = clean_beat[q_mask][q_idx]
        ax1.scatter([q_time], [q_val], color='#f59e0b', s=60, zorder=5)
        ax1.annotate('Q', xy=(q_time, q_val), xytext=(q_time - 25, q_val - 150),
                     arrowprops=dict(facecolor='#f59e0b', shrink=0.08, width=1, headwidth=5),
                     color='#f59e0b', weight='bold', ha='center')

    # S point (dip after R)
    s_mask = (t_beat_ms >= 10) & (t_beat_ms <= 90)
    if np.any(s_mask):
        s_idx = np.argmin(clean_beat[s_mask])
        s_time = t_beat_ms[s_mask][s_idx]
        s_val = clean_beat[s_mask][s_idx]
        ax1.scatter([s_time], [s_val], color='#f59e0b', s=60, zorder=5)
        ax1.annotate('S', xy=(s_time, s_val), xytext=(s_time + 25, s_val - 150),
                     arrowprops=dict(facecolor='#f59e0b', shrink=0.08, width=1, headwidth=5),
                     color='#f59e0b', weight='bold', ha='center')

    # P wave (bump before QRS: -220ms to -100ms)
    p_mask = (t_beat_ms >= -240) & (t_beat_ms <= -90)
    if np.any(p_mask):
        p_idx = np.argmax(clean_beat[p_mask])
        p_time = t_beat_ms[p_mask][p_idx]
        p_val = clean_beat[p_mask][p_idx]
        ax1.scatter([p_time], [p_val], color='#38bdf8', s=60, zorder=5)
        ax1.annotate('P-Wave\n(Atrial Depol)', xy=(p_time, p_val), xytext=(p_time, p_val + 200),
                     arrowprops=dict(facecolor='#38bdf8', shrink=0.08, width=1, headwidth=5),
                     color='#38bdf8', weight='bold', ha='center', fontsize=9)

    # T wave (bump after QRS: +120ms to +350ms)
    t_mask = (t_beat_ms >= 110) & (t_beat_ms <= 380)
    if np.any(t_mask):
        t_idx = np.argmax(clean_beat[t_mask])
        t_time = t_beat_ms[t_mask][t_idx]
        t_val = clean_beat[t_mask][t_idx]
        ax1.scatter([t_time], [t_val], color='#c084fc', s=60, zorder=5)
        ax1.annotate('T-Wave\n(Ventricular Repol)', xy=(t_time, t_val), xytext=(t_time, t_val + 200),
                     arrowprops=dict(facecolor='#c084fc', shrink=0.08, width=1, headwidth=5),
                     color='#c084fc', weight='bold', ha='center', fontsize=9)

    plt.tight_layout()
    out_dir = Path("projects/tarang-dsp/integration_validation/plots/KEDARDEMO/latest")
    out_dir.mkdir(parents=True, exist_ok=True)
    out_img = out_dir / "single_beat_zoom.png"
    plt.savefig(out_img, dpi=150, facecolor=fig.get_facecolor(), edgecolor='none')
    plt.close()
    print(f"[SUCCESS] Saved single beat zoomed plot to: {out_img}")

if __name__ == "__main__":
    main()
