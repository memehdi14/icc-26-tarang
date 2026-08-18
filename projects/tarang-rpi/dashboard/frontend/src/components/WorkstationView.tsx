'use client';

import React from 'react';
import {
  VitalsSample,
  Analytics5Min,
  ClinicalEvent,
  EcgSnippet,
  PatientInfo,
} from '../types/telemetry';
import { WaveformCanvas } from './WaveformCanvas';
import {
  Heart,
  Activity,
  Wind,
  Gauge,
  Cpu,
  Moon,
  Clock,
  AlertTriangle,
  CheckCircle,
  AlertOctagon,
  Flame,
} from 'lucide-react';

interface WorkstationViewProps {
  vitals: VitalsSample;
  analytics: Analytics5Min;
  latestEvent?: ClinicalEvent | null;
  activeSnippet?: EcgSnippet | null;
  glitchTicker?: ClinicalEvent[];
  patient: PatientInfo;
  onClearSnapshot?: () => void;
}

function getTriageBannerDetails(rhythmStatus?: number, patternType?: string | null) {
  if (rhythmStatus === 2 || patternType === 'VT' || patternType === 'V-Run') {
    return {
      bg: 'bg-red-600',
      border: 'border-red-700',
      text: 'text-white',
      badge: 'bg-white text-red-700 font-extrabold',
      title: 'CRITICAL ALERT: VENTRICULAR TACHYCARDIA / V-RUN SUSPECTED',
      desc: 'Immediate clinical review required. AI Cascade confirmed abnormal ventricular ectopy.',
      icon: AlertOctagon,
    };
  }
  if (rhythmStatus === 1 || patternType === 'AFib') {
    return {
      bg: 'bg-amber-500',
      border: 'border-amber-600',
      text: 'text-amber-950',
      badge: 'bg-amber-950 text-amber-100 font-bold',
      title: 'ATRIAL FIBRILLATION DETECTED (RR CoV & pRR50 GATED)',
      desc: 'High RR irregularity detected by Tier-3 deterministic clinical engine. 4s snippet captured.',
      icon: AlertTriangle,
    };
  }
  if (patternType && patternType !== 'null') {
    return {
      bg: 'bg-amber-500',
      border: 'border-amber-600',
      text: 'text-amber-950',
      badge: 'bg-amber-900 text-white font-bold',
      title: `ARRHYTHMIA GLITCH DETECTED: ${patternType.toUpperCase()}`,
      desc: 'Significant ectopic clustering detected and recorded in Glitch Ticker.',
      icon: Flame,
    };
  }
  return {
    bg: 'bg-emerald-600',
    border: 'border-emerald-700',
    text: 'text-white',
    badge: 'bg-emerald-800 text-emerald-100 font-semibold',
    title: 'NORMAL SINUS RHYTHM (NSR) — EM2 LOW-POWER ACTIVE',
    desc: 'Patient hemodynamically stable. Edge MCU operating at ~92% EM2 sleep duty cycle.',
    icon: CheckCircle,
  };
}

function formatTime(ts?: string | null): string {
  if (!ts) return 'Live Sync';
  const d = new Date(ts);
  return isNaN(d.getTime()) ? ts : d.toLocaleTimeString();
}

