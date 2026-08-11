'use client';

import React from 'react';
import { ClinicalTelemetryPacket, PatientInfo } from '../types/telemetry';
import { WaveformCanvas } from './WaveformCanvas';
import { Heart, Activity, Wind, Gauge, ShieldAlert, TrendingUp, Clock } from 'lucide-react';

interface WorkstationViewProps {
  telemetry: ClinicalTelemetryPacket;
  patient: PatientInfo;
}

export const WorkstationView: React.FC<WorkstationViewProps> = ({ telemetry, patient }) => {
  return (
    <div className="space-y-6">
      {/* Patient Header Banner */}
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
            MRN: <span className="font-mono font-bold">{patient.id}</span> • Admitted: {patient.admitDate} • Attending: <span className="font-semibold text-[var(--color-primary)]">{patient.attendingPhysician}</span>
          </p>
        </div>

        <div className="flex items-center gap-4 text-right">
          <div>
            <span className="text-[11px] text-[var(--color-on-surface-variant)] block font-mono">LIVE TELEMETRY SYNC</span>
            <span className="text-xs font-bold text-emerald-700 flex items-center gap-1 justify-end font-mono">
              <span className="w-2 h-2 rounded-full bg-emerald-500 animate-ping"></span>
              250 Hz Continuous
            </span>
          </div>
        </div>
      </div>

      {/* Top Vitals KPI Cards */}
      <div className="grid grid-cols-5 gap-4">
        {/* Heart Rate Card */}
        <div className="card-clinical p-4 flex flex-col justify-between border-l-4 border-l-[var(--color-primary)]">
          <div className="flex items-center justify-between text-[var(--color-on-surface-variant)]">
            <span className="text-xs font-bold uppercase tracking-wider">Heart Rate</span>
            <Heart className="w-4 h-4 text-emerald-600" />
          </div>
          <div className="my-2">
            <div className="flex items-baseline gap-1">
              <span className="font-mono font-extrabold text-4xl text-[var(--color-on-surface)]">
                {telemetry.current_hr || 74}
              </span>
              <span className="text-xs font-mono text-[var(--color-on-surface-variant)]">BPM</span>
            </div>
          </div>
          <div className="flex items-center justify-between text-[11px] font-mono border-t border-[var(--color-outline-variant)] pt-2">
            <span className="text-emerald-700 font-semibold flex items-center gap-1">
              <TrendingUp className="w-3 h-3" /> Normal
            </span>
            <span className="text-[var(--color-on-surface-variant)]">Ref: 60-100</span>
          </div>
        </div>

        {/* SpO2 Oxygen Card */}
        <div className="card-clinical p-4 flex flex-col justify-between border-l-4 border-l-amber-500">
          <div className="flex items-center justify-between text-[var(--color-on-surface-variant)]">
            <span className="text-xs font-bold uppercase tracking-wider">SpO2 Pulse</span>
            <Activity className="w-4 h-4 text-amber-500" />
          </div>
          <div className="my-2">
            <div className="flex items-baseline gap-1">
              <span className="font-mono font-extrabold text-4xl text-[var(--color-on-surface)]">
                {telemetry.spo2_pct || 98}
              </span>
              <span className="text-xs font-mono text-[var(--color-on-surface-variant)]">%</span>
            </div>
          </div>
          <div className="flex items-center justify-between text-[11px] font-mono border-t border-[var(--color-outline-variant)] pt-2">
            <span className="text-amber-700 font-semibold">Optimal Sat</span>
            <span className="text-[var(--color-on-surface-variant)]">Ref: 95-100%</span>
          </div>
        </div>

        {/* Respiration Rate Card */}
        <div className="card-clinical p-4 flex flex-col justify-between border-l-4 border-l-sky-500">
          <div className="flex items-center justify-between text-[var(--color-on-surface-variant)]">
            <span className="text-xs font-bold uppercase tracking-wider">Resp Rate</span>
            <Wind className="w-4 h-4 text-sky-500" />
          </div>
          <div className="my-2">
            <div className="flex items-baseline gap-1">
              <span className="font-mono font-extrabold text-4xl text-[var(--color-on-surface)]">
                {telemetry.resp_rate || 16}
              </span>
              <span className="text-xs font-mono text-[var(--color-on-surface-variant)]">rpm</span>
            </div>
          </div>
          <div className="flex items-center justify-between text-[11px] font-mono border-t border-[var(--color-outline-variant)] pt-2">
            <span className="text-sky-700 font-semibold">Regular</span>
            <span className="text-[var(--color-on-surface-variant)]">Ref: 12-20</span>
          </div>
        </div>

        {/* Blood Pressure Card */}
        <div className="card-clinical p-4 flex flex-col justify-between border-l-4 border-l-indigo-500">
          <div className="flex items-center justify-between text-[var(--color-on-surface-variant)]">
            <span className="text-xs font-bold uppercase tracking-wider">Blood Press</span>
            <Gauge className="w-4 h-4 text-indigo-500" />
          </div>
          <div className="my-2">
            <div className="flex items-baseline gap-1">
              <span className="font-mono font-extrabold text-2xl text-[var(--color-on-surface)]">
                {telemetry.bp_systolic || 120}/{telemetry.bp_diastolic || 80}
              </span>
              <span className="text-xs font-mono text-[var(--color-on-surface-variant)]">mmHg</span>
            </div>
          </div>
          <div className="flex items-center justify-between text-[11px] font-mono border-t border-[var(--color-outline-variant)] pt-2">
            <span className="text-indigo-700 font-semibold">Normotensive</span>
            <span className="text-[var(--color-on-surface-variant)]">Ref: 120/80</span>
          </div>
        </div>

        {/* HRV Metric Card */}
        <div className="card-clinical p-4 flex flex-col justify-between border-l-4 border-l-teal-600">
          <div className="flex items-center justify-between text-[var(--color-on-surface-variant)]">
            <span className="text-xs font-bold uppercase tracking-wider">HRV SDNN</span>
            <Activity className="w-4 h-4 text-teal-600" />
          </div>
          <div className="my-2">
            <div className="flex items-baseline gap-1">
              <span className="font-mono font-extrabold text-4xl text-[var(--color-on-surface)]">
                {telemetry.sdnn_ms || 44}
              </span>
              <span className="text-xs font-mono text-[var(--color-on-surface-variant)]">ms</span>
            </div>
          </div>
          <div className="flex items-center justify-between text-[11px] font-mono border-t border-[var(--color-outline-variant)] pt-2">
            <span className="text-teal-700 font-semibold">Autonomic Balance</span>
            <span className="text-[var(--color-on-surface-variant)]">RMSSD: {telemetry.rmssd_ms || 38}ms</span>
          </div>
        </div>
      </div>

      {/* Main Waveform Canvas */}
      <WaveformCanvas telemetry={telemetry} />

      {/* Live Event Stream Feed Table */}
      <div className="card-clinical p-4 space-y-3">
        <div className="flex items-center justify-between border-b border-[var(--color-outline-variant)] pb-3">
          <div className="flex items-center gap-2">
            <Clock className="w-4 h-4 text-[var(--color-primary)]" />
            <h3 className="text-sm font-bold text-[var(--color-on-surface)] uppercase tracking-wider">
              Real-time Clinical Event Log
            </h3>
          </div>
          <span className="text-xs font-mono text-[var(--color-on-surface-variant)]">Auto-scroll: ON</span>
        </div>

        <div className="overflow-x-auto">
          <table className="w-full text-left text-xs font-mono">
            <thead>
              <tr className="border-b border-[var(--color-outline-variant)] text-[var(--color-on-surface-variant)] bg-[var(--color-surface-container-low)]">
                <th className="p-2 font-semibold">Timestamp</th>
                <th className="p-2 font-semibold">Beat Class</th>
                <th className="p-2 font-semibold">HR (BPM)</th>
                <th className="p-2 font-semibold">RR Interval</th>
                <th className="p-2 font-semibold">TFLite Conf</th>
                <th className="p-2 font-semibold">Rhythm Event</th>
                <th className="p-2 font-semibold">Status</th>
              </tr>
            </thead>
            <tbody className="divide-y divide-[var(--color-outline-variant)]">
              <tr>
                <td className="p-2 font-bold text-[var(--color-on-surface)]">11:14:02.120</td>
                <td className="p-2">
                  <span className="px-2 py-0.5 rounded text-[10px] font-bold bg-emerald-100 text-emerald-800 border border-emerald-300">
                    NORMAL (N)
                  </span>
                </td>
                <td className="p-2 font-bold">{telemetry.current_hr || 74}</td>
                <td className="p-2">{telemetry.rr_interval_ms || 810} ms</td>
                <td className="p-2">98.4%</td>
                <td className="p-2 text-emerald-700 font-semibold">Normal Sinus Rhythm</td>
                <td className="p-2 text-emerald-600">VERIFIED</td>
              </tr>
              <tr>
                <td className="p-2 font-bold text-[var(--color-on-surface)]">11:13:58.440</td>
                <td className="p-2">
                  <span className="px-2 py-0.5 rounded text-[10px] font-bold bg-amber-100 text-amber-900 border border-amber-300">
                    PAC (Ectopic)
                  </span>
                </td>
                <td className="p-2 font-bold">78</td>
                <td className="p-2">680 ms</td>
                <td className="p-2">92.1%</td>
                <td className="p-2 text-amber-700 font-semibold">Isolated Premature Atrial Beat</td>
                <td className="p-2 text-amber-600">LOGGED</td>
              </tr>
            </tbody>
          </table>
        </div>
      </div>
    </div>
  );
};
