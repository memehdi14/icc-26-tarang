#!/usr/bin/env python3
"""Full-resolution TARANG post-hoc telemetry viewer.

Loads every firmware @S/@I/@P/@B record without resampling or decimation.
All rows share the device timestamp axis. Press n/p to move between flagged
events and a to restore the complete session.
"""

from __future__ import annotations

import argparse
import csv
import html
import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Iterable
import webbrowser

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np


BEAT_NAMES = np.array(["N", "S", "V", "Q"])
BEAT_COLORS = np.array(["#707780", "#d97706", "#dc2626", "#111827"])
RHYTHM_COLORS = {
    0x01: ("AFib", "#7c3aed"),
    0x02: ("Tachy", "#ef4444"),
    0x04: ("Brady", "#2563eb"),
    0x08: ("Bigeminy", "#f97316"),
    0x10: ("Trigeminy", "#eab308"),
    0x20: ("V-run", "#b91c1c"),
    0x40: ("SVT-run", "#db2777"),
    0x80: ("VT suspected", "#450a0a"),
}


@dataclass
class Session:
    sample: list[list[float]] = field(default_factory=list)
    imu: list[list[float]] = field(default_factory=list)
    ppg: list[list[float]] = field(default_factory=list)
    beat: list[list[float]] = field(default_factory=list)

    def arrays(self) -> dict[str, np.ndarray]:
        widths = {"sample": 9, "imu": 9, "ppg": 5, "beat": 15}
        return {
            name: np.asarray(getattr(self, name), dtype=float).reshape(-1, width)
            for name, width in widths.items()
        }


def _numbers(fields: list[str], expected: int) -> list[float] | None:
    if len(fields) != expected:
        return None
    try:
        return [float(value) for value in fields]
    except ValueError:
        return None


def parse_telemetry_line(line: str, session: Session) -> bool:
    line = line.strip()
    if not line.startswith("@") or line.startswith("@SCHEMA"):
        return False

    fields = line.split(",")
    record_type = fields[0]
    destinations = {
        "@S": (session.sample, 9),
        "@I": (session.imu, 9),
        "@P": (session.ppg, 5),
        "@B": (session.beat, 15),
    }
    if record_type not in destinations:
        return False

    destination, width = destinations[record_type]
    values = _numbers(fields[1:], width)
    if values is None:
        return False
    destination.append(values)
    return True


def iter_log_lines(path: Path) -> Iterable[str]:
    with path.open("r", encoding="utf-8", errors="replace", newline="") as handle:
        first = handle.readline()
        handle.seek(0)
        if "raw_line" in first:
            reader = csv.DictReader(handle)
            for row in reader:
                yield row.get("raw_line", "")
        else:
            yield from handle


def load_session(path: Path) -> Session:
    session = Session()
    malformed = 0
    telemetry_lines = 0
    for line in iter_log_lines(path):
        if line.lstrip().startswith("@"):
            telemetry_lines += 1
            if not parse_telemetry_line(line, session) and "@SCHEMA" not in line:
                malformed += 1

    arrays = session.arrays()
    if arrays["sample"].size == 0:
        raise ValueError(
            "No @S records found. Flash a TARANG_DEBUG_TELEMETRY build and "
            "capture it with log_vcom.py."
        )
    if malformed:
        print(f"[WARN] Ignored {malformed} malformed telemetry records")
    if telemetry_lines == 0:
        raise ValueError("The file contains no TARANG telemetry records")
    return session


def _relative_seconds(values_ms: np.ndarray, origin_ms: float) -> np.ndarray:
    return (values_ms - origin_ms) / 1000.0


def _line_with_gaps(
    time_s: np.ndarray,
    values: np.ndarray,
    valid: np.ndarray,
    expected_period_s: float,
) -> tuple[np.ndarray, np.ndarray]:
    if time_s.size == 0:
        return time_s, values
    gaps = np.flatnonzero(np.diff(time_s) > expected_period_s * 1.75) + 1
    invalid = np.flatnonzero(~valid.astype(bool))
    break_at = np.unique(np.concatenate((gaps, invalid)))
    if break_at.size == 0:
        return time_s, values
    return np.insert(time_s, break_at, np.nan), np.insert(values, break_at, np.nan)


