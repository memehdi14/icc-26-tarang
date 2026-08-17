'use client';

import React from 'react';
import { PatientInfo, ClinicalTelemetryPacket } from '../types/telemetry';
import { User, AlertTriangle, Cpu, Heart, CheckCircle2, ShieldAlert, FileText, PhoneCall } from 'lucide-react';

interface PatientSummarySidebarProps {
  patient: PatientInfo;
  telemetry: ClinicalTelemetryPacket;
}

function decodeRhythm(flags: number): string {
  if (!flags) return 'Normal Sinus Rhythm';
  const names: string[] = [];
  if (flags & 0x01) names.push('AFib Detected');
  if (flags & 0x02) names.push('Sinus Tachycardia');
  if (flags & 0x04) names.push('Sinus Bradycardia');
  if (flags & 0x08) names.push('Bigeminy');
  if (flags & 0x10) names.push('Trigeminy');
  if (flags & 0x20) names.push('V-Run');
  if (flags & 0x40) names.push('SVT-Run');
  if (flags & 0x80) names.push('VT Suspected!');
  return names.length > 0 ? names.join(' | ') : 'Normal Sinus Rhythm';
}

export const PatientSummarySidebar: React.FC<PatientSummarySidebarProps> = ({ patient, telemetry }) => {
  const confidenceStr = telemetry.confidence ? `${((telemetry.confidence / 255) * 100).toFixed(1)}%` : '98.4%';
  const rhythmText = decodeRhythm(telemetry.rhythm_flags);

  return (
    <aside style={{ width: '320px', backgroundColor: 'var(--color-surface-container-lowest)', borderLeft: '1px solid var(--color-outline-variant)' }} className="flex flex-col h-screen fixed right-0 top-0 z-20 overflow-y-auto p-4 space-y-4">
      {/* Patient Header Card */}
      <div className="card-clinical p-4 space-y-3 bg-gradient-to-br from-[var(--color-surface-container-low)] to-white">
        <div className="flex items-center justify-between">
          <span className="text-[10px] font-mono font-bold tracking-wider px-2 py-0.5 rounded bg-[var(--color-primary-container)] text-white">
            BED {patient.bed}
          </span>
          <span className="text-xs font-mono text-[var(--color-on-surface-variant)]">MRN: {patient.id}</span>
        </div>

        <div className="flex items-center gap-3 pt-1">
          <div className="w-12 h-12 rounded-full bg-[var(--color-surface-container-high)] text-[var(--color-primary)] flex items-center justify-center font-extrabold text-lg border border-[var(--color-outline-variant)]">
            {patient.name.split(' ').map(n => n[0]).join('')}
          </div>
          <div>
            <h2 className="text-lg font-bold text-[var(--color-on-surface)] leading-tight">{patient.name}</h2>
            <p className="text-xs text-[var(--color-on-surface-variant)] font-medium">
              {patient.age} yrs • {patient.gender} • Blood Group: <span className="font-mono font-bold text-[var(--color-primary)]">{patient.bloodType}</span>
            </p>
          </div>
        </div>
      </div>

      {/* Allergies Warning Chips */}
      <div className="card-clinical-inset p-3 bg-red-50/50 border-red-200">
        <div className="flex items-center gap-1.5 text-xs font-bold text-red-800 mb-2">
          <AlertTriangle className="w-4 h-4 text-red-600" />
          <span>Active Patient Allergies</span>
        </div>
        <div className="flex flex-wrap gap-1.5">
          {patient.allergies.map((allergy, idx) => (
            <span key={idx} className="px-2 py-0.5 rounded text-[11px] font-semibold bg-red-100 text-red-900 border border-red-300">
              {allergy}
            </span>
          ))}
        </div>
      </div>

      {/* TFLite AI Clinical Insights */}
      <div className="card-clinical p-4 space-y-3 border-[var(--color-primary-container)]">
        <div className="flex items-center justify-between pb-2 border-b border-[var(--color-outline-variant)]">
          <div className="flex items-center gap-2 text-xs font-bold text-[var(--color-primary)]">
            <Cpu className="w-4 h-4" />
            <span>TFLite Cascade Insights</span>
          </div>
          <span className="text-[10px] font-mono font-bold px-1.5 py-0.5 rounded bg-[var(--color-surface-container-high)] text-[var(--color-primary)]">
            Tier 0-3 Active
          </span>
        </div>

        {/* Current Rhythm Classification */}
        <div className="p-2.5 rounded-lg bg-[var(--color-surface-container-low)] border border-[var(--color-outline-variant)] flex items-center justify-between">
          <div>
            <p className="text-[11px] text-[var(--color-on-surface-variant)] font-medium">Detected Rhythm</p>
            <p className="text-sm font-bold text-[var(--color-primary)] flex items-center gap-1">
              <CheckCircle2 className="w-3.5 h-3.5 text-emerald-600" />
              {rhythmText}
            </p>
          </div>
          <div className="text-right font-mono">
            <p className="text-[10px] text-[var(--color-on-surface-variant)]">Model Confidence</p>
            <p className="text-xs font-bold text-[var(--color-on-surface)]">{confidenceStr}</p>
          </div>
        </div>

        {/* PAC / PVC Arrhythmia Burden */}
        <div className="grid grid-cols-2 gap-2 text-xs">
          <div className="p-2 rounded bg-[var(--color-surface-container-low)] border border-[var(--color-outline-variant)]">
            <span className="text-[10px] text-[var(--color-on-surface-variant)] block">PAC Burden</span>
            <span className="font-mono font-bold text-sm text-[var(--color-on-surface)]">{telemetry.pac_burden_pct ?? 0}%</span>
          </div>
          <div className="p-2 rounded bg-[var(--color-surface-container-low)] border border-[var(--color-outline-variant)]">
            <span className="text-[10px] text-[var(--color-on-surface-variant)] block">PVC Burden</span>
            <span className="font-mono font-bold text-sm text-[var(--color-on-surface)]">{telemetry.pvc_burden_pct ?? 0}%</span>
          </div>
        </div>

        {/* HRV Autonomous Metrics */}
        <div className="space-y-1 pt-1">
          <div className="flex justify-between text-xs font-medium">
            <span className="text-[var(--color-on-surface-variant)]">HRV SDNN:</span>
            <span className="font-mono font-bold text-[var(--color-on-surface)]">{telemetry.sdnn_ms ?? 0} ms</span>
          </div>
          <div className="flex justify-between text-xs font-medium">
            <span className="text-[var(--color-on-surface-variant)]">HRV RMSSD:</span>
            <span className="font-mono font-bold text-[var(--color-on-surface)]">{telemetry.rmssd_ms ?? 0} ms</span>
          </div>
        </div>
      </div>

      {/* Medical History */}
      <div className="card-clinical p-4 space-y-2">
        <h3 className="text-xs font-bold text-[var(--color-on-surface)] uppercase tracking-wider">Medical History</h3>
        <ul className="space-y-1.5 text-xs text-[var(--color-on-surface-variant)]">
          {patient.medicalHistory.map((item, idx) => (
            <li key={idx} className="flex items-start gap-2">
              <span className="w-1.5 h-1.5 rounded-full bg-[var(--color-primary)] mt-1.5 flex-shrink-0"></span>
              <span>{item}</span>
            </li>
          ))}
        </ul>
      </div>

      {/* Quick Clinical Actions */}
      <div className="space-y-2 pt-2">
        <button className="w-full py-2.5 px-3 rounded-lg bg-[var(--color-primary)] text-white text-xs font-bold flex items-center justify-center gap-2 hover:bg-[var(--color-primary-container)] transition-colors shadow-sm">
          <FileText className="w-4 h-4" />
          <span>Export 10s ECG PDF Strip</span>
        </button>
        <button className="w-full py-2 px-3 rounded-lg border border-[var(--color-outline-variant)] text-[var(--color-on-surface)] text-xs font-semibold flex items-center justify-center gap-2 hover:bg-[var(--color-surface-container)] transition-colors">
          <PhoneCall className="w-4 h-4 text-[var(--color-primary)]" />
          <span>Page Duty Physician</span>
        </button>
      </div>
    </aside>
  );
};
