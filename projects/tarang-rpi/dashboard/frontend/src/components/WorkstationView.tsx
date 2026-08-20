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
    return { label: 'Ventricular rhythm requires immediate review', detail: 'An event snapshot has been captured for clinical assessment.', tone: 'critical', icon: ShieldAlert };
  }
  if ((flags & 0x01) !== 0 || event?.patternType === 'AFib') {
    return { label: 'Atrial fibrillation pattern detected', detail: 'RR irregularity crossed the configured clinical threshold.', tone: 'warning', icon: AlertTriangle };
  }
  if (event?.patternType) {
    return { label: `${event.patternType} pattern recorded`, detail: 'The event is available in the clinical event log below.', tone: 'warning', icon: AlertTriangle };
  }
  return { label: 'Normal sinus rhythm', detail: 'Event-driven monitoring is active and no current escalation is required.', tone: 'normal', icon: CheckCircle2 };
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
    ? 'border-l-4 border-l-[var(--cardiac-rose)] border-[var(--line)] bg-[#fff1f2] text-[var(--cardiac-rose)]'
    : rhythm.tone === 'warning'
      ? 'border-l-4 border-l-[var(--amber-alert)] border-[var(--line)] bg-[#fffbeb] text-[var(--amber-alert)]'
      : 'border-l-4 border-l-[var(--clinical-teal)] border-[var(--line)] bg-[#f0fdf4] text-[var(--clinical-teal)]';

  const vitalCards = [
    {
      label: 'Heart Rate',
      tag: 'ECG + PPG FUSED',
      value: vitals.heartRateBpm ?? '--',
      unit: 'bpm',
      reference: '60 - 100',
      source: 'Auto-validated R-peak / PPG',
      icon: HeartPulse,
      accent: 'var(--cardiac-rose)',
      trend: vitals.heartRateBpm && vitals.heartRateBpm > 100 ? TrendingUp : TrendingDown,
      compact: false,
    },
    {
      label: 'Oxygen Saturation',
      tag: 'SpO2 OPTICAL',
      value: vitals.spo2Pct ?? '--',
      unit: '%',
      reference: '95 - 100',
      source: 'MAX30102 AC/DC ratio',
      icon: Waves,
      accent: 'var(--deep-ocean)',
      trend: vitals.spo2Pct && vitals.spo2Pct < 95 ? TrendingDown : TrendingUp,
      compact: false,
    },
    {
      label: 'Ectopy Burden',
      tag: '5-MIN AI WINDOW',
      value: `${analytics.pvcBurdenPct.toFixed(1)} / ${analytics.pacBurdenPct.toFixed(1)}`,
      unit: '%',
      reference: '< 5.0',
      source: 'PVC / PAC Arrhythmia index',
      icon: Activity,
      accent: 'var(--accent)',
      trend: analytics.pvcBurdenPct + analytics.pacBurdenPct > 5 ? TrendingUp : TrendingDown,
      compact: true,
    },
  ];

  return (
    <div className="view-frame view-enter">
      <header className="view-header">
        <div>
          <div className="mb-1.5 flex flex-wrap items-center gap-2.5">
            <span className="discovery-eyebrow">Bed {patient.bed} • MRN {patient.id}</span>
            {patient.allergies.length > 0 && (
              <span className="inline-flex items-center gap-1 rounded-full bg-[#fee2e2] px-2 py-0.5 font-mono text-[10px] font-bold text-[var(--cardiac-rose)] border border-[#fca5a5]">
                <AlertTriangle size={11} /> {patient.allergies.join(', ')}
              </span>
            )}
          </div>
          <h1>{patient.name}</h1>
          <p>{patient.age} yrs • {patient.gender} • Admitted {patient.admitDate} • Attending: {patient.attendingPhysician}</p>
        </div>
        <div className="text-right">
          <p className="eyebrow">Last Synchronized</p>
          <p className="mt-0.5 font-mono text-xs font-bold text-[var(--ink)]">{formatTime(vitals.ts)}</p>
        </div>
      </header>

      <section className={`mb-3.5 sm:mb-5 flex items-center justify-between gap-3 sm:gap-5 rounded-lg border px-4 py-2.5 shadow-sm ${rhythmTone}`} aria-live="polite">
        <div className="flex items-center gap-3">
          <RhythmIcon size={18} className="shrink-0" />
          <div>
            <h2 className="text-xs sm:text-sm font-bold tracking-tight">{rhythm.label}</h2>
            <p className="text-[11px] opacity-80">{rhythm.detail}</p>
          </div>
        </div>
        <span className="font-mono text-[10px] font-semibold uppercase tracking-wider hidden md:block opacity-75">
          {latestEvent ? `Event #${latestEvent.id ?? 'live'}` : 'Tier 0-3 Active'}
        </span>
      </section>

      <section className="grid grid-cols-3 gap-3 sm:gap-4 max-sm:grid-cols-1" aria-label="Current vital signs">
        {vitalCards.map((metric) => {
          const Icon = metric.icon;
          const Trend = metric.trend;
          return (
            <article key={metric.label} className="card-clinical min-h-[110px] sm:min-h-[145px] p-3.5 sm:p-4 flex flex-col justify-between relative overflow-hidden group">
              <div className="flex items-center justify-between">
                <div className="flex items-center gap-1.5">
                  <span className="h-1.5 w-1.5 rounded-full" style={{ backgroundColor: metric.accent }} />
                  <span className="discovery-eyebrow !text-[10px] !text-[var(--ink)]">{metric.label}</span>
                </div>
                <span className="font-mono text-[9px] font-bold px-1.5 py-0.5 rounded bg-[var(--paper-2)] text-[var(--muted)] border border-[var(--line-soft)]">
                  {metric.tag}
                </span>
              </div>
              
              <div className="my-2 sm:my-2.5 flex items-baseline justify-between">
                <div className="flex items-baseline gap-1.5">
                  <span className={`font-mono font-bold tracking-tight text-[var(--ink)] leading-none ${metric.compact ? 'text-2xl sm:text-3xl lg:text-4xl' : 'text-3xl sm:text-4xl lg:text-5xl'}`}>
                    {metric.value}
                  </span>
                  <span className="font-mono text-[11px] font-semibold text-[var(--muted)]">{metric.unit}</span>
                </div>
                <div className="p-1 rounded-full bg-[var(--paper-2)] text-[var(--muted)] group-hover:text-[var(--ink)] transition-colors">
                  <Trend size={14} />
                </div>
              </div>

              <div className="flex items-center justify-between border-t border-[var(--line-soft)] pt-2 text-[10px]">
                <span className="truncate text-[var(--muted)] max-w-[65%]">{metric.source}</span>
                <span className="font-mono font-medium text-[var(--ink-soft)]">Ref {metric.reference}</span>
              </div>
            </article>
          );
        })}
      </section>

      <section className="mt-3.5 sm:mt-5">
        <WaveformCanvas currentEvent={latestEvent} activeSnippet={activeSnippet} onClearSnapshot={onClearSnapshot} />
      </section>

      <section className="mt-5 grid grid-cols-[minmax(0,1fr)_340px] gap-5 max-xl:grid-cols-1">
        <div className="clinical-panel overflow-hidden bg-white">
          <div className="flex items-center justify-between border-b border-[var(--color-outline-variant)] px-5 py-4">
            <div><h2 className="text-sm font-bold">Clinical event log</h2><p className="mt-1 text-xs text-[var(--color-on-surface-variant)]">Most recent edge-detected rhythm events</p></div>
            <Clock3 size={18} className="text-[var(--color-primary)]" />
          </div>
          {glitchTicker.length === 0 ? (
            <div className="flex items-center gap-3 px-5 py-8 text-sm text-[var(--color-on-surface-variant)]"><CheckCircle2 size={19} className="text-[var(--color-success)]" /> No rhythm events in this session.</div>
          ) : (
            <div className="divide-y divide-[var(--color-surface-container-high)]">
              {glitchTicker.slice(0, 6).map((event) => (
                <div key={event.id ?? event.ts} className="grid grid-cols-[110px_1fr_auto] items-center gap-4 px-5 py-3 max-sm:grid-cols-[1fr_auto]">
                  <span className="eyebrow max-sm:hidden">{formatTime(event.ts)}</span>
                  <div><p className="text-sm font-bold">{event.patternType || (event.rhythmStatus === 1 ? 'Atrial fibrillation' : 'Rhythm event')}</p><p className="eyebrow mt-1">Confidence {event.confidence ? `${Math.round(event.confidence * 100)}%` : 'not reported'}</p></div>
                  <button className="button-quiet" onClick={() => onSelectEvent?.(event)} disabled={!event.id || loadingEventId === event.id}>
                    {loadingEventId === event.id ? <LoaderCircle size={15} className="animate-spin" /> : <Activity size={15} />} View waveform
                  </button>
                </div>
              ))}
            </div>
          )}
        </div>

        <aside className="clinical-panel bg-[var(--color-surface)] p-5">
          <div className="flex items-center justify-between border-b border-[var(--color-outline-variant)] pb-3">
            <h2 className="flex items-center gap-2 text-sm font-bold"><Cpu size={17} className="text-[var(--color-primary)]" /> Edge inference</h2>
            <span className="status-dot pulse-dot text-[var(--color-success)]" />
          </div>
          <dl className="mt-2 divide-y divide-[var(--color-surface-container-high)] text-sm">
            <div className="flex justify-between py-3"><dt className="text-[var(--color-on-surface-variant)]">AI duty cycle</dt><dd className="font-mono font-bold">{analytics.aiDutyCyclePct.toFixed(1)}%</dd></div>
            <div className="flex justify-between py-3"><dt className="text-[var(--color-on-surface-variant)]">EM2 sleep</dt><dd className="font-mono font-bold">{analytics.em2SleepPct.toFixed(1)}%</dd></div>
            <div className="flex justify-between py-3"><dt className="text-[var(--color-on-surface-variant)]">SDNN</dt><dd className="font-mono font-bold">{analytics.sdnn.toFixed(0)} ms</dd></div>
            <div className="flex justify-between py-3"><dt className="text-[var(--color-on-surface-variant)]">RMSSD</dt><dd className="font-mono font-bold">{analytics.rmssd.toFixed(0)} ms</dd></div>
          </dl>
        </aside>
      </section>
    </div>
  );
};