def _shade_intervals(ax, time_s: np.ndarray, mask: np.ndarray, color: str, alpha: float):
    if time_s.size == 0 or not np.any(mask):
        return
    changes = np.diff(np.r_[False, mask.astype(bool), False].astype(np.int8))
    starts = np.flatnonzero(changes == 1)
    ends = np.flatnonzero(changes == -1) - 1
    for start, end in zip(starts, ends):
        right = time_s[end]
        if end + 1 < time_s.size:
            right = time_s[end + 1]
        ax.axvspan(time_s[start], right, color=color, alpha=alpha, linewidth=0)


def _motion_mask(imu: np.ndarray) -> np.ndarray:
    if imu.size == 0:
        return np.empty(0, dtype=bool)
    magnitude = np.linalg.norm(imu[:, 3:6], axis=1)
    baseline_count = min(magnitude.size, 1000)
    baseline = np.median(magnitude[:baseline_count])
    mad = np.median(np.abs(magnitude[:baseline_count] - baseline))
    threshold = max(6.0 * 1.4826 * mad, 250.0)
    return (np.abs(magnitude - baseline) > threshold) & (imu[:, 2] > 0)


def _rhythm_bands(ax, beat_time: np.ndarray, flags: np.ndarray):
    if beat_time.size == 0:
        return
    for bit, (label, color) in RHYTHM_COLORS.items():
        mask = (flags.astype(np.uint8) & bit) != 0
        if np.any(mask):
            _shade_intervals(ax, beat_time, mask, color, 0.12)
            ax.plot([], [], color=color, linewidth=6, alpha=0.35, label=label)


class EventNavigator:
    def __init__(self, figure, axes, event_times: np.ndarray, full_limits: tuple[float, float]):
        self.figure = figure
        self.axes = axes
        self.event_times = event_times
        self.full_limits = full_limits
        self.index = -1
        figure.canvas.mpl_connect("key_press_event", self.on_key)

    def on_key(self, event):
        if event.key == "a":
            self.axes[-1].set_xlim(*self.full_limits)
        elif event.key in {"n", "p"} and self.event_times.size:
            step = 1 if event.key == "n" else -1
            self.index = (self.index + step) % self.event_times.size
            center = self.event_times[self.index]
            self.axes[-1].set_xlim(center - 5.0, center + 5.0)
            print(
                f"[EVENT] {self.index + 1}/{self.event_times.size} "
                f"at {center:.3f} s"
            )
        else:
            return
        self.figure.canvas.draw_idle()


