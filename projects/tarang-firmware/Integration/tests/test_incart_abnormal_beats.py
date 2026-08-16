#!/usr/bin/env python3
"""
Test Gate & SV Head on INCART — Detailed Per-Beat Analysis
==========================================================
Addresses three specific concerns:
1. Per-beat classification outcome for Normal beats that leak past Gate
2. Full P(V) range/max across all Class S beats (PAC→PVC misclass risk)
3. INCART lead selection and sample rate confirmation
"""

import sys, numpy as np, tensorflow as tf
from pathlib import Path
import wfdb
from scipy import signal

if sys.stdout.encoding != 'utf-8':
    sys.stdout.reconfigure(encoding='utf-8', errors='replace')
if sys.stderr.encoding != 'utf-8':
    sys.stderr.reconfigure(encoding='utf-8', errors='replace')

GATE_MODEL_PATH = "gate_int8.tflite"
SV_MODEL_PATH   = "sv_int8.tflite"
INCART_DIR      = Path(os.environ.get("INCART_DIR", str(Path(__file__).resolve().parents[4] / "dataset" / "incartdb")))

# Scaler values from training (Tarang_v15_FINAL_SUBMISSION.ipynb)
RR_MEAN  = np.array([800.359, 796.738, 57.817, 79.819], dtype=np.float32)
RR_SCALE = np.array([206.590, 180.936, 92.441, 22.106], dtype=np.float32)

# Thresholds from thresholds.h
GATE_THR = 0.25
V_THR    = 0.60
S_THR    = 0.35

AAMI_MAP = {
    'N':'N','L':'N','R':'N','e':'N','j':'N',
    'A':'S','a':'S','J':'S','S':'S',
    'V':'V','E':'V',
}

def q8(val, scale, zp):
    return np.clip(np.round(val / scale).astype(np.int32) + zp, -128, 127).astype(np.int8)

def dq8(qval, scale, zp):
    return (qval.astype(np.float32) - zp) * scale


