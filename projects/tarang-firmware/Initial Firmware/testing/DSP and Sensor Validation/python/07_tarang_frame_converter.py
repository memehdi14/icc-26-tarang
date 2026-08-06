#!/usr/bin/env python3
"""
07_tarang_frame_converter.py — Tarang Stage 11
Convert ESP32 CSV log into Tarang-firmware-compatible 256-sample frames.

Maps onto production types (see Tarang KB §6):
  - sensor_frame_matrix_t  : raw ECG frame + IMU accel frame
  - tarang_dsp_input_t     : raw ECG + IMU reference -> NLMS input
  - tarang_dsp_output_t    : clean_ecg[256] + ecg_snr + heart_rate_bpm + confidence
  - tarang_nlms_process_frame() : the NLMS entry point

Frame layout (matches production):
  - ECG frame length : 256 samples  (= TARANG_ECG_SAMPLES_PER_FRAME)
  - IMU samples per frame: 32       (= TARANG_NLMS_IMU_SAMPLES_PER_FRAME, 8:1 ratio)
  - Frame duration   : 256 / 250 = 1.024 s

Outputs:
    frames/frame_0001.csv     per-frame CSV with columns:
                                t_us, ecg_raw, ecg_clean, imu_mag, motion_gate, r_peak_flag
    frames/summary.json       per-frame metadata + Tarang-mapped fields

Usage:
    python3 07_tarang_frame_converter.py tarang_20250630_153000.csv

    python3 07_tarang_frame_converter.py tarang_20250630_153000.csv \\
           --combined-npz tarang_20250630_153000_combined_dsp.npz
"""
import sys, os, json, argparse
import numpy as np

from dsp import (dc_remove, baseline_wander_remove, bandpass, notch_50hz,
                 imu_magnitude, qrs_visibility_score)
from nlms import nlms_filter, motion_gate
from pan_tompkins import detect as pt_detect

