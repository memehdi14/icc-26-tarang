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
  collapsed?: boolean;
  onToggleCollapse?: () => void;
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
  collapsed = false,
  onToggleCollapse,
}) => {
  const confidence = telemetry.confidence ? `${((telemetry.confidence / 255) * 100).toFixed(1)}%` : 'Active';
  const initials = patient.name.split(/\s+/).map((part) => part[0]).join('').slice(0, 2).toUpperCase();

  return (
    <aside className={`patient-rail ${collapsed ? 'patient-rail--collapsed' : ''}`} aria-label="Patient clinical summary">
      {/* Patient demographics */}
      <section className="border-b border-[var(--line)] p-4">
        <div className="mb-3 flex items-center justify-between">
          <span className="text-[11px] font-semibold text-[var(--muted)] uppercase tracking-wider">Patient summary</span>
          <div className="flex items-center gap-1.5">
            <span className="rounded bg-[var(--paper-2)] border border-[var(--line)] px-2 py-0.5 font-mono text-[10px] font-bold text-[var(--ink)]">Bed {patient.bed}</span>
            {onToggleCollapse && (
              <button
                onClick={onToggleCollapse}
                className="icon-button !w-6 !h-6 !min-h-0 text-[var(--muted)] hover:text-[var(--ink)]"
                title="Collapse patient summary"
                aria-label="Collapse patient summary"
              >
                ✕
              </button>
            )}
          </div>
        </div>
        <div className="flex items-center gap-3">
          <div className="grid h-10 w-10 shrink-0 place-items-center rounded bg-[var(--paper-2)] text-sm font-bold text-[var(--ink)]">{initials}</div>
          <div className="min-w-0">
            <h2 className="truncate text-base font-bold text-[var(--ink)]">{patient.name}</h2>
            <p className="font-mono text-[11px] text-[var(--muted)]">MRN {patient.id}</p>
          </div>
        </div>
        <div className="mt-3 grid grid-cols-3 divide-x divide-[var(--line)] border-y border-[var(--line)] py-2 text-center text-xs">
          <div><p className="text-[10px] text-[var(--muted)]">Age</p><p className="font-semibold text-[var(--ink)]">{patient.age}</p></div>
          <div><p className="text-[10px] text-[var(--muted)]">Sex</p><p className="font-semibold text-[var(--ink)]">{patient.gender}</p></div>
          <div><p className="text-[10px] text-[var(--muted)]">Blood</p><p className="font-semibold text-[var(--ink)]">{patient.bloodType || 'Unknown'}</p></div>
        </div>
      </section>

      {/* Allergies banner */}
      {patient.allergies.length > 0 && (
        <section className="border-b border-red-200 bg-red-50 p-3.5 text-red-800 text-xs">
          <p className="flex items-center gap-1.5 font-semibold text-[11px] uppercase tracking-wider text-red-700">
            <AlertTriangle size={13} /> Active allergies
          </p>
          <p className="mt-1 font-medium">{patient.allergies.join(', ')}</p>
        </section>
      )}

      {/* Edge ML Assessment */}
      <section className="border-b border-[var(--line)] p-4">
        <div className="flex items-center justify-between">
          <h3 className="flex items-center gap-1.5 text-xs font-bold text-[var(--ink)] uppercase tracking-wider">
            <BrainCircuit size={14} className="text-[var(--clinical-teal)]" /> Edge rhythm analysis
          </h3>
          <span className="text-[10px] font-mono text-[var(--clinical-teal)] font-semibold">Tier 0-3</span>
        </div>
        <div className="mt-3 rounded border border-[var(--line-soft)] bg-[var(--paper-2)] p-2.5">
          <p className="text-[10px] text-[var(--muted)] uppercase tracking-wider">Detected rhythm</p>
          <p className="mt-0.5 flex items-center gap-1.5 text-xs font-bold text-[var(--ink)]">
            <CheckCircle2 size={13} className="text-[var(--clinical-teal)]" /> {decodeRhythm(telemetry.rhythm_flags)}
          </p>
          <p className="mt-1 font-mono text-[10px] text-[var(--muted)]">Model confidence {confidence}</p>
        </div>
        <dl className="mt-3 divide-y divide-[var(--line-soft)] text-xs">
          <div className="flex justify-between py-1.5"><dt className="text-[var(--muted)]">PAC burden</dt><dd className="font-mono font-semibold">{telemetry.pac_burden_pct ?? 0}%</dd></div>
          <div className="flex justify-between py-1.5"><dt className="text-[var(--muted)]">PVC burden</dt><dd className="font-mono font-semibold">{telemetry.pvc_burden_pct ?? 0}%</dd></div>
          <div className="flex justify-between py-1.5"><dt className="text-[var(--muted)]">SDNN / RMSSD</dt><dd className="font-mono font-semibold">{telemetry.sdnn_ms ?? 0} / {telemetry.rmssd_ms ?? 0} ms</dd></div>
        </dl>
      </section>

      {/* Medical History */}
      <section className="border-b border-[var(--line)] p-4">
        <h3 className="text-xs font-bold text-[var(--ink)] uppercase tracking-wider">Medical history</h3>
        {patient.medicalHistory.length === 0 ? (
          <p className="mt-2 text-xs text-[var(--muted)]">No medical history recorded.</p>
        ) : (
          <ul className="mt-2 space-y-1.5 text-xs text-[var(--ink-soft)]">
            {patient.medicalHistory.map((item) => (
              <li key={item} className="flex gap-2">
                <span className="mt-1.5 h-1 w-1 shrink-0 rounded-full bg-[var(--clinical-teal)]" />
                <span>{item}</span>
              </li>
            ))}
          </ul>
        )}
      </section>

      {/* Actions */}
      <section className="space-y-2 p-4">
        <button onClick={onExportEcg} disabled={!canExportEcg || exportBusy} className="discovery-pill-primary w-full !py-2 !text-xs justify-center">
          {exportBusy ? <RefreshCw size={14} className="animate-spin" /> : <FileDown size={14} />} <span>Export event ECG (PDF)</span>
        </button>
        <button onClick={onPagePhysician} disabled={pageBusy} className="button-quiet w-full justify-center !text-xs !border !border-[var(--line)]">
          <PhoneCall size={14} /> <span>Page duty physician</span>
        </button>
        {actionMessage && <p className="text-center font-mono text-[10px] text-[var(--clinical-teal)]">{actionMessage}</p>}
      </section>
    </aside>
  );
};
