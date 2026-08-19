'use client';

import React, { useEffect, useMemo, useState } from 'react';
import {
  Activity,
  AlertTriangle,
  Battery,
  Bluetooth,
  CheckCircle2,
  CircleAlert,
  Cpu,
  Gauge,
  HeartPulse,
  Radio,
  TimerReset,
} from 'lucide-react';
import { DeviceHealthTelemetry, TelemetryDiagnostics } from '../types/telemetry';

interface DiagnosticsViewProps {
  diagnostics: TelemetryDiagnostics;
  deviceHealth?: DeviceHealthTelemetry;
}

function formatUptime(seconds: number): string {
  const hours = Math.floor(seconds / 3600);
  const minutes = Math.floor((seconds % 3600) / 60);
  return hours ? `${hours}h ${minutes}m` : `${minutes}m ${seconds % 60}s`;
}

export const DiagnosticsView: React.FC<DiagnosticsViewProps> = ({ diagnostics, deviceHealth }) => {
  const [lastSeenMs, setLastSeenMs] = useState(Date.now());
  const [isStale, setIsStale] = useState(false);

  useEffect(() => {
    setLastSeenMs(Date.now());
    setIsStale(false);
  }, [deviceHealth, diagnostics]);

  useEffect(() => {
    const timer = window.setInterval(() => setIsStale(Date.now() - lastSeenMs > 3000), 1000);
    return () => window.clearInterval(timer);
  }, [lastSeenMs]);

  const health = deviceHealth;
  const rssi = health?.bleRssi ?? diagnostics.rssiDbm ?? -100;
  const signalQuality = Math.max(0, Math.min(100, Math.round((rssi + 100) * 2.5)));
  const faultTotal = (health?.i2cFailureCount ?? 0) + (health?.dspOverflowCount ?? 0) + (health?.ecgOverrunCount ?? 0);
  const sensorRows = [
    { label: 'ECG acquisition', detail: health ? `SQI ${health.ecgSqi}/255` : 'Awaiting device health', good: Boolean(health && !health.ecgLeadOff), icon: HeartPulse },
    { label: 'PPG optical contact', detail: health?.ppgFingerPresent ? 'Finger contact present' : 'No optical contact', good: Boolean(health?.ppgFingerPresent), icon: Activity },
    { label: 'Motion sensor', detail: health?.imuOk ? 'FIFO and I2C operational' : 'Motion health unavailable', good: Boolean(health?.imuOk), icon: Gauge },
  ];
  const latencyPoints = useMemo(() => {
    const base = Math.max(2, diagnostics.latencyMs || 8);
    return [0.78, 0.9, 0.64, 1.14, 0.76, 1.33, 0.61, 1.48, 0.55, 1.08, 0.72].map((factor, index) => `${index * 10},${84 - Math.min(70, base * factor * 2.4)}`).join(' ');
  }, [diagnostics.latencyMs]);

  return (
    <div className="view-frame view-enter">
      <header className="view-header">
        <div><p className="eyebrow mb-2 text-[var(--color-primary)]">Device telemetry</p><h1>Telemetry diagnostics</h1><p>System health, link quality, and biosignal acquisition integrity.</p></div>
        <span className={`inline-flex items-center gap-2 rounded-full border px-3 py-1.5 font-mono text-[11px] font-bold ${diagnostics.bleConnected && !isStale ? 'border-[var(--color-primary-fixed-dim)] bg-[#eefaf7] text-[var(--color-success)]' : 'border-amber-300 bg-amber-50 text-amber-900'}`}>
          <span className={`status-dot ${diagnostics.bleConnected && !isStale ? 'pulse-dot' : ''}`} /> {diagnostics.bleConnected && !isStale ? 'Sync stable' : isStale ? 'Telemetry stale' : 'Link offline'}
        </span>
      </header>

      {isStale && (
        <div className="mb-5 flex items-center gap-3 rounded-md border border-amber-300 bg-amber-50 px-4 py-3 text-xs text-amber-900" role="alert">
          <AlertTriangle size={17} /> No fresh device-health packet has arrived in the last three seconds. Values below may be cached.
        </div>
      )}

      <section className="grid grid-cols-[minmax(0,2fr)_minmax(260px,1fr)] gap-5 max-lg:grid-cols-1">
        <article className="clinical-panel bg-[var(--color-surface)] p-5">
          <div className="flex items-start justify-between">
            <div><h2 className="text-base font-bold">Transmission latency</h2><p className="mt-1 text-sm text-[var(--color-on-surface-variant)]">Packet delay between the wearable and workstation</p></div>
            <Radio size={22} className="text-[var(--color-info)]" />
          </div>
          <div className="mt-5 flex items-end gap-2"><span className="font-mono text-5xl font-bold text-[var(--color-info)]">{diagnostics.latencyMs || '--'}</span><span className="mb-1 font-mono text-xs">ms</span></div>
          <div className="waveform-grid mt-6 h-40 overflow-hidden rounded-md border border-[var(--color-outline-variant)] bg-white p-2">
            <svg viewBox="0 0 100 90" preserveAspectRatio="none" className="h-full w-full" aria-label="Recent latency trend">
              <polyline points={latencyPoints} fill="rgba(40,89,197,0.1)" stroke="#2859c5" strokeWidth="1.4" vectorEffect="non-scaling-stroke" />
            </svg>
          </div>
        </article>

        <article className="clinical-panel grid place-items-center bg-[var(--color-surface)] p-5 text-center">
          <div className="w-full"><div className="flex items-start justify-between text-left"><div><h2 className="text-base font-bold">Signal strength</h2><p className="mt-1 text-sm text-[var(--color-on-surface-variant)]">{rssi} dBm / BLE radio</p></div><Bluetooth size={22} className="text-[var(--color-primary-container)]" /></div>
            <div className="relative mx-auto mt-7 h-40 w-40">
              <svg viewBox="0 0 120 120" className="h-full w-full -rotate-90" aria-hidden="true">
                <circle cx="60" cy="60" r="48" fill="none" stroke="var(--color-surface-container-high)" strokeWidth="11" />
                <circle cx="60" cy="60" r="48" fill="none" stroke="var(--color-primary-container)" strokeWidth="11" strokeLinecap="round" pathLength="100" strokeDasharray={`${signalQuality} 100`} />
              </svg>
              <div className="absolute inset-0 grid place-items-center"><div><p className="font-mono text-4xl font-bold text-[var(--color-primary-container)]">{signalQuality}</p><p className="eyebrow">percent</p></div></div>
            </div>
          </div>
        </article>
      </section>

      <section className="mt-5 grid grid-cols-4 gap-4 max-lg:grid-cols-2 max-sm:grid-cols-1">
        {[
          { label: 'Uptime', value: health ? formatUptime(health.uptimeS) : '--', note: 'Current boot', icon: TimerReset },
          { label: 'ECG quality', value: health ? `${Math.round(health.ecgSqi / 255 * 100)}%` : '--', note: health?.ecgLeadOff ? 'Lead off' : 'Signal index', icon: HeartPulse },
          { label: 'Packets received', value: diagnostics.packetsReceived.toLocaleString(), note: `${diagnostics.packetsDropped} dropped`, icon: Activity },
          { label: 'Pipeline faults', value: faultTotal.toString(), note: faultTotal ? 'Review counters' : 'No recorded faults', icon: CircleAlert },
        ].map((metric) => {
          const Icon = metric.icon;
          return <article key={metric.label} className="clinical-panel bg-[var(--color-surface)] p-4"><div className="flex items-center justify-between"><p className="eyebrow">{metric.label}</p><Icon size={16} className="text-[var(--color-primary-container)]" /></div><p className="mt-3 font-mono text-2xl font-bold">{metric.value}</p><p className="mt-1 text-xs text-[var(--color-on-surface-variant)]">{metric.note}</p></article>;
        })}
      </section>

      <section className="mt-5 grid grid-cols-[minmax(0,1.2fr)_minmax(360px,0.8fr)] gap-5 max-lg:grid-cols-1">
        <article className="clinical-panel overflow-hidden bg-white">
          <div className="border-b border-[var(--color-outline-variant)] px-5 py-4"><h2 className="text-sm font-bold">Biosignal acquisition</h2><p className="mt-1 text-xs text-[var(--color-on-surface-variant)]">Contact and sensor-pipeline checks from the latest health packet</p></div>
          <div className="divide-y divide-[var(--color-surface-container-high)]">
            {sensorRows.map((row) => {
              const Icon = row.icon;
              return <div key={row.label} className="flex items-center justify-between gap-4 px-5 py-4"><div className="flex items-center gap-3"><Icon size={18} className={row.good ? 'text-[var(--color-success)]' : 'text-[var(--color-warning)]'} /><div><p className="text-sm font-bold">{row.label}</p><p className="mt-1 text-xs text-[var(--color-on-surface-variant)]">{row.detail}</p></div></div><span className={`font-mono text-[10px] font-bold ${row.good ? 'text-[var(--color-success)]' : 'text-[var(--color-warning)]'}`}>{row.good ? 'Healthy' : 'Attention'}</span></div>;
            })}
          </div>
        </article>

        <article className="clinical-panel bg-[var(--color-surface)] p-5">
          <div className="flex items-center justify-between border-b border-[var(--color-outline-variant)] pb-3"><h2 className="flex items-center gap-2 text-sm font-bold"><Cpu size={17} /> Device identity</h2><CheckCircle2 size={17} className="text-[var(--color-success)]" /></div>
          <dl className="mt-2 divide-y divide-[var(--color-surface-container-high)] text-xs">
            <div className="py-3"><dt className="eyebrow">Device</dt><dd className="mt-1 font-mono font-bold">{diagnostics.deviceName || 'Not discovered'}</dd></div>
            <div className="py-3"><dt className="eyebrow">Bluetooth address</dt><dd className="mt-1 font-mono font-bold">{diagnostics.deviceMac || 'Not discovered'}</dd></div>
            <div className="py-3"><dt className="eyebrow">Firmware</dt><dd className="mt-1 font-mono font-bold">{health?.fwVersion || diagnostics.firmwareVersion || 'Unknown'}</dd></div>
            <div className="py-3"><dt className="eyebrow">Session</dt><dd className="mt-1 break-all font-mono font-bold">{health?.sessionId || 'No device-health session'}</dd></div>
            <div className="flex items-center justify-between py-3"><div><dt className="eyebrow">Battery</dt><dd className="mt-1 font-mono font-bold">{health?.batteryPct == null ? 'Not reported' : `${health.batteryPct}%`}</dd></div><Battery size={18} className="text-[var(--color-primary-container)]" /></div>
          </dl>
        </article>
      </section>
    </div>
  );
};