def main():
    # ── Confirm INCART metadata ──────────────────────────────────────────
    hea = (INCART_DIR / "I01.hea").read_text()
    lines = hea.strip().split('\n')
    rec_line = lines[0].split()
    native_fs = int(rec_line[2])
    lead_names = [l.split()[-1] for l in lines[1:13]]
    print("=" * 72)
    print("INCART DATABASE METADATA VERIFICATION")
    print("=" * 72)
    print(f"  Native sample rate:  {native_fs} Hz")
    print(f"  Lead order (cols 0–11): {lead_names}")
    print(f"  Column 0 used in test: '{lead_names[0]}'")
    print(f"  Resampling applied:    {native_fs} → 250 Hz (factor {250/native_fs:.6f})")
    print()

    # ── Load models ──────────────────────────────────────────────────────
    gate_interp = tf.lite.Interpreter(model_path=GATE_MODEL_PATH)
    gate_interp.allocate_tensors()
    gi, go = gate_interp.get_input_details(), gate_interp.get_output_details()

    sv_interp = tf.lite.Interpreter(model_path=SV_MODEL_PATH)
    sv_interp.allocate_tensors()
    si, so = sv_interp.get_input_details(), sv_interp.get_output_details()

    # ── Collect beats ────────────────────────────────────────────────────
    collected = {'N': [], 'S': [], 'V': []}
    target = 50

    for recno in range(1, 76):
        rec_name = f"I{recno:02d}"
        if not (INCART_DIR / f"{rec_name}.hea").exists():
            continue
        try:
            record = wfdb.rdrecord(str(INCART_DIR / rec_name))
            ann    = wfdb.rdann(str(INCART_DIR / rec_name), 'atr')
            fs     = record.fs

            lead1 = record.p_signal[:, 0]  # Column 0 = Lead I
            n250  = int(len(lead1) * 250.0 / fs)
            lead1_250 = signal.resample(lead1, n250)

            b, a = signal.butter(4, [0.5/125, 40.0/125], btype='bandpass')
            morph = signal.lfilter(b, a, lead1_250)

            locs250 = (np.array(ann.sample) * 250.0 / fs).astype(int)
            syms    = ann.symbol

            for idx in range(5, len(locs250) - 2):
                sym = syms[idx]
                if sym not in AAMI_MAP:
                    continue
                cls = AAMI_MAP[sym]
                if len(collected[cls]) >= target:
                    continue

                ploc = locs250[idx]
                if ploc < 65 or ploc + 65 > len(morph):
                    continue

                w = morph[ploc-65:ploc+65].astype(np.float32)
                sd = np.std(w)
                if sd < 1e-4:
                    continue
                w_norm = (w - np.mean(w)) / sd

                rr_intervals = np.diff(locs250[idx-5:idx+1]) * (1000.0/250.0)
                rr_raw  = np.array([rr_intervals[-1],
                                    np.mean(rr_intervals),
                                    np.std(rr_intervals),
                                    60000.0/np.mean(rr_intervals)], dtype=np.float32)
                rr_norm = (rr_raw - RR_MEAN) / RR_SCALE

                collected[cls].append((w_norm, rr_norm, sym, rec_name, idx))
        except Exception:
            continue

        if all(len(collected[c]) >= target for c in ['N','S','V']):
            break

    print("=" * 72)
    print("COLLECTED BEATS")
    print("=" * 72)
    for c in ['N','S','V']:
        print(f"  Class {c}: {len(collected[c])} beats")
    print()

    # ── Run inference and collect per-beat detail ────────────────────────
    results = {}  # cls -> list of (gate_p, pv, ps, sym, rec, idx)

    for cls in ['N','S','V']:
        results[cls] = []
        for w_norm, rr_norm, sym, rec, idx in collected[cls]:
            # Gate
            gate_interp.set_tensor(gi[0]['index'],
                q8(rr_norm, gi[0]['quantization'][0], gi[0]['quantization'][1]).reshape(1,4))
            gate_interp.set_tensor(gi[1]['index'],
                q8(w_norm, gi[1]['quantization'][0], gi[1]['quantization'][1]).reshape(1,130,1))
            gate_interp.invoke()
            gp = dq8(gate_interp.get_tensor(go[0]['index'])[0,0],
                      go[0]['quantization'][0], go[0]['quantization'][1])

            # SV Head
            sv_interp.set_tensor(si[0]['index'],
                q8(rr_norm, si[0]['quantization'][0], si[0]['quantization'][1]).reshape(1,4))
            sv_interp.set_tensor(si[1]['index'],
                q8(w_norm, si[1]['quantization'][0], si[1]['quantization'][1]).reshape(1,130,1))
            sv_interp.invoke()
            pv = dq8(sv_interp.get_tensor(so[0]['index'])[0,0],
                      so[0]['quantization'][0], so[0]['quantization'][1])
            ps = dq8(sv_interp.get_tensor(so[1]['index'])[0,0],
                      so[1]['quantization'][0], so[1]['quantization'][1])

            results[cls].append((float(gp), float(pv), float(ps), sym, rec, idx))

    # ── CONCERN 1: Normal beats that leak past Gate ─────────────────────
    print("=" * 72)
    print("CONCERN 1: Normal beats that cross GATE_THR > 0.25")
    print("  (What does SV Head classify them as?)")
    print("=" * 72)
    n_leaks = [(gp, pv, ps, sym, rec, idx)
               for gp, pv, ps, sym, rec, idx in results['N'] if gp > GATE_THR]
    if not n_leaks:
        print("  No Normal beats leaked past Gate in this run.")
    else:
        print(f"  {len(n_leaks)} Normal beat(s) leaked past Gate:\n")
        print(f"  {'Rec':>6}  {'Sym':>4}  {'Gate_P':>8}  {'P(V)':>8}  {'P(S)':>8}  {'Pipeline Decision':>20}")
        print(f"  {'---':>6}  {'---':>4}  {'------':>8}  {'----':>8}  {'----':>8}  {'------------------':>20}")
        for gp, pv, ps, sym, rec, idx in n_leaks:
            if pv > V_THR:
                decision = "CLASS V (FALSE PVC!)"
            elif ps > S_THR:
                decision = "CLASS S (FALSE PAC!)"
            else:
                decision = "CLASS N (correct)"
            print(f"  {rec:>6}  {sym:>4}  {gp:>8.4f}  {pv:>8.4f}  {ps:>8.4f}  {decision:>20}")
        n_false_pac = sum(1 for gp,pv,ps,_,_,_ in n_leaks if pv <= V_THR and ps > S_THR)
        n_false_pvc = sum(1 for gp,pv,ps,_,_,_ in n_leaks if pv > V_THR)
        print(f"\n  Summary: {n_false_pac} false PAC, {n_false_pvc} false PVC, "
              f"{len(n_leaks)-n_false_pac-n_false_pvc} correctly rejected as N")
        print(f"  Overall Normal false-alarm rate: {len(n_leaks)}/{len(results['N'])} "
              f"= {len(n_leaks)/len(results['N'])*100:.1f}% reach SV Head, "
              f"{n_false_pac+n_false_pvc}/{len(results['N'])} "
              f"= {(n_false_pac+n_false_pvc)/len(results['N'])*100:.1f}% misclassified")

    # ── CONCERN 2: Class S tail — max P(V) ──────────────────────────────
    print()
    print("=" * 72)
    print("CONCERN 2: Class S (PAC) — full P(V) distribution")
    print("  (Any PAC beat with P(V) > 0.60 gets misclassified as PVC)")
    print("=" * 72)
    s_pvs = np.array([pv for _, pv, _, _, _, _ in results['S']])
    s_pss = np.array([ps for _, _, ps, _, _, _ in results['S']])
    print(f"  P(V) across {len(s_pvs)} PAC beats:")
    print(f"    Mean:   {np.mean(s_pvs):.4f}")
    print(f"    Median: {np.median(s_pvs):.4f}")
    print(f"    Min:    {np.min(s_pvs):.4f}")
    print(f"    Max:    {np.max(s_pvs):.4f}")
    print(f"    Std:    {np.std(s_pvs):.4f}")
    above_vthr = sum(1 for pv in s_pvs if pv > V_THR)
    print(f"  PAC beats with P(V) > {V_THR}: {above_vthr}/{len(s_pvs)} "
          f"({above_vthr/len(s_pvs)*100:.1f}%)")

    if above_vthr > 0:
        print(f"\n  *** MISCLASSIFIED PAC→PVC BEATS: ***")
        for gp, pv, ps, sym, rec, idx in results['S']:
            if pv > V_THR:
                print(f"    {rec} beat#{idx} sym={sym}: Gate={gp:.4f} P(V)={pv:.4f} P(S)={ps:.4f}")

    print(f"\n  P(S) across {len(s_pss)} PAC beats:")
    print(f"    Mean:   {np.mean(s_pss):.4f}")
    print(f"    Median: {np.median(s_pss):.4f}")
    print(f"    Min:    {np.min(s_pss):.4f}")
    print(f"    Max:    {np.max(s_pss):.4f}")

    # Pipeline classification for Class S
    s_correct = sum(1 for gp,pv,ps,_,_,_ in results['S']
                    if gp > GATE_THR and pv <= V_THR and ps > S_THR)
    s_as_pvc  = sum(1 for gp,pv,ps,_,_,_ in results['S']
                    if gp > GATE_THR and pv > V_THR)
    s_missed_gate = sum(1 for gp,_,_,_,_,_ in results['S'] if gp <= GATE_THR)
    s_as_n    = sum(1 for gp,pv,ps,_,_,_ in results['S']
                    if gp > GATE_THR and pv <= V_THR and ps <= S_THR)
    print(f"\n  Full pipeline classification of {len(results['S'])} PAC beats:")
    print(f"    Correctly classified as S: {s_correct}")
    print(f"    Misclassified as V (PVC):  {s_as_pvc}")
    print(f"    Misclassified as N (Gate filtered): {s_missed_gate}")
    print(f"    Passed Gate but fell below S_THR:   {s_as_n}")

    # ── CONCERN 3: Class V full stats (already good, confirm) ───────────
    print()
    print("=" * 72)
    print("FULL CLASS V (PVC) STATS — for completeness")
    print("=" * 72)
    v_pvs = np.array([pv for _, pv, _, _, _, _ in results['V']])
    v_pss = np.array([ps for _, _, ps, _, _, _ in results['V']])
    v_gps = np.array([gp for gp, _, _, _, _, _ in results['V']])
    print(f"  Gate P(abn): mean={np.mean(v_gps):.4f}, min={np.min(v_gps):.4f}, max={np.max(v_gps):.4f}")
    print(f"  P(V):  mean={np.mean(v_pvs):.4f}, min={np.min(v_pvs):.4f}, max={np.max(v_pvs):.4f}")
    print(f"  P(S):  mean={np.mean(v_pss):.4f}, min={np.min(v_pss):.4f}, max={np.max(v_pss):.4f}")
    v_correct = sum(1 for gp,pv,ps,_,_,_ in results['V']
                    if gp > GATE_THR and pv > V_THR)
    print(f"  Correctly classified as V: {v_correct}/{len(results['V'])}")

    # ── Summary table ───────────────────────────────────────────────────
    print()
    print("=" * 72)
    print("END-TO-END PIPELINE CONFUSION MATRIX (50 beats per class)")
    print("=" * 72)
    print(f"  {'True Class':>12}  {'→ N':>6}  {'→ S':>6}  {'→ V':>6}  {'Recall':>8}")
    print(f"  {'----------':>12}  {'----':>6}  {'----':>6}  {'----':>6}  {'------':>8}")

    for cls in ['N','S','V']:
        n_n = sum(1 for gp,pv,ps,_,_,_ in results[cls]
                  if gp <= GATE_THR or (pv <= V_THR and ps <= S_THR))
        n_s = sum(1 for gp,pv,ps,_,_,_ in results[cls]
                  if gp > GATE_THR and pv <= V_THR and ps > S_THR)
        n_v = sum(1 for gp,pv,ps,_,_,_ in results[cls]
                  if gp > GATE_THR and pv > V_THR)
        total = len(results[cls])
        correct = {'N': n_n, 'S': n_s, 'V': n_v}[cls]
        print(f"  {cls:>12}  {n_n:>6}  {n_s:>6}  {n_v:>6}  {correct/total*100:>7.1f}%")


if __name__ == "__main__":
    main()
