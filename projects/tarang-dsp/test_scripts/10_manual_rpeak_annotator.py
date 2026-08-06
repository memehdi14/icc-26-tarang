#!/usr/bin/env python3
"""
10_manual_rpeak_annotator.py — Tarang DSP Finalization Item B

Manual R-peak annotation tool. Click on the ECG plot where you see R-peaks.
Saves labels to CSV for comparison with Pan-Tompkins.

Usage:
    python 10_manual_rpeak_annotator.py tarang_20260702_133137.csv --start 60 --duration 60

Controls:
    Left click  : add R-peak label
    Right click : remove nearest label
    's'         : save labels to CSV
    'q'         : quit (also saves)

Output:
    manual_labels.csv  with columns: sample_idx, time_s
"""
import sys, os, argparse
import numpy as np
import matplotlib.pyplot as plt

ECG_HZ = 250

def load_csv(path):
    rows = []; header = None
    with open(path, 'r', encoding='ascii', errors='ignore') as f:
        for line in f:
            s = line.strip()
            if not s or s.startswith('#'): continue
            fields = s.split(',')
            if header is None: header = fields; continue
            if len(fields) < 10: continue
            try: rows.append([float(x) for x in fields[:10]])
            except ValueError: continue
    arr = np.array(rows, dtype=np.float64)
    return arr

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('csv')
    ap.add_argument('--start', type=int, default=60, help='start time in seconds')
    ap.add_argument('--duration', type=int, default=60, help='window duration in seconds')
    ap.add_argument('--output', default='manual_labels.csv')
    args = ap.parse_args()

    arr = load_csv(args.csv)
    t_us = arr[:,0]; ecg_mv = arr[:,4]

    s = args.start * ECG_HZ
    e = min(s + args.duration * ECG_HZ, len(arr))
    t_show = (t_us[s:e] - t_us[s]) / 1000.0
    ecg_show = ecg_mv[s:e]

    # Simple bandpass for display clarity
    from scipy.signal import butter, filtfilt
    b, a = butter(2, [0.5/(ECG_HZ/2), 40.0/(ECG_HZ/2)], btype='band')
    ecg_filt = filtfilt(b, a, ecg_show - np.mean(ecg_show))

    fig, ax = plt.subplots(figsize=(16, 6))
    ax.plot(t_show, ecg_filt, lw=0.7, color='navy')
    ax.set_xlabel('Time (ms)'); ax.set_ylabel('ECG (mV, filtered)')
    ax.set_title(f'Manual R-peak annotation — {args.duration}s window starting at {args.start}s\n'
                 f'Left-click: add R-peak | Right-click: remove nearest | "s": save | "q": quit')
    ax.grid(alpha=0.3); ax.axhline(0, color='k', lw=0.5)

    labels = []  # list of (sample_idx_absolute, time_ms)

    def onclick(event):
        if event.inaxes != ax: return
        if event.xdata is None: return
        t_ms = event.xdata
        sample_idx = s + int(t_ms * ECG_HZ / 1000.0)
        if event.button == 1:  # left click
            # refine: find local max within ±25 ms
            w = int(ECG_HZ * 0.025)
            lo = max(0, sample_idx - s - w); hi = min(len(ecg_filt), sample_idx - s + w + 1)
            if hi > lo:
                local_max = lo + int(np.argmax(ecg_filt[lo:hi]))
                sample_idx = s + local_max
                t_ms = (t_us[sample_idx] - t_us[s]) / 1000.0
            labels.append((sample_idx, t_ms))
            ax.plot(t_ms, ecg_filt[sample_idx - s], 'rv', ms=10)
            ax.set_title(f'Manual R-peak annotation — {len(labels)} labels | '
                         f'Left-click: add | Right-click: remove | "s": save | "q": quit')
            plt.draw()
        elif event.button == 3:  # right click
            if not labels: return
            dists = [abs(l[1] - t_ms) for l in labels]
            nearest = np.argmin(dists)
            if dists[nearest] < 100:  # within 100 ms
                removed = labels.pop(nearest)
                ax.lines = [l for l in ax.lines if not (
                    hasattr(l, '_manual_label') and
                    abs(l.get_xdata()[0] - removed[1]) < 1)]
                # redraw all label markers
                ax.lines = [l for l in ax.lines if not getattr(l, '_is_manual', False)]
                for lab in labels:
                    line, = ax.plot(lab[1], ecg_filt[lab[0] - s], 'rv', ms=10)
                    line._is_manual = True
                ax.set_title(f'Manual R-peak annotation — {len(labels)} labels | '
                             f'Left-click: add | Right-click: remove | "s": save | "q": quit')
                plt.draw()

    def onkey(event):
        if event.key == 's':
            save_labels()
        elif event.key == 'q':
            save_labels()
            plt.close(fig)

    def save_labels():
        if not labels:
            print('No labels to save')
            return
        labels_sorted = sorted(labels, key=lambda x: x[0])
        with open(args.output, 'w') as f:
            f.write('sample_idx,time_s\n')
            for sidx, tms in labels_sorted:
                f.write(f'{sidx},{sidx/ECG_HZ:.4f}\n')
        print(f'Saved {len(labels_sorted)} manual labels to {args.output}')

    fig.canvas.mpl_connect('button_press_event', onclick)
    fig.canvas.mpl_connect('key_press_event', onkey)
    plt.show()

if __name__ == '__main__':
    main()