def build_figure(session: Session, title: str):
    data = session.arrays()
    sample, imu, ppg, beat = (
        data["sample"], data["imu"], data["ppg"], data["beat"]
    )
    timestamp_sets = [values[:, 0] for values in (sample, imu, ppg, beat) if values.size]
    origin_ms = min(values[0] for values in timestamp_sets)

    ts = _relative_seconds(sample[:, 0], origin_ms)
    ti = _relative_seconds(imu[:, 0], origin_ms) if imu.size else np.empty(0)
    tb = _relative_seconds(beat[:, 0], origin_ms) if beat.size else np.empty(0)

    plt.rcParams["path.simplify"] = False
    plt.rcParams["agg.path.chunksize"] = 0
    figure, axes = plt.subplots(
        4, 1, sharex=True, figsize=(16, 10),
        gridspec_kw={"height_ratios": [1.2, 1.5, 1.0, 1.0]},
    )
    figure.canvas.manager.set_window_title("TARANG validation")
    figure.suptitle(title, fontsize=13)

    raw_t, raw_y = _line_with_gaps(ts, sample[:, 2], sample[:, 8] > 0, 0.004)
    axes[0].plot(raw_t, raw_y, color="#20262e", linewidth=0.65, label="Raw ECG")
    if imu.size:
        _shade_intervals(axes[0], ti, _motion_mask(imu), "#f59e0b", 0.18)
        axes[0].plot([], [], color="#f59e0b", linewidth=6, alpha=0.25, label="Motion")
    axes[0].set_ylabel("ADC counts")
    axes[0].set_title("Raw ECG and native-rate IMU motion", loc="left", fontsize=10)
    axes[0].legend(loc="upper right", ncols=2)

    filtered_t, filtered = _line_with_gaps(
        ts, sample[:, 3] / 1000.0, sample[:, 8] > 0, 0.004
    )
    normalized_t, normalized = _line_with_gaps(
        ts, sample[:, 4] / 1000.0, sample[:, 8] > 0, 0.004
    )
    axes[1].plot(filtered_t, filtered, color="#2563eb", linewidth=0.7, label="Bandpass")
    axes[1].plot(normalized_t, normalized, color="#059669", linewidth=0.7, label="Z-score")
    detection_axis = axes[1].twinx()
    detection_axis.plot(ts, sample[:, 5] / 1000.0, color="#a855f7", alpha=0.55,
                        linewidth=0.65, label="MWI")
    detection_axis.plot(ts, sample[:, 6] / 1000.0, color="#dc2626", alpha=0.7,
                        linewidth=0.65, label="TH1")
    if beat.size:
        axes[1].scatter(tb, np.interp(tb, ts, sample[:, 4] / 1000.0), marker="|",
                        s=55, color="#dc2626", label="R peak", zorder=4)
    axes[1].set_ylabel("ECG")
    detection_axis.set_ylabel("MWI")
    axes[1].set_title("Firmware DSP output and detector state", loc="left", fontsize=10)
    lines = axes[1].get_lines() + detection_axis.get_lines()
    labels = [line.get_label() for line in lines]
    axes[1].legend(lines, labels, loc="upper right", ncols=4)

    if beat.size:
        gate = beat[:, 5] / 1000.0
        p_v = beat[:, 6] / 1000.0
        p_s = beat[:, 7] / 1000.0
        axes[2].scatter(tb[gate >= 0], gate[gate >= 0], s=16, color="#7c3aed",
                        label="Gate P(abnormal)")
        axes[2].scatter(tb[p_v >= 0], p_v[p_v >= 0], s=16, color="#dc2626",
                        label="SV P(V)")
        axes[2].scatter(tb[p_s >= 0], p_s[p_s >= 0], s=16, color="#d97706",
                        label="SV P(S)")
        axes[2].axhline(0.25, color="#7c3aed", linestyle="--", linewidth=0.8)
        axes[2].axhline(0.60, color="#dc2626", linestyle="--", linewidth=0.8)
        axes[2].axhline(0.35, color="#d97706", linestyle="--", linewidth=0.8)
        classes = np.clip(beat[:, 8].astype(int), 0, 3)
        axes[2].scatter(tb, np.full(tb.size, 1.04), s=20,
                        c=BEAT_COLORS[classes], marker="v", label="Beat class")
    axes[2].set_ylim(-0.04, 1.10)
    axes[2].set_ylabel("Probability")
    axes[2].set_title("AI output at native beat timestamps", loc="left", fontsize=10)
    axes[2].legend(loc="upper right", ncols=4)

    if beat.size:
        axes[3].step(tb, beat[:, 11], where="post", color="#111827", linewidth=1.0,
                     label="HR")
        hrv_axis = axes[3].twinx()
        hrv_axis.step(tb, beat[:, 12], where="post", color="#2563eb", linewidth=0.9,
                      label="SDNN")
        hrv_axis.step(tb, beat[:, 13], where="post", color="#059669", linewidth=0.9,
                      label="RMSSD")
        _rhythm_bands(axes[3], tb, beat[:, 10])
        axes[3].set_ylabel("HR (BPM)")
        hrv_axis.set_ylabel("HRV (ms)")
        lines = axes[3].get_lines() + hrv_axis.get_lines()
        axes[3].legend(lines, [line.get_label() for line in lines],
                       loc="upper right", ncols=5)
    axes[3].set_title("Clinical state and rhythm flags", loc="left", fontsize=10)
    axes[3].set_xlabel("Device time from capture start (s)")

    for axis in axes:
        axis.grid(True, color="#d1d5db", linewidth=0.45, alpha=0.65)
        axis.margins(x=0)

    full_limits = (float(ts[0]), float(ts[-1]))
    flagged = np.empty(0)
    if beat.size:
        flagged = tb[(beat[:, 8] != 0) | (beat[:, 10] != 0)]
    navigator = EventNavigator(figure, axes, flagged, full_limits)
    figure._tarang_event_navigator = navigator
    figure.tight_layout(rect=(0, 0, 1, 0.97))
    return figure, data, flagged


