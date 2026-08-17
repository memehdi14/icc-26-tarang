#!/usr/bin/env python3
"""
TARANG Single-Session Comprehensive Telemetry & AI Visualizer
============================================================
Generates deep-dive clinical visualizations from volunteer VCOM CSV captures:
1. Master Multi-Sensor Clinical Dashboard (ECG, IMU, Gyro, AI Cascade, Ectopic Burden)
2. Clinical AI Cascade & Arrhythmia Risk Profile (Funnel, Classification Pie, Burden Timeline)
3. IMU Biomechanical Motion & Posture Analysis (3-Axis Accel, Gyro, Vector Magnitude, Tilt)
"""

import os
import sys
import re
import csv
import argparse
import numpy as np
import matplotlib.pyplot as plt
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


def parse_volunteer_session(csv_path):
    """Extracts all metadata, telemetry streams, and AI events from a volunteer capture CSV."""
    metadata = {
        'volunteer_id': 'UNKNOWN',
        'date': 'N/A',
        'port': 'N/A',
        'cardiac_condition': 'N/A',
        'status': 'N/A'
    }
    
    times = []
    
    # ECG Telemetry
    ecg_t, ecg_total_samples, ecg_halves, ecg_overruns = [], [], [], []
    ecg_half0, ecg_half1 = [], []
    
    # IMU Telemetry
    imu_t, imu_samples = [], []
    imu_ax, imu_ay, imu_az = [], [], []
    imu_gx, imu_gy, imu_gz = [], [], []
    
    # AI Cascade Telemetry
    ai_t = []
    ai_tier0, ai_tier1, ai_tier2 = [], [], []
    ai_n, ai_s, ai_v = [], [], []
    
    # Discrete AI Events
    discrete_events = []

    with open(csv_path, 'r', encoding='utf-8', errors='replace') as f:
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

            raw = row[2].strip()

            # ECG Halves & Samples
            m_ecg = re.search(r'\[ECG\]\s+halves=(\d+)\s+total_samples=(\d+)\s+overruns=(\d+)', raw)
            if m_ecg:
                ecg_t.append(t_sec)
                ecg_halves.append(int(m_ecg.group(1)))
                ecg_total_samples.append(int(m_ecg.group(2)))
                ecg_overruns.append(int(m_ecg.group(3)))

            # ECG Half Buffer ADC values
            m_half = re.search(r'\[ECG\]\s+latest_half0=(\d+)\s+latest_half1=(\d+)', raw)
            if m_half:
                ecg_half0.append(int(m_half.group(1)))
                ecg_half1.append(int(m_half.group(2)))

            # IMU Samples & Status
            m_imu_s = re.search(r'\[IMU\]\s+samples=(\d+)\s+interrupts=(\d+)', raw)
            if m_imu_s:
                imu_t.append(t_sec)
                imu_samples.append(int(m_imu_s.group(1)))

            # IMU Accel
            m_accel = re.search(r'\[IMU\]\s+accel:\s+ax=([-\d]+)\s+ay=([-\d]+)\s+az=([-\d]+)', raw)
            if m_accel:
                imu_ax.append(int(m_accel.group(1)))
                imu_ay.append(int(m_accel.group(2)))
                imu_az.append(int(m_accel.group(3)))

            # IMU Gyro
            m_gyro = re.search(r'\[IMU\]\s+gyro:\s+gx=([-\d]+)\s+gy=([-\d]+)\s+gz=([-\d]+)', raw)
            if m_gyro:
                imu_gx.append(int(m_gyro.group(1)))
                imu_gy.append(int(m_gyro.group(2)))
                imu_gz.append(int(m_gyro.group(3)))

            # AI Counters
            m_ai1 = re.search(r'\[AI\]\s+tier0_evals=(\d+)\s+tier1_fires=(\d+)\s+tier2_fires=(\d+)', raw)
            if m_ai1:
                ai_t.append(t_sec)
                ai_tier0.append(int(m_ai1.group(1)))
                ai_tier1.append(int(m_ai1.group(2)))
                ai_tier2.append(int(m_ai1.group(3)))

            # AI Class Distribution
            m_ai2 = re.search(r'\[AI\]\s+class_n=(\d+)\s+class_s=(\d+)\s+class_v=(\d+)', raw)
            if m_ai2:
                ai_n.append(int(m_ai2.group(1)))
                ai_s.append(int(m_ai2.group(2)))
                ai_v.append(int(m_ai2.group(3)))

            # Discrete Tier-1 / Tier-2 Events
            if "[AI] TIER1" in raw:
                m_t1 = re.search(r'gate_prob(?:_x10k)?=([0-9.]+)\s+suspicious_reason=(\w+)', raw)
                if m_t1:
                    val = float(m_t1.group(1))
                    prob = val / 10000.0 if val > 1.0 else val
                    discrete_events.append({'t': t_sec, 'type': 'TIER1', 'prob': prob, 'reason': m_t1.group(2)})
            elif "[AI] TIER2" in raw:
                m_t2 = re.search(r'p_v(?:_x10k)?=([0-9.]+)\s+p_s(?:_x10k)?=([0-9.]+)\s+beat_class=(\w)', raw)
                if m_t2:
                    v_val = float(m_t2.group(1))
                    s_val = float(m_t2.group(2))
                    pv = v_val / 10000.0 if v_val > 1.0 else v_val
                    ps = s_val / 10000.0 if s_val > 1.0 else s_val
                    discrete_events.append({'t': t_sec, 'type': 'TIER2', 'p_v': pv, 'p_s': ps, 'cls': m_t2.group(3)})

    return {
        'metadata': metadata,
        'filename': os.path.basename(csv_path),
        'ecg': {
            't': np.array(ecg_t),
            'total_samples': np.array(ecg_total_samples),
            'halves': np.array(ecg_halves),
            'overruns': np.array(ecg_overruns),
            'half0': np.array(ecg_half0),
            'half1': np.array(ecg_half1)
        },
        'imu': {
            't': np.array(imu_t),
            'samples': np.array(imu_samples),
            'ax': np.array(imu_ax) / 16384.0,  # Convert to g (+-2g range)
            'ay': np.array(imu_ay) / 16384.0,
            'az': np.array(imu_az) / 16384.0,
            'gx': np.array(imu_gx) / 131.0,    # Convert to deg/s (+-250 dps range)
            'gy': np.array(imu_gy) / 131.0,
            'gz': np.array(imu_gz) / 131.0
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


def generate_master_clinical_dashboard(data, out_path):
    """Renders a 6-panel comprehensive clinical dashboard."""
    fig = plt.figure(figsize=(18, 14), facecolor=BG_DARK)
    gs = gridspec.GridSpec(4, 2, height_ratios=[1, 1, 1, 1], width_ratios=[1, 1], figure=fig, hspace=0.35, wspace=0.22)

    vol_id = data['metadata']['volunteer_id']
    date = data['metadata']['date']
    cond = data['metadata']['cardiac_condition']
    
    fig.suptitle(f"TARANG CLINICAL INTELLIGENCE PLATFORM — Session Report: {vol_id}\n"
                 f"Recorded: {date} | Condition: {cond} | Hardware: TARANG-EFR32xG24 v2.0",
                 fontsize=14, fontweight='bold', color=GREEN_ACCENT, y=0.98)

    # ─────────────────────────────────────────────────────────────
    # Panel 1: ECG Stream Throughput & Sampling Stability
    # ─────────────────────────────────────────────────────────────
    ax1 = fig.add_subplot(gs[0, 0])
    ax1.set_facecolor(BG_CARD)
    ecg = data['ecg']
    if len(ecg['t']) > 1:
        t_ecg = ecg['t'] - ecg['t'][0]
        # Calculate instantaneous sampling rate
        dt = np.diff(t_ecg)
        ds = np.diff(ecg['total_samples'])
        valid_dt = dt > 0.05
        fs_inst = np.where(valid_dt, ds / np.maximum(dt, 0.001), 250.0)
        
        ax1.plot(t_ecg, ecg['total_samples'] - ecg['total_samples'][0], color=GREEN_ACCENT, linewidth=1.8, label='Cumulative Samples')
        ax1.set_ylabel("Total Samples Processed", color=GREEN_ACCENT, fontsize=9)
        ax1_twin = ax1.twinx()
        ax1_twin.plot(t_ecg[1:], fs_inst, color=CYAN_ACCENT, linestyle=':', alpha=0.7, label='Inst. Sampling Rate (Hz)')
        ax1_twin.axhline(250.0, color='#888888', linestyle='--', alpha=0.5, label='Target Fs (250 Hz)')
        ax1_twin.set_ylabel("Rate (Hz)", color=CYAN_ACCENT, fontsize=9)
        ax1_twin.set_ylim(200, 300)
    ax1.set_title("1. ECG DMA Stream Throughput & 250 Hz Clock Stability", color=GREEN_ACCENT, loc='left', fontsize=10, fontweight='bold')
    ax1.grid(True, linestyle='--', alpha=0.2)
    ax1.tick_params(colors=TEXT_MUTED)

    # ─────────────────────────────────────────────────────────────
    # Panel 2: ECG ADC Potential Tracking (Buffer Snapshots)
    # ─────────────────────────────────────────────────────────────
    ax2 = fig.add_subplot(gs[0, 1])
    ax2.set_facecolor(BG_CARD)
    if len(ecg['half0']) > 0:
        t_adc = ecg['t'][:len(ecg['half0'])] - ecg['t'][0]
        v_half0 = (ecg['half0'] / 4095.0) * 3300.0  # mV
        v_half1 = (ecg['half1'] / 4095.0) * 3300.0  # mV
        ax2.plot(t_adc, v_half0, color='#00E676', marker='o', markersize=3, linewidth=1.2, label='DMA Half-0 ADC (mV)')
        ax2.plot(t_adc, v_half1, color='#76FF03', marker='s', markersize=3, linewidth=1.2, label='DMA Half-1 ADC (mV)')
        ax2.set_ylabel("Electrode Voltage (mV)", color=TEXT_LIGHT, fontsize=9)
        ax2.legend(loc='upper right', fontsize=8, facecolor=BG_DARK, edgecolor=BORDER_COLOR)
    ax2.set_title("2. Analog Front-End Potential Snapshot (12-bit ADC / 3.3V)", color=GREEN_ACCENT, loc='left', fontsize=10, fontweight='bold')
    ax2.grid(True, linestyle='--', alpha=0.2)
    ax2.tick_params(colors=TEXT_MUTED)

    # ─────────────────────────────────────────────────────────────
    # Panel 3: IMU 3-Axis Accelerometer (Motion & Posture)
    # ─────────────────────────────────────────────────────────────
    ax3 = fig.add_subplot(gs[1, 0])
    ax3.set_facecolor(BG_CARD)
    imu = data['imu']
    if len(imu['t']) > 0:
        t_imu = imu['t'] - imu['t'][0]
        ax3.plot(t_imu, imu['ax'], color='#00E676', label='Accel X (Lateral)', alpha=0.85)
        ax3.plot(t_imu, imu['ay'], color=YELLOW_ACCENT, label='Accel Y (Vertical / Gravity)', alpha=0.85)
        ax3.plot(t_imu, imu['az'], color=PURPLE_ACCENT, label='Accel Z (Anterior-Posterior)', alpha=0.85)
        
        # Magnitude
        mag = np.sqrt(imu['ax']**2 + imu['ay']**2 + imu['az']**2)
        ax3.plot(t_imu, mag, color='#FFFFFF', linestyle='--', linewidth=1.2, label='|a| Magnitude (g)', alpha=0.9)
        ax3.set_ylabel("Acceleration (g)", color=TEXT_LIGHT, fontsize=9)
        ax3.legend(loc='upper right', fontsize=8, facecolor=BG_DARK, edgecolor=BORDER_COLOR, ncol=2)
    ax3.set_title("3. Biomechanical Accelerometer (3-Axis Posture & Motion Artifacts)", color=YELLOW_ACCENT, loc='left', fontsize=10, fontweight='bold')
    ax3.grid(True, linestyle='--', alpha=0.2)
    ax3.tick_params(colors=TEXT_MUTED)

    # ─────────────────────────────────────────────────────────────
    # Panel 4: IMU 3-Axis Gyroscope (Rotational Velocity)
    # ─────────────────────────────────────────────────────────────
    ax4 = fig.add_subplot(gs[1, 1])
    ax4.set_facecolor(BG_CARD)
    if len(imu['t']) > 0:
        t_imu = imu['t'] - imu['t'][0]
        ax4.plot(t_imu, imu['gx'], color='#FF5252', label='Gyro X (Pitch °/s)', alpha=0.85)
        ax4.plot(t_imu, imu['gy'], color='#448AFF', label='Gyro Y (Roll °/s)', alpha=0.85)
        ax4.plot(t_imu, imu['gz'], color='#E040FB', label='Gyro Z (Yaw °/s)', alpha=0.85)
        ax4.set_ylabel("Rotational Velocity (°/s)", color=TEXT_LIGHT, fontsize=9)
        ax4.legend(loc='upper right', fontsize=8, facecolor=BG_DARK, edgecolor=BORDER_COLOR, ncol=3)
    ax4.set_title("4. Gyroscopic Stability (Tremor & Torso Rotational Velocity)", color='#448AFF', loc='left', fontsize=10, fontweight='bold')
    ax4.grid(True, linestyle='--', alpha=0.2)
    ax4.tick_params(colors=TEXT_MUTED)

    # ─────────────────────────────────────────────────────────────
    # Panel 5: AI Cascade Progression (Tier-0 -> Tier-1 -> Tier-2)
    # ─────────────────────────────────────────────────────────────
    ax5 = fig.add_subplot(gs[2, 0])
    ax5.set_facecolor(BG_CARD)
    ai = data['ai']
    if len(ai['t']) > 0:
        t_ai = ai['t'] - ai['t'][0]
        ax5.plot(t_ai, ai['tier0'], color=CYAN_ACCENT, linewidth=2.0, label='Tier-0 Evaluated Beats')
        ax5.plot(t_ai, ai['tier1'], color=YELLOW_ACCENT, linewidth=2.0, label='Tier-1 Gate Inferences')
        ax5.plot(t_ai, ai['tier2'], color=RED_ACCENT, linewidth=2.0, label='Tier-2 SV Head Inferences')
        ax5.set_ylabel("Cumulative Beat Count", color=TEXT_LIGHT, fontsize=9)
        ax5.legend(loc='upper left', fontsize=8, facecolor=BG_DARK, edgecolor=BORDER_COLOR)
    ax5.set_title("5. 3-Tier AI Escalation Cascade Execution Profile", color=CYAN_ACCENT, loc='left', fontsize=10, fontweight='bold')
    ax5.grid(True, linestyle='--', alpha=0.2)
    ax5.tick_params(colors=TEXT_MUTED)

    # ─────────────────────────────────────────────────────────────
    # Panel 6: Clinical Beat Distribution & Ectopic Burden %
    # ─────────────────────────────────────────────────────────────
    ax6 = fig.add_subplot(gs[2, 1])
    ax6.set_facecolor(BG_CARD)
    if len(ai['t']) > 0 and len(ai['n']) > 0:
        t_ai = ai['t'] - ai['t'][0]
        total_beats = np.maximum(ai['n'] + ai['s'] + ai['v'], 1)
        burden_pct = ((ai['s'] + ai['v']) / total_beats) * 100.0

        ax6.plot(t_ai, ai['n'], color=GREEN_ACCENT, linewidth=1.8, label='Normal Beats (Class N)')
        ax6.plot(t_ai, ai['s'], color=YELLOW_ACCENT, linewidth=1.8, label='Supraventricular PAC (Class S)')
        ax6.plot(t_ai, ai['v'], color=RED_ACCENT, linewidth=1.8, label='Ventricular PVC (Class V)')
        ax6.set_ylabel("Class Count", color=TEXT_LIGHT, fontsize=9)
        
        ax6_twin = ax6.twinx()
        ax6_twin.plot(t_ai, burden_pct, color=PURPLE_ACCENT, linestyle='--', linewidth=1.5, label='Ectopic Burden %')
        ax6_twin.set_ylabel("Burden (%)", color=PURPLE_ACCENT, fontsize=9)
        ax6_twin.set_ylim(0, max(15.0, np.max(burden_pct) * 1.5))
        
        ax6.legend(loc='upper left', fontsize=8, facecolor=BG_DARK, edgecolor=BORDER_COLOR)
        ax6_twin.legend(loc='upper right', fontsize=8, facecolor=BG_DARK, edgecolor=BORDER_COLOR)
    ax6.set_title("6. Clinical Arrhythmia Burden & Classification Evolution", color=RED_ACCENT, loc='left', fontsize=10, fontweight='bold')
    ax6.grid(True, linestyle='--', alpha=0.2)
    ax6.tick_params(colors=TEXT_MUTED)

    # ─────────────────────────────────────────────────────────────
    # Panel 7 & 8 (Bottom Span): Summary Metrics Card & Timeline
    # ─────────────────────────────────────────────────────────────
    ax_card = fig.add_subplot(gs[3, :])
    ax_card.set_facecolor('#0B141A')
    ax_card.axis('off')

    # Compute key stats
    tot_evals = ai['tier0'][-1] if len(ai['tier0']) > 0 else 0
    t1_fires = ai['tier1'][-1] if len(ai['tier1']) > 0 else 0
    t2_fires = ai['tier2'][-1] if len(ai['tier2']) > 0 else 0
    n_count = ai['n'][-1] if len(ai['n']) > 0 else 0
    s_count = ai['s'][-1] if len(ai['s']) > 0 else 0
    v_count = ai['v'][-1] if len(ai['v']) > 0 else 0
    
    total_classified = n_count + s_count + v_count
    burden = ((s_count + v_count) / max(total_classified, 1)) * 100.0
    energy_saved = (1.0 - (t1_fires / max(tot_evals, 1))) * 100.0
    
    status_text = (
        f"  SESSION DURATION: {ecg['t'][-1]-ecg['t'][0]:.1f}s   |   TOTAL ECG SAMPLES: {ecg['total_samples'][-1]-ecg['total_samples'][0] if len(ecg['total_samples'])>0 else 0}   |   DMA OVERRUNS: {ecg['overruns'][-1] if len(ecg['overruns'])>0 else 0}\n"
        f"  ----------------------------------------------------------------------------------------------------------------------\n"
        f"  TOTAL BEATS EVALUATED : {tot_evals:<5}   |   NORMAL BEATS (N)        : {n_count:<5} ({n_count/max(total_classified,1)*100:.1f}%)\n"
        f"  TIER-1 GATE CNN FIRES  : {t1_fires:<5}   |   SUPRAVENTRICULAR PAC (S): {s_count:<5} ({s_count/max(total_classified,1)*100:.1f}%)\n"
        f"  TIER-2 SV HEAD FIRES   : {t2_fires:<5}   |   VENTRICULAR PVC (V)     : {v_count:<5} ({v_count/max(total_classified,1)*100:.1f}%)\n"
        f"  ----------------------------------------------------------------------------------------------------------------------\n"
        f"  CASCADE ENERGY EFFICIENCY : {energy_saved:.1f}% AI MCU SLEEP (Tier-1 called on only {100-energy_saved:.1f}% of beats)\n"
        f"  CLINICAL ECTOPIC BURDEN   : {burden:.2f}% (Status: {'BENIGN / LOW RISK' if burden < 5.0 else 'ELEVATED BURDEN — CLINICAL REVIEW RECOMMENDED'})\n"
    )
    
    ax_card.text(0.02, 0.5, status_text, family='monospace', fontsize=9.5, color=GREEN_ACCENT, va='center',
                 bbox=dict(boxstyle='round,pad=0.8', facecolor='#0D1B2A', edgecolor=GREEN_ACCENT, linewidth=1.2))

    plt.tight_layout()
    os.makedirs(os.path.dirname(out_path), exist_ok=True)
    plt.savefig(out_path, dpi=200, facecolor=BG_DARK)
    plt.close()
    print(f"[SAVED] Master Clinical Dashboard -> {out_path}")


def generate_ai_cascade_breakdown(data, out_path):
    """Renders high-res AI cascade funnel, pie chart, and classification metrics."""
    fig, axes = plt.subplots(1, 3, figsize=(18, 6), facecolor=BG_DARK)
    fig.suptitle(f"TARANG Multi-Tier Clinical AI Cascade Analysis — {data['metadata']['volunteer_id']}",
                 fontsize=14, fontweight='bold', color=CYAN_ACCENT, y=0.98)

    ai = data['ai']
    tot_evals = ai['tier0'][-1] if len(ai['tier0']) > 0 else 0
    t1_fires = ai['tier1'][-1] if len(ai['tier1']) > 0 else 0
    t2_fires = ai['tier2'][-1] if len(ai['tier2']) > 0 else 0
    n_count = ai['n'][-1] if len(ai['n']) > 0 else 0
    s_count = ai['s'][-1] if len(ai['s']) > 0 else 0
    v_count = ai['v'][-1] if len(ai['v']) > 0 else 0

    # 1. Funnel Bar Chart
    ax1 = axes[0]
    ax1.set_facecolor(BG_CARD)
    stages = ['Tier-0 DSP\nHeuristics', 'Tier-1 Gate\nCNN Inference', 'Tier-2 SV Head\nClassification']
    counts = [tot_evals, t1_fires, t2_fires]
    colors = [CYAN_ACCENT, YELLOW_ACCENT, RED_ACCENT]
    bars = ax1.bar(stages, counts, color=colors, width=0.55, edgecolor=BORDER_COLOR)
    for bar, cnt in zip(bars, counts):
        yval = bar.get_height()
        ax1.text(bar.get_x() + bar.get_width()/2.0, yval + max(tot_evals*0.02, 1), f"{cnt}\n({cnt/max(tot_evals,1)*100:.1f}%)",
                 ha='center', va='bottom', color='#FFFFFF', fontsize=9, fontweight='bold')
    ax1.set_ylabel("Inferences / Evaluations", color=TEXT_LIGHT, fontsize=10)
    ax1.set_title("Cascade Execution Gating Funnel", color=CYAN_ACCENT, fontsize=11, fontweight='bold')
    ax1.set_ylim(0, tot_evals * 1.25)
    ax1.grid(True, linestyle='--', alpha=0.2)

    # 2. Beat Classification Donut Chart
    ax2 = axes[1]
    ax2.set_facecolor(BG_CARD)
    labels = ['Normal (N)', 'PAC (S)', 'PVC (V)']
    sizes = [n_count, s_count, v_count]
    pie_colors = [GREEN_ACCENT, YELLOW_ACCENT, RED_ACCENT]
    
    # Filter non-zero
    plot_labels = [l for l, s in zip(labels, sizes) if s > 0]
    plot_sizes = [s for s in sizes if s > 0]
    plot_colors = [c for c, s in zip(pie_colors, sizes) if s > 0]

    wedges, texts, autotexts = ax2.pie(plot_sizes, labels=plot_labels, autopct='%1.1f%%',
                                       startangle=140, colors=plot_colors,
                                       wedgeprops=dict(width=0.45, edgecolor=BG_DARK, linewidth=2),
                                       textprops=dict(color=TEXT_LIGHT, fontsize=10))
    for at in autotexts:
        at.set_color('#000000')
        at.set_weight('bold')
    ax2.set_title("Clinical Beat Classification Breakdown", color=GREEN_ACCENT, fontsize=11, fontweight='bold')

    # 3. Clinical Metrics Card
    ax3 = axes[2]
    ax3.set_facecolor(BG_CARD)
    ax3.axis('off')
    
    total_classified = max(n_count + s_count + v_count, 1)
    burden = ((s_count + v_count) / total_classified) * 100.0
    
    card_str = (
        "  CLINICAL SUMMARY METRICS\n"
        "  ====================================\n"
        f"  Total Heart Beats   : {total_classified}\n"
        f"  Normal Beats (N)    : {n_count} ({n_count/total_classified*100:.1f}%)\n"
        f"  PAC Ectopic Beats(S): {s_count} ({s_count/total_classified*100:.1f}%)\n"
        f"  PVC Ectopic Beats(V): {v_count} ({v_count/total_classified*100:.1f}%)\n"
        "  ------------------------------------\n"
        f"  Total Ectopic Burden: {burden:.2f}%\n"
        f"  Arrhythmia Gating   : {'LOW RISK' if burden < 5 else 'MODERATE'}\n"
        f"  Energy Efficiency   : {(1.0-t1_fires/max(tot_evals,1))*100:.1f}% Sleep\n"
        "  ===================================="
    )
    ax3.text(0.1, 0.5, card_str, family='monospace', fontsize=11, color=TEXT_LIGHT, va='center',
             bbox=dict(boxstyle='round,pad=1.0', facecolor='#0D1B2A', edgecolor=CYAN_ACCENT, linewidth=1.5))

    plt.tight_layout()
    os.makedirs(os.path.dirname(out_path), exist_ok=True)
    plt.savefig(out_path, dpi=200, facecolor=BG_DARK)
    plt.close()
    print(f"[SAVED] AI Cascade Breakdown -> {out_path}")


def generate_imu_dynamics_plot(data, out_path):
    """Renders 3-axis IMU biomechanics, pitch/roll tilt angles, and angular velocity."""
    fig, axes = plt.subplots(3, 1, figsize=(16, 10), facecolor=BG_DARK, sharex=True)
    fig.suptitle(f"TARANG Biomechanical Motion & Posture Telemetry — {data['metadata']['volunteer_id']}",
                 fontsize=14, fontweight='bold', color=YELLOW_ACCENT, y=0.98)

    imu = data['imu']
    if len(imu['t']) == 0:
        return

    t = imu['t'] - imu['t'][0]

    # 1. 3-Axis Acceleration
    ax1 = axes[0]
    ax1.set_facecolor(BG_CARD)
    ax1.plot(t, imu['ax'], color='#00E676', label='Lateral (ax)', alpha=0.9)
    ax1.plot(t, imu['ay'], color=YELLOW_ACCENT, label='Vertical/Gravity (ay)', alpha=0.9)
    ax1.plot(t, imu['az'], color=PURPLE_ACCENT, label='Anterior-Posterior (az)', alpha=0.9)
    ax1.set_ylabel("Accel (g)", color=TEXT_LIGHT, fontsize=9)
    ax1.legend(loc='upper right', fontsize=8, facecolor=BG_DARK, edgecolor=BORDER_COLOR)
    ax1.set_title("1. Linear Acceleration Vector Components", color=YELLOW_ACCENT, loc='left', fontsize=10, fontweight='bold')
    ax1.grid(True, linestyle='--', alpha=0.2)

    # 2. Calculated Tilt Angles (Pitch & Roll)
    ax2 = axes[1]
    ax2.set_facecolor(BG_CARD)
    # Estimate pitch and roll from gravity vector
    pitch = np.arctan2(imu['ax'], np.sqrt(imu['ay']**2 + imu['az']**2)) * 180.0 / np.pi
    roll = np.arctan2(imu['az'], np.sqrt(imu['ax']**2 + imu['ay']**2)) * 180.0 / np.pi
    ax2.plot(t, pitch, color='#00E5FF', label='Pitch Angle (°)', linewidth=1.5)
    ax2.plot(t, roll, color='#FF4081', label='Roll Angle (°)', linewidth=1.5)
    ax2.set_ylabel("Angle (°)", color=TEXT_LIGHT, fontsize=9)
    ax2.legend(loc='upper right', fontsize=8, facecolor=BG_DARK, edgecolor=BORDER_COLOR)
    ax2.set_title("2. Patient Posture & Torso Tilt Tracking", color='#00E5FF', loc='left', fontsize=10, fontweight='bold')
    ax2.grid(True, linestyle='--', alpha=0.2)

    # 3. 3-Axis Gyroscope Angular Velocity
    ax3 = axes[2]
    ax3.set_facecolor(BG_CARD)
    ax3.plot(t, imu['gx'], color='#FF5252', label='Pitch Rate (gx)', alpha=0.85)
    ax3.plot(t, imu['gy'], color='#448AFF', label='Roll Rate (gy)', alpha=0.85)
    ax3.plot(t, imu['gz'], color='#E040FB', label='Yaw Rate (gz)', alpha=0.85)
    ax3.set_ylabel("Angular Velocity (°/s)", color=TEXT_LIGHT, fontsize=9)
    ax3.set_xlabel("Elapsed Time (s)", color=TEXT_LIGHT, fontsize=10)
    ax3.legend(loc='upper right', fontsize=8, facecolor=BG_DARK, edgecolor=BORDER_COLOR)
    ax3.set_title("3. Rotational Velocity Dynamics", color='#FF5252', loc='left', fontsize=10, fontweight='bold')
    ax3.grid(True, linestyle='--', alpha=0.2)

    plt.tight_layout()
    os.makedirs(os.path.dirname(out_path), exist_ok=True)
    plt.savefig(out_path, dpi=200, facecolor=BG_DARK)
    plt.close()
    print(f"[SAVED] IMU Dynamics Plot -> {out_path}")


def main():
    parser = argparse.ArgumentParser(description="Plot comprehensive volunteer session telemetry & AI metrics.")
    parser.add_argument("csv_path", nargs="?", default=r"c:\MMDPublic\Hackathons\TeamOcelleon\projects\tarang-dsp\integration_validation\captures\KEDARFINALTEST\KEDARFINALTEST_20260816_114314.csv",
                        help="Path to volunteer capture CSV")
    parser.add_argument("--outdir", default=r"c:\MMDPublic\Hackathons\TeamOcelleon\projects\tarang-dsp\integration_validation\plots",
                        help="Output directory for generated plots")
    args = parser.parse_args()

    csv_path = os.path.abspath(args.csv_path)
    outdir = os.path.abspath(args.outdir)

    print(f"[INFO] Parsing volunteer session: {csv_path}")
    data = parse_volunteer_session(csv_path)
    
    vol_id = data['metadata']['volunteer_id']
    stem = os.path.splitext(os.path.basename(csv_path))[0]

    p1 = os.path.join(outdir, f"{stem}_master_dashboard.png")
    p2 = os.path.join(outdir, f"{stem}_ai_cascade_breakdown.png")
    p3 = os.path.join(outdir, f"{stem}_imu_dynamics.png")

    generate_master_clinical_dashboard(data, p1)
    generate_ai_cascade_breakdown(data, p2)
    generate_imu_dynamics_plot(data, p3)

    print(f"\n[DONE] All visualizations successfully generated in {outdir}")


if __name__ == "__main__":
    main()
