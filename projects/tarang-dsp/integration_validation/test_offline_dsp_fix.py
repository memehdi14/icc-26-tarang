#!/usr/bin/env python3
"""
Test updated Pan-Tompkins with 360ms refractory & 0.45x slope threshold against KEDARDEMO capture.
"""

import sys
import os
from pathlib import Path
import numpy as np
from scipy.signal import butter, sosfilt

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from vcom_stream import VCOMTelemetryStream

def main():
    csv_path = Path("projects/tarang-dsp/integration_validation/captures/KEDARDEMO/KEDARDEMO_ecg_20260825_203106.csv")
    stream = VCOMTelemetryStream(replay_file=str(csv_path))
    stream.open()

    raw_samples = []
    for line in stream.stream_lines():
        ecg_frames, _, _, _, _, _ = stream.parse_line(line)
        if ecg_frames:
            for f in ecg_frames:
                raw_samples.append(f.raw_adc)

    raw = np.array(raw_samples, dtype=float)
    fs = 250.0
    duration_s = len(raw) / fs

    # 1. 0.5 - 40 Hz Butterworth Bandpass
    nyq = fs / 2.0
    sos_bp = butter(4, [0.5 / nyq, 40.0 / nyq], btype="band", output="sos")
    y_filt = sosfilt(sos_bp, raw - np.mean(raw))

    # 2. QRS Bandpass (5 - 15 Hz)
    sos_qrs = butter(2, [5.0 / nyq, 15.0 / nyq], btype="band", output="sos")
    y_qrs = sosfilt(sos_qrs, y_filt)

    # 3. 5-point Derivative: y[n] = (1/8T) * (2*x[n] + x[n-1] - x[n-3] - 2*x[n-4])
    deriv = np.diff(y_qrs, prepend=y_qrs[0])

    # 4. Squaring
    sq = deriv ** 2

    # 5. MWI (38 samples = 152 ms)
    mwi_kernel = np.ones(38) / 38.0
    mwi = np.convolve(sq, mwi_kernel, mode="same")

    # 6. Adaptive Threshold with 360ms refractory backstop
    refr_samples = int(0.360 * fs)  # 90 samples
    spki = np.max(mwi[:int(8*fs)]) * 0.5
    npki = np.mean(mwi[:int(8*fs)])
    th1 = npki + 0.25 * (spki - npki)

    detected_peaks = []
    last_r_idx = -refr_samples

    for i in range(1, len(mwi) - 1):
        if mwi[i] > mwi[i-1] and mwi[i] >= mwi[i+1]:
            peak_val = mwi[i]
            if (i - last_r_idx) < refr_samples:
                continue
            if peak_val > th1:
                detected_peaks.append(i)
                last_r_idx = i
                spki = 0.125 * peak_val + 0.875 * spki
            else:
                npki = 0.125 * peak_val + 0.875 * npki
            th1 = npki + 0.25 * (spki - npki)

    num_beats = len(detected_peaks)
    bpm = (num_beats / duration_s) * 60.0

    print("=" * 60)
    print("  OFFLINE DSP RE-EVALUATION WITH 360ms REFRACTORY")
    print("=" * 60)
    print(f"  Duration          : {duration_s:.1f} s")
    print(f"  Total Samples     : {len(raw)}")
    print(f"  Detected R-Peaks  : {num_beats} beats")
    print(f"  Calculated HR     : {bpm:.1f} BPM")
    print("=" * 60)

if __name__ == "__main__":
    main()
