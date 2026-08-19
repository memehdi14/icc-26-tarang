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
  if (event?.rhythmStatus === 2 || event?.patternType === 'VT' || event?.patternType === 'V-Run') {
    return { label: 'Ventricular rhythm requires immediate review', detail: 'An event snapshot has been captured for clinical assessment.', tone: 'critical', icon: ShieldAlert };
  }
  if (event?.rhythmStatus === 1 || event?.patternType === 'AFib') {
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
    ? 'border-[var(--color-error)] bg-[var(--color-error-container)] text-[var(--color-error)]'
    : rhythm.tone === 'warning'
      ? 'border-[#d49a3f] bg-[#fff7ea] text-[var(--color-warning)]'
      : 'border-[var(--color-primary-fixed-dim)] bg-[#f2fbf8] text-[var(--color-primary)]';

  const vitalCards = [
    {
      label: 'Heart rate',
      value: vitals.heartRateBpm ?? '--',
      unit: 'bpm',
      reference: '60-100',
      source: 'ECG + PPG fused',
      icon: HeartPulse,
      color: 'var(--color-secondary)',
      trend: vitals.heartRateBpm && vitals.heartRateBpm > 100 ? TrendingUp : TrendingDown,
      compact: false,
    },
    {
      label: 'SpO2',
      value: vitals.spo2Pct ?? '--',
      unit: '%',
      reference: '95-100',
      source: 'MAX30102 optical',
      icon: Waves,
      color: 'var(--color-tertiary)',
      trend: vitals.spo2Pct && vitals.spo2Pct < 95 ? TrendingDown : TrendingUp,
      compact: false,
    },
    {
      label: 'Ectopy burden',
      value: `${analytics.pvcBurdenPct.toFixed(1)} / ${analytics.pacBurdenPct.toFixed(1)}`,
      unit: '%',
      reference: '< 5.0',
      source: 'PVC / PAC, 5-minute window',
      icon: Activity,
      color: 'var(--color-primary-container)',
      trend: analytics.pvcBurdenPct + analytics.pacBurdenPct > 5 ? TrendingUp : TrendingDown,
      compact: true,
    },
  ];

  return (
    <div className="view-frame view-enter">
      <header className="view-header">
        <div>
          <div className="mb-2 flex flex-wrap items-center gap-3">
            <p className="eyebrow text-[var(--color-primary)]">Bed {patient.bed} / MRN {patient.id}</p>
            {patient.allergies.length > 0 && (
              <span className="inline-flex items-center gap-1.5 rounded-full bg-[var(--color-error-container)] px-2.5 py-1 text-[11px] font-bold text-[var(--color-error)]">
                <AlertTriangle size={13} /> {patient.allergies.join(', ')} allergy
              </span>
            )}
          </div>
          <h1>{patient.name}</h1>
          <p>{patient.age} years / {patient.gender} / Admitted {patient.admitDate}</p>
        </div>
        <div className="text-right">
          <p className="eyebrow">Last telemetry</p>
          <p className="mt-1 font-mono text-sm font-bold">{formatTime(vitals.ts)}</p>
        </div>
      </header>

      <section className={`mb-5 flex items-center justify-between gap-5 rounded-md border px-4 py-3 ${rhythmTone}`} aria-live="polite">
        <div className="flex items-center gap-3">
          <RhythmIcon size={20} />
          <div><h2 className="text-sm font-bold">{rhythm.label}</h2><p className="mt-0.5 text-xs opacity-80">{rhythm.detail}</p></div>
        </div>
        <span className="eyebrow hidden shrink-0 md:block">{latestEvent ? `Event ${latestEvent.id ?? 'live'}` : 'Continuous assessment'}</span>
      </section>

      <section className="grid grid-cols-3 gap-4 max-xl:grid-cols-1" aria-label="Current vital signs">
        {vitalCards.map((metric) => {
          const Icon = metric.icon;
          const Trend = metric.trend;
          return (
            <article key={metric.label} className="card-clinical min-h-[178px] p-5" style={{ borderTopColor: metric.color, borderTopWidth: 3 }}>
              <div className="flex items-center justify-between" style={{ color: metric.color }}>
                <p className="flex items-center gap-2 text-sm font-bold"><Icon size={18} /> {metric.label}</p>
                <Trend size={18} />
              </div>
              <div className="mt-5 flex items-end gap-2">
                <span className={`whitespace-nowrap font-mono font-bold leading-none ${metric.compact ? 'text-4xl' : 'text-5xl'}`} style={{ color: metric.color }}>{metric.value}</span>
                <span className="mb-1 font-mono text-xs text-[var(--color-on-surface-variant)]">{metric.unit}</span>
              </div>
              <div className="mt-5 flex items-center justify-between border-t border-[var(--color-surface-container-high)] pt-3 text-[11px]">
                <span className="font-medium text-[var(--color-on-surface-variant)]">{metric.source}</span>
                <span className="font-mono">Ref {metric.reference}</span>
              </div>
            </article>
          );
        })}
      </section>

      <section className="mt-5">
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