ECG_HZ = 250
IMU_HZ = 100
ECG_FRAME = 256          # TARANG_ECG_SAMPLES_PER_FRAME
IMU_PER_FRAME = 32       # TARANG_NLMS_IMU_SAMPLES_PER_FRAME (8:1)

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('csv')
    ap.add_argument('--combined-npz', default=None,
                    help='Optional pre-computed combined_dsp.npz to skip re-DSP')
    ap.add_argument('--out-dir', default=None,
                    help='Output dir (default: <csv>_frames/)')
    args = ap.parse_args()

    if not os.path.exists(args.csv):
        print(f'Not found: {args.csv}'); return

    if args.combined_npz and os.path.exists(args.combined_npz):
        print(f'[Stage11] Loading pre-computed arrays from {args.combined_npz}')
        z = np.load(args.combined_npz, allow_pickle=False)
        t_us     = z['t_us']
        ecg_mv   = z['ecg_raw']
        ecg_clean= z['ecg_clean']
        imu_mag  = z['imu_mag']
        adapt_mask = z['adapt_mask']
        pt_clean_peaks = z['pt_clean_peaks'] if 'pt_clean_peaks' in z.files else None
    else:
        print(f'[Stage11] Loading CSV {args.csv} and running DSP from scratch')
        def _load_csv_robust(p):
            rows = []; header = None
            with open(p, 'r', encoding='ascii', errors='ignore') as f:
                for line in f:
                    s = line.strip()
                    if not s or s.startswith('#'):
                        continue
                    fields = s.split(',')
                    if header is None:
                        header = fields; continue
                    if len(fields) < 10: continue
                    try:
                        rows.append([float(x) for x in fields[:10]])
                    except ValueError:
                        continue
            arr = np.array(rows, dtype=np.float64)
            return arr
        arr = _load_csv_robust(args.csv)
        t_us    = arr[:, 0]
        ecg_mv  = arr[:, 4]
        ax      = arr[:, 5]
        ay      = arr[:, 6]
        az      = arr[:, 7]

        ecg_dc       = dc_remove(ecg_mv)
        ecg_baseline = baseline_wander_remove(ecg_dc, fs=ECG_HZ, cutoff=0.5)
        ecg_bp       = bandpass(ecg_baseline, fs=ECG_HZ, low=0.5, high=40.0)
        ecg_notch    = notch_50hz(ecg_bp, fs=ECG_HZ)
        imu_mag = imu_magnitude(ax, ay, az)
        from scipy.ndimage import uniform_filter1d
        imu_env = uniform_filter1d(imu_mag - 16384.0, size=25)
        adapt_mask = motion_gate(imu_mag, baseline=16384.0, threshold=300.0)
        r = nlms_filter(primary=ecg_notch, reference=imu_env,
                        num_taps=32, mu=0.01, eps=1.0,
                        adapt_mask=adapt_mask, verbose=False)
        ecg_clean = r['cleaned']
        pt = pt_detect(ecg_clean, fs=ECG_HZ, verbose=False)
        pt_clean_peaks = pt['r_peaks']

    # === Output directory ===
    out_dir = args.out_dir or args.csv.replace('.csv', '_frames')
    os.makedirs(out_dir, exist_ok=True)

    n_frames = len(ecg_mv) // ECG_FRAME
    print(f'[Stage11] Splitting {len(ecg_mv)} samples into {n_frames} frames of {ECG_FRAME}')

    r_peak_set = set(int(p) for p in pt_clean_peaks) if pt_clean_peaks is not None else set()

    summary = {
        'tarang_compatibility': {
            'ecg_frame_len': ECG_FRAME,
            'imu_per_frame': IMU_PER_FRAME,
            'ecg_hz': ECG_HZ,
            'imu_hz': IMU_HZ,
            'maps_to': [
                'sensor_frame_matrix_t',
                'tarang_dsp_input_t',
                'tarang_dsp_output_t',
                'tarang_nlms_process_frame()',
            ],
        },
        'frame_count': n_frames,
        'frames': [],
    }

    for fi in range(n_frames):
        s = fi * ECG_FRAME
        e = s + ECG_FRAME
        frame_raw = ecg_mv[s:e]
        frame_clean = ecg_clean[s:e]
        frame_imu = imu_mag[s:e]
        frame_adapt = adapt_mask[s:e]
        frame_t = t_us[s:e]

        # Subsample IMU to 32 samples per frame (matches production 8:1 ratio)
        imu_idx = np.linspace(0, len(frame_imu) - 1, IMU_PER_FRAME).astype(int)
        imu_32 = frame_imu[imu_idx]

        # Frame-level metrics
        p_raw = float(np.mean(frame_raw ** 2))
        p_clean = float(np.mean(frame_clean ** 2))
        snr_db = 10 * np.log10(p_raw / p_clean) if p_clean > 0 else 0.0
        motion_pct = 100.0 * float(np.sum(frame_adapt)) / ECG_FRAME
        q_vis = qrs_visibility_score(frame_clean, fs=ECG_HZ)

        # R-peaks in this frame (relative to frame start)
        r_peaks_in_frame = sorted([p - s for p in r_peak_set if s <= p < e])

        # Per-frame Pan-Tompkins on cleaned segment
        pt_f = pt_detect(frame_clean, fs=ECG_HZ, verbose=False)
        hr_bpm = float(pt_f['heart_rate'])

        # === Write per-frame CSV ===
        fpath = os.path.join(out_dir, f'frame_{fi+1:04d}.csv')
        with open(fpath, 'w') as f:
            f.write('t_us,ecg_raw,ecg_clean,imu_mag,motion_gate,r_peak_flag\n')
            for i in range(ECG_FRAME):
                rp = 1 if i in r_peaks_in_frame else 0
                f.write(f'{int(frame_t[i])},{frame_raw[i]:.4f},'
                        f'{frame_clean[i]:.4f},{int(frame_imu[i])},'
                        f'{1 if frame_adapt[i] else 0},{rp}\n')

        # === Add IMU 32-sample payload as a sidecar ===
        imu_path = os.path.join(out_dir, f'frame_{fi+1:04d}_imu32.csv')
        with open(imu_path, 'w') as f:
            f.write('imu_idx,imu_mag\n')
            for i, v in enumerate(imu_32):
                f.write(f'{i},{int(v)}\n')

        # === Summary entry ===
        summary['frames'].append({
            'frame_sequence': fi,
            'timestamp_start_us': int(frame_t[0]),
            'timestamp_end_us': int(frame_t[-1]),
            'duration_s': (frame_t[-1] - frame_t[0]) / 1e6,
            'ecg_quality': {
                'raw_rms_mv': float(np.sqrt(p_raw)),
                'clean_rms_mv': float(np.sqrt(p_clean)),
                'snr_db': snr_db,
                'qrs_visibility': q_vis,
            },
            'motion_quality': {
                'motion_pct': motion_pct,
                'imu_mean_mag': float(np.mean(frame_imu)),
                'imu_std_mag': float(np.std(frame_imu)),
            },
            'r_peaks': [int(p) for p in r_peaks_in_frame],
            'r_peak_count': len(r_peaks_in_frame),
            'heart_rate_bpm': hr_bpm,
            'confidence': _confidence(q_vis, motion_pct, len(r_peaks_in_frame)),
        })

        if fi < 3 or fi == n_frames - 1:
            print(f'  frame {fi:3d}  HR={hr_bpm:5.1f} bpm  '
                  f'motion={motion_pct:4.1f}%  R-peaks={len(r_peaks_in_frame)}  '
                  f'SNR={snr_db:+5.2f} dB  Q={q_vis:.2f}')

    out_json = os.path.join(out_dir, 'summary.json')
    with open(out_json, 'w') as f:
        json.dump(summary, f, indent=2)
    print(f'\n[Stage11] Wrote {n_frames} frames to {out_dir}/')
    print(f'[Stage11] Summary JSON -> {out_json}')
    print(f'[Stage11] Mapping to Tarang firmware:')
    print(f'           sensor_frame_matrix_t  <-- frame_XXXX.csv (raw+clean+imu)')
    print(f'           tarang_dsp_input_t     <-- raw ECG + imu32.csv')
    print(f'           tarang_dsp_output_t    <-- ecg_clean + snr_db + heart_rate_bpm')
    print(f'           tarang_nlms_process_frame() <-- the NLMS step that produced ecg_clean')

def _confidence(q_vis, motion_pct, n_peaks):
    """Heuristic 0..1 confidence score (NOT a clinical metric)."""
    if n_peaks == 0:
        return 0.0
    c_q = min(1.0, q_vis)
    c_motion = max(0.0, 1.0 - motion_pct / 100.0)
    c_peaks = min(1.0, n_peaks / 2.0)   # ~2 beats per 1.024 s frame
    return round(0.4 * c_q + 0.3 * c_motion + 0.3 * c_peaks, 3)

if __name__ == '__main__':
    main()