export const WorkstationView: React.FC<WorkstationViewProps> = ({
  vitals,
  analytics,
  latestEvent,
  activeSnippet,
  glitchTicker = [],
  patient,
  onClearSnapshot,
}) => {
  const triage = getTriageBannerDetails(latestEvent?.rhythmStatus, latestEvent?.patternType);
  const TriageIcon = triage.icon;

  return (
    <div className="space-y-6">
      {/* ── Triage Banner (Event-Driven: Green -> Amber -> Red) ─────────────── */}
      <div
        className={`p-4 rounded-xl border ${triage.bg} ${triage.border} ${triage.text} shadow-md transition-colors duration-300 flex items-center justify-between`}
      >
        <div className="flex items-center gap-3">
          <div className="p-2 rounded-lg bg-black/10">
            <TriageIcon className="w-6 h-6 animate-pulse" />
          </div>
          <div>
            <div className="flex items-center gap-2">
              <h2 className="text-base font-black tracking-wide">{triage.title}</h2>
              <span className={`px-2 py-0.5 rounded text-[10px] uppercase font-mono ${triage.badge}`}>
                Mode A Event Driven
              </span>
            </div>
            <p className="text-xs opacity-90 mt-0.5">{triage.desc}</p>
          </div>
        </div>

        <div className="text-right font-mono text-xs opacity-90">
          <div className="font-bold">TRIAGE STATUS</div>
          <div>{formatTime(latestEvent?.ts)}</div>
        </div>
      </div>

      {/* ── Patient Header ─────────────────────────────────────────────────── */}
      <div className="flex items-center justify-between bg-white p-4 rounded-xl border border-[var(--color-outline-variant)] shadow-sm">
        <div>
          <div className="flex items-center gap-3">
            <h1 className="text-2xl font-extrabold text-[var(--color-on-surface)]">{patient.name}</h1>
            <span className="px-2.5 py-1 rounded-full text-xs font-mono font-bold bg-[var(--color-primary-container)] text-white">
              BED {patient.bed}
            </span>
            <span className="px-2.5 py-0.5 rounded text-xs font-semibold bg-emerald-100 text-emerald-800 border border-emerald-300">
              STABLE ICU MONITORING
            </span>
          </div>
          <p className="text-xs text-[var(--color-on-surface-variant)] mt-1">
            MRN: <span className="font-mono font-bold">{patient.id}</span> • Admitted: {patient.admitDate} • Attending:{' '}
            <span className="font-semibold text-[var(--color-primary)]">{patient.attendingPhysician}</span>
          </p>
        </div>

        <div className="flex items-center gap-4 text-right font-mono">
          <div>
            <span className="text-[11px] text-[var(--color-on-surface-variant)] block">POD POWER STATE</span>
            <span className="text-xs font-bold text-emerald-700 flex items-center gap-1 justify-end">
              <span className="w-2 h-2 rounded-full bg-emerald-500 animate-ping"></span>
              EM2 Sleep {analytics.em2SleepPct || 92}%
            </span>
          </div>
        </div>
      </div>

      {/* ── Top KPI Cards: Instant Vitals + Edge AI Health ──────────────────── */}
      <div className="grid grid-cols-5 gap-4">
        {/* Instant Heart Rate (Periodic 2s) */}
        <div className="card-clinical p-4 flex flex-col justify-between border-l-4 border-l-[var(--color-primary)]">
          <div className="flex items-center justify-between text-[var(--color-on-surface-variant)]">
            <span className="text-xs font-bold uppercase tracking-wider">Heart Rate</span>
            <Heart className="w-4 h-4 text-emerald-600 animate-pulse" />
          </div>
          <div className="my-2">
            <div className="flex items-baseline gap-1">
              <span className="font-mono font-extrabold text-4xl text-[var(--color-on-surface)]">
                {vitals.heartRateBpm ?? 75}
              </span>
              <span className="text-xs font-mono text-[var(--color-on-surface-variant)]">BPM</span>
            </div>
          </div>
          <div className="flex items-center justify-between text-[11px] font-mono border-t border-[var(--color-outline-variant)] pt-2">
            <span className="text-emerald-700 font-semibold">ECG+PPG Fused</span>
            <span className="text-[var(--color-on-surface-variant)]">Ref: 60-100</span>
          </div>
        </div>

        {/* SpO2 Saturation (Periodic 2s) */}
        <div className="card-clinical p-4 flex flex-col justify-between border-l-4 border-l-indigo-500">
          <div className="flex items-center justify-between text-[var(--color-on-surface-variant)]">
            <span className="text-xs font-bold uppercase tracking-wider">SpO2 Pulse</span>
            <Gauge className="w-4 h-4 text-indigo-500" />
          </div>
          <div className="my-2">
            <div className="flex items-baseline gap-1">
              <span className="font-mono font-extrabold text-4xl text-[var(--color-on-surface)]">
                {vitals.spo2Pct ?? 98}
              </span>
              <span className="text-xs font-mono text-[var(--color-on-surface-variant)]">%</span>
            </div>
          </div>
          <div className="flex items-center justify-between text-[11px] font-mono border-t border-[var(--color-outline-variant)] pt-2">
            <span className="text-indigo-700 font-semibold">MAX30102</span>
            <span className="text-[var(--color-on-surface-variant)]">Ref: 95-100%</span>
          </div>
        </div>

        {/* Arrhythmia Burden (5-Min Rollup) */}
        <div className="card-clinical p-4 flex flex-col justify-between border-l-4 border-l-amber-500">
          <div className="flex items-center justify-between text-[var(--color-on-surface-variant)]">
            <span className="text-xs font-bold uppercase tracking-wider">PVC/PAC Burden</span>
            <Wind className="w-4 h-4 text-amber-500" />
          </div>
          <div className="my-2">
            <div className="flex items-baseline gap-2">
              <span className="font-mono font-extrabold text-xl text-[var(--color-on-surface)]">
                PVC {analytics.pvcBurdenPct ?? 0.4}%
              </span>
              <span className="font-mono font-extrabold text-xl text-sky-700">
                PAC {analytics.pacBurdenPct ?? 1.2}%
              </span>
            </div>
          </div>
          <div className="flex items-center justify-between text-[11px] font-mono border-t border-[var(--color-outline-variant)] pt-2">
            <span className="text-amber-700 font-semibold">5-Min Rollup</span>
            <span className="text-[var(--color-on-surface-variant)]">Target &lt; 5%</span>
          </div>
        </div>

        {/* Clinical HRV (5-Min Rollup) */}
        <div className="card-clinical p-4 flex flex-col justify-between border-l-4 border-l-teal-600">
          <div className="flex items-center justify-between text-[var(--color-on-surface-variant)]">
            <span className="text-xs font-bold uppercase tracking-wider">Clinical HRV</span>
            <Activity className="w-4 h-4 text-teal-600" />
          </div>
          <div className="my-2">
            <div className="flex items-baseline gap-1">
              <span className="font-mono font-extrabold text-4xl text-[var(--color-on-surface)]">
                {analytics.sdnn ?? 44}
              </span>
              <span className="text-xs font-mono text-[var(--color-on-surface-variant)]">ms (SDNN)</span>
            </div>
          </div>
          <div className="flex items-center justify-between text-[11px] font-mono border-t border-[var(--color-outline-variant)] pt-2">
            <span className="text-teal-700 font-semibold">RMSSD: {analytics.rmssd ?? 38}ms</span>
            <span className="text-[var(--color-on-surface-variant)]">pRR50: {analytics.prr50 ?? 8.5}%</span>
          </div>
        </div>

        {/* Edge AI & Low-Power Sleep Health (5-Min Rollup) */}
        <div className="card-clinical p-4 flex flex-col justify-between border-l-4 border-l-purple-600">
          <div className="flex items-center justify-between text-[var(--color-on-surface-variant)]">
            <span className="text-xs font-bold uppercase tracking-wider">Edge AI & Power</span>
            <Cpu className="w-4 h-4 text-purple-600" />
          </div>
          <div className="my-2">
            <div className="flex items-baseline gap-1">
              <span className="font-mono font-extrabold text-4xl text-[var(--color-on-surface)]">
                {analytics.em2SleepPct ?? 92}%
              </span>
              <span className="text-xs font-mono text-[var(--color-on-surface-variant)]">EM2 Sleep</span>
            </div>
          </div>
          <div className="flex items-center justify-between text-[11px] font-mono border-t border-[var(--color-outline-variant)] pt-2">
            <span className="text-purple-700 font-semibold flex items-center gap-1">
              <Moon className="w-3 h-3" /> Duty: {analytics.aiDutyCyclePct ?? 1.5}%
            </span>
            <span className="text-[var(--color-on-surface-variant)]">Energy-Gated</span>
          </div>
        </div>
      </div>

      {/* ── Main Waveform Canvas (Idle Low-Power vs Event 4s Snapshot) ──────── */}
      <WaveformCanvas
        currentEvent={latestEvent}
        activeSnippet={activeSnippet}
        onClearSnapshot={onClearSnapshot}
      />

      {/* ── Glitch Ticker: Append-Only Arrhythmia Event Stream ──────────────── */}
      <div className="card-clinical p-4 space-y-3">
        <div className="flex items-center justify-between border-b border-[var(--color-outline-variant)] pb-3">
          <div className="flex items-center gap-2">
            <Clock className="w-4 h-4 text-[var(--color-primary)]" />
            <h3 className="text-sm font-bold text-[var(--color-on-surface)] uppercase tracking-wider">
              Mode A Glitch Ticker (Couplets • Triplets • Bigeminy • Runs)
            </h3>
          </div>
          <span className="text-xs font-mono text-[var(--color-on-surface-variant)]">
            {glitchTicker.length} Anomaly Events Recorded
          </span>
        </div>

        <div className="overflow-x-auto">
          <table className="w-full text-left text-xs font-mono">
            <thead>
              <tr className="border-b border-[var(--color-outline-variant)] text-[var(--color-on-surface-variant)] bg-[var(--color-surface-container-low)]">
                <th className="p-2 font-semibold">Time</th>
                <th className="p-2 font-semibold">Event Pattern</th>
                <th className="p-2 font-semibold">Rhythm Classification</th>
                <th className="p-2 font-semibold">AI Confidence</th>
                <th className="p-2 font-semibold">Snapshot Status</th>
                <th className="p-2 font-semibold">Action</th>
              </tr>
            </thead>
            <tbody className="divide-y divide-[var(--color-outline-variant)]">
              {glitchTicker.length > 0 ? (
                glitchTicker.map((evt, idx) => (
                  <tr key={idx} className="hover:bg-[var(--color-surface-container-low)]">
                    <td className="p-2 font-bold text-[var(--color-on-surface)]">{formatTime(evt.ts)}</td>
                    <td className="p-2">
                      <span className="px-2 py-0.5 rounded text-[10px] font-bold bg-amber-100 text-amber-900 border border-amber-300">
                        {evt.patternType || 'Rhythm Change'}
                      </span>
                    </td>
                    <td className="p-2 font-semibold">
                      {evt.rhythmStatus === 2
                        ? 'Ventricular Tachycardia'
                        : evt.rhythmStatus === 1
                        ? 'Atrial Fibrillation'
                        : 'Ectopic Glitch'}
                    </td>
                    <td className="p-2">{((evt.confidence || 0.95) * 100).toFixed(1)}%</td>
                    <td className="p-2 text-emerald-700 font-bold">4s Snippet Captured</td>
                    <td className="p-2">
                      <span className="text-[var(--color-primary)] font-bold cursor-pointer hover:underline">
                        View Waveform
                      </span>
                    </td>
                  </tr>
                ))
              ) : (
                <tr>
                  <td colSpan={6} className="p-4 text-center text-[var(--color-on-surface-variant)]">
                    No arrhythmia glitches recorded yet. System monitoring in EM2 Low-Power Standby.
                  </td>
                </tr>
              )}
            </tbody>
          </table>
        </div>
      </div>
    </div>
  );
};
