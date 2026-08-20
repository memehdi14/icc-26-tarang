'use client';

import React from 'react';
import {
  Activity,
  AlertTriangle,
  CheckCircle2,
  Clock3,
  Cpu,
  HeartPulse,
  LoaderCircle,
  ShieldAlert,
  TrendingDown,
  TrendingUp,
  Waves,
} from 'lucide-react';
import { Analytics5Min, ClinicalEvent, EcgSnippet, PatientInfo, VitalsSample } from '../types/telemetry';
import { WaveformCanvas } from './WaveformCanvas';

interface WorkstationViewProps {
  vitals: VitalsSample;
  analytics: Analytics5Min;
  latestEvent?: ClinicalEvent | null;
  activeSnippet?: EcgSnippet | null;
  glitchTicker?: ClinicalEvent[];
  patient: PatientInfo;
  onClearSnapshot?: () => void;
  onSelectEvent?: (event: ClinicalEvent) => void;
  loadingEventId?: number | null;
}

function formatTime(value?: string | null): string {
  if (!value) return 'Awaiting sync';
  const date = new Date(value);
  return Number.isNaN(date.getTime()) ? value : date.toLocaleTimeString([], { hour: '2-digit', minute: '2-digit', second: '2-digit' });
}

function rhythmPresentation(event?: ClinicalEvent | null) {
  const flags = event?.rhythmStatus ?? 0;
  if ((flags & 0x80) !== 0 || event?.patternType === 'VT' || event?.patternType === 'V-Run') {
    return { label: 'Ventricular tachycardia alert', detail: 'Immediate clinical review required.', tone: 'critical', icon: ShieldAlert };
  }
  if ((flags & 0x01) !== 0 || event?.patternType === 'AFib') {
    return { label: 'Atrial fibrillation detected', detail: 'RR irregularity crossed clinical threshold.', tone: 'warning', icon: AlertTriangle };
  }
  if (event?.patternType) {
    return { label: `${event.patternType} recorded`, detail: 'Event snapshot available in history log.', tone: 'warning', icon: AlertTriangle };
  }
  return { label: 'Normal sinus rhythm', detail: 'No active clinical alerts.', tone: 'normal', icon: CheckCircle2 };
}

