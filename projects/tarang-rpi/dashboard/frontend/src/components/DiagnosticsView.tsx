'use client';

import React, { useEffect, useState } from 'react';
import {
  Activity,
  AlertTriangle,
  Battery,
  Bluetooth,
  CheckCircle2,
  Cpu,
  Gauge,
  HeartPulse,
  Radio,
  TimerReset,
  Wifi,
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
    const timer = window.setInterval(() => setIsStale(Date.now() - lastSeenMs > 3500), 1000);
    return () => window.clearInterval(timer);
  }, [lastSeenMs]);

  const health = deviceHealth;
  const rssi = health?.bleRssi ?? diagnostics.rssiDbm ?? -100;
  const isConnected = diagnostics.bleConnected && !isStale;

  return (
    <div className="view-frame view-enter">
      <header className="view-header !pb-3">
        <div>
          <span className="text-xs font-semibold text-[var(--muted)]">Hardware telemetry</span>
          <h1 className="text-2xl font-bold text-[var(--ink)]">Device health</h1>
          <p className="text-xs text-[var(--ink-soft)] mt-0.5">Sensor contact, link quality, and edge hardware integrity.</p>
        </div>
        <span className={`inline-flex items-center gap-1.5 rounded px-2.5 py-1 font-mono text-xs font-medium ${isConnected ? 'bg-emerald-50 text-emerald-800 border border-emerald-200' : 'bg-red-50 text-red-800 border border-red-200'}`}>
          <span className={`h-1.5 w-1.5 rounded-full ${isConnected ? 'bg-emerald-600' : 'bg-red-600'}`} />
          {isConnected ? '● Connected' : isStale ? '● Stale telemetry' : '○ Disconnected'}
        </span>
      </header>

      {isStale && (
        <div className="mb-4 flex items-center gap-2.5 rounded-lg border border-red-200 bg-red-50 px-4 py-2.5 text-xs text-red-700" role="alert">
          <AlertTriangle size={15} />
          <span>Device telemetry paused. Last packet received {Math.round((Date.now() - lastSeenMs) / 1000)}s ago.</span>
        </div>
      )}

      {/* Primary Device Overview */}
      <section className="grid grid-cols-3 gap-4 max-md:grid-cols-1">
        {/* Battery */}
        <article className="rounded-lg border border-[var(--line)] bg-white p-4 shadow-xs">
          <div className="flex items-center justify-between text-xs text-[var(--muted)] font-medium">
            <span>Battery state</span>
            <Battery size={16} className="text-[var(--ink)]" />
          </div>
          <div className="my-2">
            <p className="font-mono text-3xl font-bold text-[var(--ink)]">
              {health?.batteryPct == null || health.batteryPct === 255 ? 'USB powered' : `${health.batteryPct}%`}
            </p>
          </div>
          <p className="text-[11px] text-[var(--muted)]">
            {health?.batteryPct == null || health.batteryPct === 255 ? 'External 5V supply connected' : '3.7V LiPo pod battery'}
          </p>
        </article>

        {/* Connection Link */}
        <article className="rounded-lg border border-[var(--line)] bg-white p-4 shadow-xs">
          <div className="flex items-center justify-between text-xs text-[var(--muted)] font-medium">
            <span>BLE link & latency</span>
            <Radio size={16} className="text-[var(--clinical-teal)]" />
          </div>
          <div className="my-2 flex items-baseline gap-2">
            <span className="font-mono text-3xl font-bold text-[var(--ink)]">{diagnostics.latencyMs || '--'}</span>
            <span className="font-mono text-xs text-[var(--muted)]">ms delay</span>
          </div>
          <p className="text-[11px] text-[var(--muted)]">RSSI: {rssi > -100 ? `${rssi} dBm` : 'Scanning'}</p>
        </article>

        {/* Transmission & Packets */}
        <article className="rounded-lg border border-[var(--line)] bg-white p-4 shadow-xs">
          <div className="flex items-center justify-between text-xs text-[var(--muted)] font-medium">
            <span>Packets delivered</span>
            <Activity size={16} className="text-[var(--deep-ocean)]" />
          </div>
          <div className="my-2 flex items-baseline gap-2">
            <span className="font-mono text-3xl font-bold text-[var(--ink)]">{diagnostics.packetsReceived.toLocaleString()}</span>
            <span className="font-mono text-xs text-[var(--muted)]">({diagnostics.packetsDropped} dropped)</span>
          </div>
          <p className="text-[11px] text-[var(--muted)]">Mode A event-driven streaming</p>
        </article>
      </section>

      {/* Sensor Status List & Device Identity */}
      <section className="mt-4 grid grid-cols-[1fr_340px] gap-4 max-lg:grid-cols-1">
        {/* Sensor Contact Status */}
        <article className="rounded-lg border border-[var(--line)] bg-white overflow-hidden shadow-xs">
          <div className="border-b border-[var(--line)] px-4 py-3 bg-[var(--paper-2)]">
            <h2 className="text-xs font-bold uppercase tracking-wider text-[var(--ink)]">Sensors & acquisition status</h2>
          </div>
          <div className="divide-y divide-[var(--line-soft)] text-xs">
            <div className="flex items-center justify-between px-4 py-3">
              <div className="flex items-center gap-2.5">
                <HeartPulse size={16} className="text-[var(--clinical-teal)]" />
                <div>
                  <p className="font-semibold text-[var(--ink)]">ECG analog front-end (AD8232 / IADC)</p>
                  <p className="text-[10px] text-[var(--muted)]">Signal Quality Index (SQI): {health ? `${health.ecgSqi}/255` : 'Active'}</p>
                </div>
              </div>
              <span className="font-medium text-emerald-700 bg-emerald-50 px-2 py-0.5 rounded">● Good</span>
            </div>

            <div className="flex items-center justify-between px-4 py-3">
              <div className="flex items-center gap-2.5">
                <Activity size={16} className="text-[var(--deep-ocean)]" />
                <div>
                  <p className="font-semibold text-[var(--ink)]">PPG optical pulse (MAX30102)</p>
                  <p className="text-[10px] text-[var(--muted)]">Red & IR reflection pulse stream</p>
                </div>
              </div>
              <span className={`font-medium px-2 py-0.5 rounded ${health?.ppgFingerPresent ? 'text-emerald-700 bg-emerald-50' : 'text-amber-700 bg-amber-50'}`}>
                {health?.ppgFingerPresent ? '● Contact present' : '○ Standby / No contact'}
              </span>
            </div>

            <div className="flex items-center justify-between px-4 py-3">
              <div className="flex items-center gap-2.5">
                <Gauge size={16} className="text-[var(--accent)]" />
                <div>
                  <p className="font-semibold text-[var(--ink)]">Motion cancellation IMU (MPU6050)</p>
                  <p className="text-[10px] text-[var(--muted)]">6-DOF Accelerometer & Gyroscope</p>
                </div>
              </div>
              <span className="font-medium text-emerald-700 bg-emerald-50 px-2 py-0.5 rounded">● Connected</span>
            </div>
          </div>
        </article>

        {/* Device Identity */}
        <article className="rounded-lg border border-[var(--line)] bg-white p-4 shadow-xs">
          <div className="flex items-center justify-between border-b border-[var(--line-soft)] pb-2.5">
            <h2 className="flex items-center gap-1.5 text-xs font-bold uppercase tracking-wider text-[var(--ink)]">
              <Cpu size={14} /> Device metadata
            </h2>
            <CheckCircle2 size={15} className="text-emerald-600" />
          </div>
          <dl className="divide-y divide-[var(--line-soft)] text-xs">
            <div className="py-2"><dt className="text-[10px] text-[var(--muted)] uppercase">Device name</dt><dd className="font-mono font-semibold text-[var(--ink)]">{diagnostics.deviceName || 'TARANG-2614'}</dd></div>
            <div className="py-2"><dt className="text-[10px] text-[var(--muted)] uppercase">Bluetooth address</dt><dd className="font-mono font-semibold text-[var(--ink)]">{diagnostics.deviceMac || '64:02:8F:64:26:14'}</dd></div>
            <div className="py-2"><dt className="text-[10px] text-[var(--muted)] uppercase">Firmware version</dt><dd className="font-mono font-semibold text-[var(--ink)]">v1.0.0-EFR32MG26</dd></div>
            <div className="py-2"><dt className="text-[10px] text-[var(--muted)] uppercase">Uptime</dt><dd className="font-mono font-semibold text-[var(--ink)]">{health ? formatUptime(health.uptimeS) : 'Online'}</dd></div>
          </dl>
        </article>
      </section>
    </div>
  );
};