def print_summary(data: dict[str, np.ndarray], flagged: np.ndarray):
    sample, imu, ppg, beat = (
        data["sample"], data["imu"], data["ppg"], data["beat"]
    )
    duration_s = (sample[-1, 0] - sample[0, 0]) / 1000.0
    ecg_drops = int(np.sum(
        (np.diff(sample[:, 1]) != 1) | (np.diff(sample[:, 0]) > 7.0)
    ))
    imu_drops = int(np.sum(np.diff(imu[:, 1]) != 1)) if imu.size else 0
    ppg_drops = int(np.sum(np.diff(ppg[:, 1]) != 1)) if ppg.size else 0
    print(f"[SESSION] duration={duration_s:.3f}s ECG={len(sample)} IMU={len(imu)} PPG={len(ppg)} beats={len(beat)}")
    print(f"[GAPS] ECG={ecg_drops} IMU={imu_drops} PPG={ppg_drops} flagged_events={len(flagged)}")
    print("[VIEW] n=next event, p=previous event, a=entire session")


HTML_TEMPLATE = r"""<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>__TITLE__</title>
<style>
  * { box-sizing: border-box; }
  body { margin: 0; font: 13px system-ui, sans-serif; color: #18212b; background: #f4f6f8; }
  header { height: 48px; display: flex; align-items: center; gap: 12px; padding: 0 16px; background: #fff; border-bottom: 1px solid #cfd5dc; }
  h1 { margin: 0; min-width: 0; flex: 1; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; font-size: 15px; font-weight: 650; }
  .status { color: #56616d; font-variant-numeric: tabular-nums; white-space: nowrap; }
  .tools { display: flex; gap: 4px; }
  button { width: 32px; height: 30px; border: 1px solid #b8c0c9; border-radius: 4px; background: #fff; color: #18212b; font-size: 16px; cursor: pointer; }
  button:hover { background: #edf2f6; }
  main { padding: 10px 12px 16px; }
  .plot { position: relative; height: 190px; margin-bottom: 8px; background: #fff; border: 1px solid #cfd5dc; border-radius: 4px; overflow: hidden; }
  canvas { display: block; width: 100%; height: 100%; cursor: crosshair; }
  .legend { position: absolute; top: 6px; right: 9px; display: flex; gap: 10px; pointer-events: none; font-size: 11px; background: rgba(255,255,255,.86); padding: 3px 5px; }
  .key::before { content: ''; display: inline-block; width: 12px; height: 2px; margin-right: 4px; vertical-align: middle; background: var(--c); }
  @media (max-width: 720px) { .plot { height: 155px; } .status { display: none; } main { padding: 6px; } }
</style>
</head>
<body>
<header>
  <h1>__TITLE__</h1>
  <div class="status" id="status"></div>
  <div class="tools">
    <button id="home" title="Full session" aria-label="Full session">&#8962;</button>
    <button id="prev" title="Previous flagged event" aria-label="Previous event">&#9664;</button>
    <button id="next" title="Next flagged event" aria-label="Next event">&#9654;</button>
  </div>
</header>
<main>
  <section class="plot"><canvas data-row="0"></canvas><div class="legend"><span class="key" style="--c:#20262e">Raw ECG</span><span class="key" style="--c:#f59e0b">Motion</span></div></section>
  <section class="plot"><canvas data-row="1"></canvas><div class="legend"><span class="key" style="--c:#2563eb">Bandpass</span><span class="key" style="--c:#059669">Z-score</span><span class="key" style="--c:#a855f7">MWI</span><span class="key" style="--c:#dc2626">TH1</span></div></section>
  <section class="plot"><canvas data-row="2"></canvas><div class="legend"><span class="key" style="--c:#7c3aed">Gate</span><span class="key" style="--c:#dc2626">P(V)</span><span class="key" style="--c:#d97706">P(S)</span></div></section>
  <section class="plot"><canvas data-row="3"></canvas><div class="legend"><span class="key" style="--c:#111827">HR</span><span class="key" style="--c:#2563eb">SDNN</span><span class="key" style="--c:#059669">RMSSD</span></div></section>
</main>
<script>
const D = __DATA__;
const canvases = [...document.querySelectorAll('canvas')];
const origin = D.S[0][0], full = [origin, D.S[D.S.length - 1][0]];
let view = [...full], dragging = false, dragX = 0, dragView = null, cursorX = null, eventIndex = -1;
const pad = {l: 62, r: 54, t: 26, b: 25};
const colors = ['#707780','#d97706','#dc2626','#111827'];

function lowerBound(rows, value) { let lo=0, hi=rows.length; while(lo<hi){const m=(lo+hi)>>1; if(rows[m][0]<value)lo=m+1;else hi=m;} return lo; }
function bounds(rows) { return [Math.max(0, lowerBound(rows, view[0])-1), Math.min(rows.length, lowerBound(rows, view[1])+1)]; }
function xMap(t,w) { return pad.l + (t-view[0])/(view[1]-view[0])*(w-pad.l-pad.r); }
function yMap(v,min,max,h) { return pad.t + (max-v)/(max-min||1)*(h-pad.t-pad.b); }
function range(rows, cols, validCol=null) {
  if(!rows.length) return [0,1]; const [a,b]=bounds(rows); let mn=Infinity,mx=-Infinity;
  for(let i=a;i<b;i++){ if(validCol!==null && !rows[i][validCol]) continue; for(const c of cols){const v=rows[i][c]; if(v<mn)mn=v;if(v>mx)mx=v;} }
  if(!isFinite(mn)) return [0,1]; const d=Math.max((mx-mn)*.08, 1e-6); return [mn-d,mx+d];
}
function series(ctx,rows,col,min,max,w,h,color,validCol=null,gap=Infinity,scale=1) {
  if(!rows.length)return; const [a,b]=bounds(rows); ctx.strokeStyle=color;ctx.lineWidth=1;ctx.beginPath();let open=false,prev=0;
  for(let i=a;i<b;i++){const r=rows[i], ok=(validCol===null||r[validCol]) && (i===a||r[0]-prev<=gap); const x=xMap(r[0],w),y=yMap(r[col]/scale,min,max,h); if(!ok||!isFinite(y)){open=false;} else if(!open){ctx.moveTo(x,y);open=true;}else ctx.lineTo(x,y); prev=r[0];}
  ctx.stroke();
}
function axes(ctx,w,h,title,left,right='') {
  ctx.strokeStyle='#d5dbe1';ctx.lineWidth=1;ctx.fillStyle='#5b6570';ctx.font='11px system-ui';
  for(let i=0;i<=5;i++){const x=pad.l+i*(w-pad.l-pad.r)/5;ctx.beginPath();ctx.moveTo(x,pad.t);ctx.lineTo(x,h-pad.b);ctx.stroke();const sec=(view[0]-origin+(view[1]-view[0])*i/5)/1000;ctx.fillText(sec.toFixed(sec<10?2:1)+'s',x-12,h-7);}
  ctx.fillStyle='#18212b';ctx.font='600 12px system-ui';ctx.fillText(title,9,16);ctx.save();ctx.translate(14,h/2);ctx.rotate(-Math.PI/2);ctx.fillText(left,0,0);ctx.restore();if(right){ctx.save();ctx.translate(w-8,h/2);ctx.rotate(Math.PI/2);ctx.fillText(right,0,0);ctx.restore();}
}
function motionBands(ctx,w,h){for(const r of D.motion){if(r[1]<view[0]||r[0]>view[1])continue;ctx.fillStyle='rgba(245,158,11,.17)';const x0=xMap(Math.max(r[0],view[0]),w),x1=xMap(Math.min(r[1],view[1]),w);ctx.fillRect(x0,pad.t,x1-x0,h-pad.t-pad.b);}}
function rhythmBands(ctx,w,h){for(const r of D.rhythm){if(r[1]<view[0]||r[0]>view[1])continue;ctx.fillStyle=r[3];const x0=xMap(Math.max(r[0],view[0]),w),x1=xMap(Math.min(r[1],view[1]),w);ctx.fillRect(x0,pad.t,x1-x0,h-pad.t-pad.b);}}
function points(ctx,rows,col,w,h,color,condition){const [a,b]=bounds(rows);ctx.fillStyle=color;for(let i=a;i<b;i++){const r=rows[i];if(!condition(r))continue;const x=xMap(r[0],w),y=yMap(r[col]/1000,0,1.1,h);ctx.fillRect(x-2,y-2,4,4);}}
function draw(canvas){
  const dpr=devicePixelRatio||1,w=canvas.clientWidth,h=canvas.clientHeight;canvas.width=w*dpr;canvas.height=h*dpr;const ctx=canvas.getContext('2d');ctx.scale(dpr,dpr);ctx.fillStyle='#fff';ctx.fillRect(0,0,w,h);const row=+canvas.dataset.row;
  if(row===0){axes(ctx,w,h,'1. Raw ECG and native-rate motion','ADC counts');motionBands(ctx,w,h);const y=range(D.S,[2],8);series(ctx,D.S,2,y[0],y[1],w,h,'#20262e',8,7);}
  if(row===1){axes(ctx,w,h,'2. Firmware DSP and R-peaks','ECG','MWI');const y=range(D.S,[3,4],8),q=range(D.S,[5,6],8);series(ctx,D.S,3,y[0]/1000,y[1]/1000,w,h,'#2563eb',8,7,1000);series(ctx,D.S,4,y[0]/1000,y[1]/1000,w,h,'#059669',8,7,1000);series(ctx,D.S,5,q[0]/1000,q[1]/1000,w,h,'#a855f7',8,7,1000);series(ctx,D.S,6,q[0]/1000,q[1]/1000,w,h,'#dc2626',8,7,1000);ctx.strokeStyle='#dc2626';for(const b of D.B){if(b[0]>=view[0]&&b[0]<=view[1]){const x=xMap(b[0],w);ctx.beginPath();ctx.moveTo(x,pad.t);ctx.lineTo(x,pad.t+8);ctx.stroke();}}}
  if(row===2){axes(ctx,w,h,'3. AI output at beat timestamps','Probability');points(ctx,D.B,5,w,h,'#7c3aed',r=>r[5]>=0);points(ctx,D.B,6,w,h,'#dc2626',r=>r[6]>=0);points(ctx,D.B,7,w,h,'#d97706',r=>r[7]>=0);for(const [v,c] of [[.25,'#7c3aed'],[.6,'#dc2626'],[.35,'#d97706']]){ctx.strokeStyle=c;ctx.setLineDash([4,4]);ctx.beginPath();ctx.moveTo(pad.l,yMap(v,0,1.1,h));ctx.lineTo(w-pad.r,yMap(v,0,1.1,h));ctx.stroke();ctx.setLineDash([]);}for(const b of D.B){if(b[0]>=view[0]&&b[0]<=view[1]){ctx.fillStyle=colors[Math.max(0,Math.min(3,b[8]))];ctx.fillRect(xMap(b[0],w)-2,pad.t+2,4,5);}}}
  if(row===3){axes(ctx,w,h,'4. Clinical state and rhythm flags','HR','HRV');rhythmBands(ctx,w,h);const hr=range(D.B,[11]),hv=range(D.B,[12,13]);series(ctx,D.B,11,hr[0],hr[1],w,h,'#111827');series(ctx,D.B,12,hv[0],hv[1],w,h,'#2563eb');series(ctx,D.B,13,hv[0],hv[1],w,h,'#059669');}
  if(cursorX!==null){ctx.strokeStyle='rgba(24,33,43,.35)';ctx.beginPath();ctx.moveTo(cursorX,pad.t);ctx.lineTo(cursorX,h-pad.b);ctx.stroke();}
}
function redraw(){for(const c of canvases)draw(c);const span=(view[1]-view[0])/1000;document.getElementById('status').textContent=`${span.toFixed(2)} s visible | ${D.S.length.toLocaleString()} ECG samples | ${D.B.length} beats`;}
function clamp(){const span=view[1]-view[0];if(view[0]<full[0]){view[0]=full[0];view[1]=full[0]+span;}if(view[1]>full[1]){view[1]=full[1];view[0]=full[1]-span;}}
for(const c of canvases){
  c.addEventListener('wheel',e=>{e.preventDefault();const r=c.getBoundingClientRect(),p=(e.clientX-r.left-pad.l)/(r.width-pad.l-pad.r),anchor=view[0]+Math.max(0,Math.min(1,p))*(view[1]-view[0]),factor=e.deltaY>0?1.25:.8,span=Math.max(100,Math.min(full[1]-full[0],(view[1]-view[0])*factor));view=[anchor-span*p,anchor+span*(1-p)];clamp();redraw();},{passive:false});
  c.addEventListener('pointerdown',e=>{dragging=true;dragX=e.clientX;dragView=[...view];c.setPointerCapture(e.pointerId);});
  c.addEventListener('pointermove',e=>{const r=c.getBoundingClientRect();cursorX=e.clientX-r.left;if(dragging){const dx=e.clientX-dragX,span=dragView[1]-dragView[0],dt=-dx/(r.width-pad.l-pad.r)*span;view=[dragView[0]+dt,dragView[1]+dt];clamp();}redraw();});
  c.addEventListener('pointerup',()=>dragging=false);c.addEventListener('pointerleave',()=>{if(!dragging){cursorX=null;redraw();}});c.addEventListener('dblclick',()=>{view=[...full];redraw();});
}
function jump(step){if(!D.events.length)return;eventIndex=(eventIndex+step+D.events.length)%D.events.length;const t=D.events[eventIndex],span=Math.min(10000,full[1]-full[0]);view=[t-span/2,t+span/2];clamp();redraw();}
document.getElementById('home').onclick=()=>{view=[...full];redraw();};document.getElementById('prev').onclick=()=>jump(-1);document.getElementById('next').onclick=()=>jump(1);
addEventListener('keydown',e=>{if(e.key==='a'){view=[...full];redraw();}if(e.key==='n')jump(1);if(e.key==='p')jump(-1);});addEventListener('resize',redraw);redraw();
</script>
</body>
</html>"""


