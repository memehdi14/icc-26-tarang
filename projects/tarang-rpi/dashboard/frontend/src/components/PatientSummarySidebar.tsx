'use client';

import React from 'react';
import { AlertTriangle, BrainCircuit, CheckCircle2, FileDown, PhoneCall, RefreshCw } from 'lucide-react';
import { ClinicalTelemetryPacket, PatientInfo } from '../types/telemetry';

interface PatientSummarySidebarProps {
  patient: PatientInfo;
  telemetry: ClinicalTelemetryPacket;
  canExportEcg: boolean;
  exportBusy: boolean;
  pageBusy: boolean;
  actionMessage?: string | null;
  onExportEcg: () => void;
  onPagePhysician: () => void;
}

function decodeRhythm(flags: number): string {
  if (!flags) return 'Normal sinus rhythm';
  const names: string[] = [];
  if (flags & 0x01) names.push('AFib');
  if (flags & 0x02) names.push('Tachycardia');
  if (flags & 0x04) names.push('Bradycardia');
  if (flags & 0x08) names.push('Bigeminy');
  if (flags & 0x10) names.push('Trigeminy');
  if (flags & 0x20) names.push('V-run');
  if (flags & 0x40) names.push('SVT run');
  if (flags & 0x80) names.push('VT suspected');
  return names.join(' / ');
}

export const PatientSummarySidebar: React.FC<PatientSummarySidebarProps> = ({
  patient,
  telemetry,
  canExportEcg,
  exportBusy,
  pageBusy,
  actionMessage,
  onExportEcg,
  onPagePhysician,
}) => {
  const confidence = telemetry.confidence ? `${((telemetry.confidence / 255) * 100).toFixed(1)}%` : 'Pending';
  const initials = patient.name.split(/\s+/).map((part) => part[0]).join('').slice(0, 2).toUpperCase();

  return (
    <aside className="patient-rail" aria-label="Patient clinical summary">
      <section className="border-b border-[var(--color-outline-variant)] p-5">
        <div className="mb-4 flex items-center justify-between">
          <span className="eyebrow text-[var(--color-primary)]">Patient summary</span>
          <span className="rounded bg-[var(--color-primary)] px-2 py-1 font-mono text-[10px] font-bold text-white">Bed {patient.bed}</span>
        </div>
        <div className="flex items-center gap-3">
          <div className="grid h-12 w-12 shrink-0 place-items-center rounded-lg bg-[var(--color-surface-container-high)] text-base font-bold text-[var(--color-primary)]">{initials}</div>
          <div className="min-w-0"><h2 className="truncate text-lg font-extrabold">{patient.name}</h2><p className="eyebrow mt-1">MRN {patient.id}</p></div>
        </div>
        <div className="mt-4 grid grid-cols-3 divide-x divide-[var(--color-outline-variant)] border-y border-[var(--color-outline-variant)] py-3 text-center">
          <div><p className="eyebrow">Age</p><p className="mt-1 font-mono text-sm font-bold">{patient.age}</p></div>
          <div><p className="eyebrow">Sex</p><p className="mt-1 text-sm font-bold">{patient.gender}</p></div>
          <div><p className="eyebrow">Blood</p><p className="mt-1 font-mono text-sm font-bold">{patient.bloodType}</p></div>
        </div>
      </section>

      {patient.allergies.length > 0 && (
        <section className="border-b border-[var(--color-outline-variant)] bg-[var(--color-error-container)] p-5 text-[var(--color-error)]">
          <h3 className="flex items-center gap-2 text-xs font-bold"><AlertTriangle size={16} /> Active allergies</h3>
          <p className="mt-2 text-sm font-semibold">{patient.allergies.join(', ')}</p>
        </section>
      )}

      <section className="border-b border-[var(--color-outline-variant)] p-5">
        <div className="flex items-center justify-between">
          <h3 className="flex items-center gap-2 text-sm font-bold"><BrainCircuit size={17} className="text-[var(--color-primary)]" /> Edge analysis</h3>
          <span className="eyebrow text-[var(--color-success)]">Tier 0-3 active</span>
        </div>
        <div className="mt-4 border-l-2 border-[var(--color-primary-container)] pl-3">
          <p className="eyebrow">Detected rhythm</p>
          <p className="mt-1 flex items-center gap-2 text-sm font-bold text-[var(--color-primary)]"><CheckCircle2 size={15} /> {decodeRhythm(telemetry.rhythm_flags)}</p>
          <p className="mt-2 font-mono text-[10px] text-[var(--color-on-surface-variant)]">Model confidence {confidence}</p>
        </div>
        <dl className="mt-4 divide-y divide-[var(--color-surface-container-high)] text-xs">
          <div className="flex justify-between py-2.5"><dt className="text-[var(--color-on-surface-variant)]">PAC burden</dt><dd className="font-mono font-bold">{telemetry.pac_burden_pct ?? 0}%</dd></div>
          <div className="flex justify-between py-2.5"><dt className="text-[var(--color-on-surface-variant)]">PVC burden</dt><dd className="font-mono font-bold">{telemetry.pvc_burden_pct ?? 0}%</dd></div>
          <div className="flex justify-between py-2.5"><dt className="text-[var(--color-on-surface-variant)]">SDNN / RMSSD</dt><dd className="font-mono font-bold">{telemetry.sdnn_ms ?? 0} / {telemetry.rmssd_ms ?? 0} ms</dd></div>
        </dl>
      </section>

      <section className="border-b border-[var(--color-outline-variant)] p-5">
        <h3 className="text-sm font-bold">Medical history</h3>
        {patient.medicalHistory.length === 0 ? (
          <p className="mt-3 text-xs text-[var(--color-on-surface-variant)]">No medical history recorded.</p>
        ) : (
          <ul className="mt-3 space-y-2 text-xs text-[var(--color-on-surface-variant)]">
            {patient.medicalHistory.map((item) => <li key={item} className="flex gap-2"><span className="mt-1.5 h-1.5 w-1.5 shrink-0 rounded-full bg-[var(--color-primary)]" />{item}</li>)}
          </ul>
        )}
      </section>

      <section className="space-y-2 p-5">
        <button onClick={onExportEcg} disabled={!canExportEcg || exportBusy} className="button-primary w-full">
          {exportBusy ? <RefreshCw size={16} className="animate-spin" /> : <FileDown size={16} />} Export event ECG
        </button>
        <button onClick={onPagePhysician} disabled={pageBusy} className="button-secondary w-full">
          {pageBusy ? <RefreshCw size={16} className="animate-spin" /> : <PhoneCall size={16} />} Page duty physician
        </button>
        {actionMessage && <p className="mt-3 rounded border border-[var(--color-outline-variant)] bg-white p-2.5 text-[11px] text-[var(--color-on-surface-variant)]" role="status">{actionMessage}</p>}
      </section>
    </aside>
  );
};