export const WorkstationView: React.FC<WorkstationViewProps> = ({
  vitals,
  analytics,
  latestEvent,
  activeSnippet,
  glitchTicker = [],
  patient,
  onClearSnapshot,
  onSelectEvent,
  loadingEventId,
}) => {
  const rhythm = rhythmPresentation(latestEvent);
  const RhythmIcon = rhythm.icon;
  const rhythmTone = rhythm.tone === 'critical'
    ? 'border border-red-300 bg-red-50 text-red-800'
    : rhythm.tone === 'warning'
      ? 'border border-amber-300 bg-amber-50 text-amber-800'
      : 'border border-emerald-300 bg-emerald-50 text-emerald-800';

  return (
    <div className="view-frame view-enter">
      {/* 1. Patient Header */}
      <header className="view-header !pb-3">
        <div>
          <div className="mb-1 flex flex-wrap items-center gap-2">
            <span className="text-xs font-semibold text-[var(--ink)] flex items-center gap-1">
              <span className="text-[var(--accent)] text-[10px]">✦</span> Bed {patient.bed}
            </span>
            <span className="text-xs text-[var(--muted)]">•</span>
            <span className="text-xs font-mono text-[var(--muted)]">MRN {patient.id}</span>
            {patient.allergies.length > 0 && (
              <span className="rounded-full bg-red-100 border border-red-200 px-2.5 py-0.5 text-[11px] font-semibold text-red-700">
                ⚠ Allergies: {patient.allergies.join(', ')}
              </span>
            )}
          </div>
          <h1 className="text-2xl font-bold text-[var(--ink)]">{patient.name}</h1>
          <p className="text-xs text-[var(--ink-soft)] mt-0.5">
            {patient.age} years • {patient.gender} • Admitted {patient.admitDate} • Attending: {patient.attendingPhysician}
          </p>
        </div>
        <div className="text-right max-sm:text-left">
          <p className="text-[10px] uppercase tracking-wider text-[var(--muted)] font-medium">Last synchronized</p>
          <p className="font-mono text-xs font-bold text-[var(--ink)] mt-0.5">{formatTime(vitals.ts)}</p>
        </div>
      </header>

      {/* 2. Rhythm Status Alert Banner */}
      <section className={`mb-4 flex items-center justify-between gap-3 rounded-lg px-4 py-2.5 ${rhythmTone}`} aria-live="polite">
        <div className="flex items-center gap-2.5">
          <RhythmIcon size={18} className="shrink-0" />
          <div>
            <h2 className="text-xs sm:text-sm font-bold tracking-tight">{rhythm.label}</h2>
            <p className="text-[11px] opacity-90">{rhythm.detail}</p>
          </div>
        </div>
        <span className="font-mono text-[10px] font-semibold hidden md:block opacity-75">
          {latestEvent ? `Event #${latestEvent.id ?? 'live'}` : 'Monitoring active'}
        </span>
      </section>

      {/* 3. HERO: Physiological ECG Waveform */}
      <section className="mb-4">
        <WaveformCanvas currentEvent={latestEvent} activeSnippet={activeSnippet} onClearSnapshot={onClearSnapshot} />
      </section>

      {/* 4. Vital Signs (Prominent Physiological Numerals) */}
      <section className="grid grid-cols-3 gap-3 sm:gap-4 max-sm:grid-cols-1" aria-label="Current vital signs">
        <article className="rounded-lg border border-[var(--line)] bg-white p-3.5 sm:p-4 shadow-xs">
          <div className="flex items-center justify-between text-xs text-[var(--muted)] font-medium">
            <span>Heart rate</span>
            <span className="font-mono text-[10px]">Ref 60–100</span>
          </div>
          <div className="my-1.5 flex items-baseline gap-1.5">
            <span className="font-mono text-3xl sm:text-4xl font-bold tracking-tight text-[var(--ink)]">
              {vitals.heartRateBpm ?? '--'}
            </span>
            <span className="font-mono text-xs text-[var(--muted)]">bpm</span>
          </div>
          <p className="text-[10px] text-[var(--muted)] truncate">Fused ECG / optical pulse</p>
        </article>

        <article className="rounded-lg border border-[var(--line)] bg-white p-3.5 sm:p-4 shadow-xs">
          <div className="flex items-center justify-between text-xs text-[var(--muted)] font-medium">
            <span>Blood oxygen (SpO₂)</span>
            <span className="font-mono text-[10px]">Ref 95–100</span>
          </div>
          <div className="my-1.5 flex items-baseline gap-1.5">
            <span className="font-mono text-3xl sm:text-4xl font-bold tracking-tight text-[var(--ink)]">
              {vitals.spo2Pct ?? '--'}
            </span>
            <span className="font-mono text-xs text-[var(--muted)]">%</span>
          </div>
          <p className="text-[10px] text-[var(--muted)] truncate">Optical saturation</p>
        </article>

        <article className="rounded-lg border border-[var(--line)] bg-white p-3.5 sm:p-4 shadow-xs">
          <div className="flex items-center justify-between text-xs text-[var(--muted)] font-medium">
            <span>Arrhythmia burden (PVC / PAC)</span>
            <span className="font-mono text-[10px]">Ref &lt; 5%</span>
          </div>
          <div className="my-1.5 flex items-baseline gap-1.5">
            <span className="font-mono text-2xl sm:text-3xl font-bold tracking-tight text-[var(--ink)]">
              {analytics.pvcBurdenPct.toFixed(1)} / {analytics.pacBurdenPct.toFixed(1)}
            </span>
            <span className="font-mono text-xs text-[var(--muted)]">%</span>
          </div>
          <p className="text-[10px] text-[var(--muted)] truncate">5-minute rolling window</p>
        </article>
      </section>

      {/* 5. Clinical Event Log & Technical Diagnostics */}
      <section className="mt-4 grid grid-cols-[minmax(0,1fr)_320px] gap-4 max-xl:grid-cols-1">
        <div className="rounded-lg border border-[var(--line)] bg-white overflow-hidden shadow-xs">
          <div className="flex items-center justify-between border-b border-[var(--line)] px-4 py-3 bg-[var(--paper-2)]">
            <h2 className="text-xs font-bold text-[var(--ink)] uppercase tracking-wider">Recent rhythm events</h2>
            <Clock3 size={15} className="text-[var(--muted)]" />
          </div>
          {glitchTicker.length === 0 ? (
            <div className="flex items-center gap-2.5 px-4 py-6 text-xs text-[var(--muted)]">
              <CheckCircle2 size={16} className="text-[var(--clinical-teal)]" />
              <span>No arrhythmia events flagged in this monitoring session.</span>
            </div>
          ) : (
            <div className="divide-y divide-[var(--line-soft)]">
              {glitchTicker.slice(0, 5).map((event) => (
                <div key={event.id ?? event.ts} className="grid grid-cols-[100px_1fr_auto] items-center gap-3 px-4 py-2.5 text-xs max-sm:grid-cols-[1fr_auto]">
                  <span className="font-mono text-[11px] text-[var(--muted)] max-sm:hidden">{formatTime(event.ts)}</span>
                  <div>
                    <p className="font-semibold text-[var(--ink)]">{event.patternType || (event.rhythmStatus === 1 ? 'Atrial fibrillation' : 'Rhythm anomaly')}</p>
                    <p className="text-[10px] text-[var(--muted)]">Confidence {event.confidence ? `${Math.round(event.confidence * 100)}%` : 'unspecified'}</p>
                  </div>
                  <button
                    className="discovery-pill-secondary !py-0.5 !px-2 !min-h-[24px] !text-[10px]"
                    onClick={() => onSelectEvent?.(event)}
                    disabled={!event.id || loadingEventId === event.id}
                  >
                    {loadingEventId === event.id ? <LoaderCircle size={12} className="animate-spin" /> : <Activity size={12} />} View waveform
                  </button>
                </div>
              ))}
            </div>
          )}
        </div>

        <aside className="rounded-lg border border-[var(--line)] bg-white p-4 shadow-xs">
          <div className="flex items-center justify-between border-b border-[var(--line-soft)] pb-2.5">
            <h2 className="flex items-center gap-2 text-xs font-bold text-[var(--ink)] uppercase tracking-wider">
              <Cpu size={14} className="text-[var(--clinical-teal)]" /> Device health & HRV
            </h2>
            <span className="h-1.5 w-1.5 rounded-full bg-[var(--clinical-teal)]" />
          </div>
          <dl className="divide-y divide-[var(--line-soft)] text-xs">
            <div className="flex justify-between py-2.5"><dt className="text-[var(--muted)]">AI duty cycle</dt><dd className="font-mono font-semibold text-[var(--ink)]">{analytics.aiDutyCyclePct.toFixed(1)}%</dd></div>
            <div className="flex justify-between py-2.5"><dt className="text-[var(--muted)]">Deep sleep (EM2)</dt><dd className="font-mono font-semibold text-[var(--ink)]">{analytics.em2SleepPct.toFixed(1)}%</dd></div>
            <div className="flex justify-between py-2.5"><dt className="text-[var(--muted)]">SDNN (HRV)</dt><dd className="font-mono font-semibold text-[var(--ink)]">{analytics.sdnn.toFixed(0)} ms</dd></div>
            <div className="flex justify-between py-2.5"><dt className="text-[var(--muted)]">RMSSD (HRV)</dt><dd className="font-mono font-semibold text-[var(--ink)]">{analytics.rmssd.toFixed(0)} ms</dd></div>
          </dl>
        </aside>
      </section>
    </div>
  );
};