def _intervals(time_ms: np.ndarray, mask: np.ndarray) -> list[list[float]]:
    if time_ms.size == 0 or not np.any(mask):
        return []
    changes = np.diff(np.r_[False, mask.astype(bool), False].astype(np.int8))
    starts = np.flatnonzero(changes == 1)
    ends = np.flatnonzero(changes == -1) - 1
    result = []
    for start, end in zip(starts, ends):
        right = time_ms[end + 1] if end + 1 < time_ms.size else time_ms[end]
        result.append([float(time_ms[start]), float(right)])
    return result


def write_html_viewer(data: dict[str, np.ndarray], path: Path, title: str):
    imu, beat = data["imu"], data["beat"]
    motion = _intervals(imu[:, 0], _motion_mask(imu)) if imu.size else []
    rhythm = []
    rhythm_colors = {
        0x01: "rgba(124,58,237,.12)", 0x02: "rgba(239,68,68,.10)",
        0x04: "rgba(37,99,235,.10)", 0x08: "rgba(249,115,22,.12)",
        0x10: "rgba(234,179,8,.12)", 0x20: "rgba(185,28,28,.14)",
        0x40: "rgba(219,39,119,.12)", 0x80: "rgba(69,10,10,.20)",
    }
    if beat.size:
        for bit, color in rhythm_colors.items():
            for start, end in _intervals(beat[:, 0], (beat[:, 10].astype(np.uint8) & bit) != 0):
                rhythm.append([start, end, bit, color])
    events = beat[(beat[:, 8] != 0) | (beat[:, 10] != 0), 0].tolist() if beat.size else []
    payload = {
        "S": data["sample"].tolist(), "I": imu.tolist(),
        "P": data["ppg"].tolist(), "B": beat.tolist(),
        "motion": motion, "rhythm": rhythm, "events": events,
    }
    document = HTML_TEMPLATE.replace("__TITLE__", html.escape(title)).replace(
        "__DATA__", json.dumps(payload, separators=(",", ":"), allow_nan=False)
    )
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(document, encoding="utf-8")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("csv", type=Path, help="VCOM CSV or raw telemetry text file")
    parser.add_argument("--html", type=Path, help="output HTML path")
    parser.add_argument("--save", type=Path, help="also save a static PNG")
    parser.add_argument("--no-open", action="store_true", help="do not open the HTML viewer")
    parser.add_argument("--no-show", action="store_true", help=argparse.SUPPRESS)
    args = parser.parse_args()

    try:
        session = load_session(args.csv)
    except (OSError, ValueError) as exc:
        parser.error(str(exc))

    data = session.arrays()
    beat = data["beat"]
    flagged = beat[(beat[:, 8] != 0) | (beat[:, 10] != 0), 0] if beat.size else np.empty(0)
    print_summary(data, flagged)
    html_path = args.html or args.csv.with_suffix(".html")
    write_html_viewer(data, html_path, f"TARANG: {args.csv.name}")
    print(f"[SAVED] {html_path}")
    if args.save:
        figure, _, _ = build_figure(session, f"TARANG: {args.csv.name}")
        args.save.parent.mkdir(parents=True, exist_ok=True)
        figure.savefig(args.save, dpi=160)
        print(f"[SAVED] {args.save}")
        plt.close(figure)
    if not (args.no_open or args.no_show):
        webbrowser.open(html_path.resolve().as_uri())
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
