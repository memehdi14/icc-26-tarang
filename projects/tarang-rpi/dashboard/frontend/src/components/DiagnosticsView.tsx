'use client';

import React, { useState, useEffect } from 'react';
import { TelemetryDiagnostics, DeviceHealthTelemetry } from '../types/telemetry';
import {
  ShieldCheck, Cpu, Radio, Wifi, Zap, Activity, CheckCircle,
  HardDrive, AlertCircle, Heart, Gauge, AlertTriangle, BatteryCharging
} from 'lucide-react';

interface DiagnosticsViewProps {
  diagnostics: TelemetryDiagnostics;
  deviceHealth?: DeviceHealthTelemetry;
}

export const DiagnosticsView: React.FC<DiagnosticsViewProps> = ({ diagnostics, deviceHealth }) => {
  const [isStale, setIsStale] = useState(false);
  const [lastSeenMs, setLastSeenMs] = useState(Date.now());

  const health = deviceHealth || {
    uptimeS: 0,
    ecgLeadOff: false,
    ecgSqi: 240,
    ppgFingerPresent: true,
    imuOk: true,
    i2cFailureCount: 0,
    dspOverflowCount: 0,
    ecgOverrunCount: 0,
    bleRssi: diagnostics.rssiDbm ?? -60,
    batteryPct: null,
    fwVersion: diagnostics.firmwareVersion || '1.0.0',
    sessionId: null,
  };

  useEffect(() => {
    setLastSeenMs(Date.now());
    setIsStale(false);
  }, [deviceHealth, diagnostics]);

  useEffect(() => {
    const timer = setInterval(() => {
      const elapsed = Date.now() - lastSeenMs;
      if (elapsed > 3000) {
        setIsStale(true);
      }
    }, 1000);
    return () => clearInterval(timer);
  }, [lastSeenMs]);

  const formatUptime = (seconds: number) => {
    const hrs = Math.floor(seconds / 3600);
    const mins = Math.floor((seconds % 3600) / 60);
    const secs = seconds % 60;
    if (hrs > 0) return `${hrs}h ${mins}m ${secs}s`;
    return `${mins}m ${secs}s`;
  };

  const getFaultBadge = (count: number) => {
    if (count === 0) {
      return 'text-emerald-700 bg-emerald-50 border-emerald-200';
    }
    if (count <= 5) {
      return 'text-amber-700 bg-amber-100 border-amber-300 animate-pulse';
    }
    return 'text-rose-700 bg-rose-100 border-rose-300 font-extrabold animate-pulse';
  };

  const getRssiBars = (rssi: number | null | undefined) => {
    const val = rssi ?? -60;
    if (val >= -60) return 4;
    if (val >= -75) return 3;
    if (val >= -85) return 2;
    return 1;
  };

  return (
    <div className="space-y-6">
      {/* Staleness Warning Banner */}
      {isStale && (
        <div className="flex items-center gap-3 p-3.5 rounded-xl bg-amber-500/10 border border-amber-500/40 text-amber-900 shadow-sm animate-pulse">
          <AlertTriangle className="w-5 h-5 text-amber-600 shrink-0" />
          <div className="text-xs">
            <span className="font-bold">TELEMETRY STALE (&gt;3s latency):</span> No live health snapshots received recently. Indicators reflect last cached state.
          </div>
        </div>
      )}

      {/* Title & Header */}
      <div className="flex items-center justify-between bg-white p-4 rounded-xl border border-[var(--color-outline-variant)] shadow-sm">
        <div>
          <h1 className="text-2xl font-extrabold text-[var(--color-on-surface)] flex items-center gap-2">
            <ShieldCheck className="w-7 h-7 text-[var(--color-primary)]" />
            Telemetry Diagnostics & Device Health
          </h1>
          <p className="text-xs text-[var(--color-on-surface-variant)] mt-1">
            Real-time link status, sensor lead/contact awareness, SQI signal quality & DSP fault metrics.
          </p>
        </div>

        <div className="flex items-center gap-3">
          <span className={`px-3 py-1.5 rounded-lg text-xs font-mono font-bold border ${
            isStale ? 'bg-amber-100 text-amber-800 border-amber-300' : 'bg-[var(--color-surface-container-low)] text-[var(--color-on-surface-variant)] border-[var(--color-outline-variant)]'
          }`}>
            Uptime: {formatUptime(health.uptimeS)}
          </span>
        </div>
      </div>

      {/* Primary Status Cards */}
      <div className="grid grid-cols-4 gap-4">
        {/* Connection Link Status */}
        <div className="card-clinical p-4 space-y-2">
          <div className="flex items-center justify-between text-xs font-bold text-[var(--color-on-surface-variant)]">
            <span>BLE Connection</span>
            <Wifi className={`w-4 h-4 ${diagnostics.bleConnected && !isStale ? 'text-emerald-600' : 'text-red-500'}`} />
          </div>
          <p className={`text-xl font-mono font-extrabold flex items-center gap-2 ${diagnostics.bleConnected && !isStale ? 'text-emerald-700' : 'text-red-600'}`}>
            {diagnostics.bleConnected && !isStale ? (
              <>
                <CheckCircle className="w-5 h-5 text-emerald-600" />
                CONNECTED
              </>
            ) : (
              <>
                <AlertCircle className="w-5 h-5 text-red-600" />
                {isStale ? 'LINK PAUSED' : 'DISCONNECTED'}
              </>
            )}
          </p>
          <p className="text-[11px] font-mono text-[var(--color-on-surface-variant)] border-t border-[var(--color-outline-variant)] pt-2">
            Interval: 20 ms • Bluetooth 5.4 GATT
          </p>
        </div>

        {/* Transmission Latency */}
        <div className="card-clinical p-4 space-y-2">
          <div className="flex items-center justify-between text-xs font-bold text-[var(--color-on-surface-variant)]">
            <span>Round-Trip Latency</span>
            <Activity className="w-4 h-4 text-[var(--color-primary)]" />
          </div>
          <p className="text-xl font-mono font-extrabold text-[var(--color-on-surface)]">
            {diagnostics.latencyMs ?? 0} ms
          </p>
          <p className="text-[11px] font-mono text-[var(--color-on-surface-variant)] border-t border-[var(--color-outline-variant)] pt-2">
            Dropped: {diagnostics.packetsDropped ?? 0} pkts • Target &lt; 50ms
          </p>
        </div>

        {/* Signal Strength RSSI */}
        <div className="card-clinical p-4 space-y-2">
          <div className="flex items-center justify-between text-xs font-bold text-[var(--color-on-surface-variant)]">
            <span>Signal Strength (RSSI)</span>
            <Radio className="w-4 h-4 text-blue-600" />
          </div>
          <div className="flex items-center gap-2">
            <p className="text-xl font-mono font-extrabold text-[var(--color-on-surface)]">
              {health.bleRssi ?? diagnostics.rssiDbm ?? -60} dBm
            </p>
            <div className="flex items-end gap-0.5 h-4 mb-1">
              {[1, 2, 3, 4].map((bar) => (
                <div
                  key={bar}
                  className={`w-1 rounded-sm ${
                    bar <= getRssiBars(health.bleRssi)
                      ? 'bg-blue-600'
                      : 'bg-slate-200'
                  }`}
                  style={{ height: `${bar * 25}%` }}
                />
              ))}
            </div>
          </div>
          <p className="text-[11px] font-mono text-emerald-700 border-t border-[var(--color-outline-variant)] pt-2">
            Link Quality: {diagnostics.bleConnected ? 'Active Link' : 'No Link'}
          </p>
        </div>

        {/* Battery / System Power */}
        <div className="card-clinical p-4 space-y-2">
          <div className="flex items-center justify-between text-xs font-bold text-[var(--color-on-surface-variant)]">
            <span>EFR32 Battery Level</span>
            <Zap className="w-4 h-4 text-amber-500" />
          </div>
          <div className="flex items-center gap-2">
            <span className="px-2 py-0.5 rounded text-sm font-mono font-bold bg-slate-100 text-slate-700 border border-slate-300">
              N/A
            </span>
            <span className="text-[11px] font-mono text-slate-500">
              (No HW Fuel Gauge)
            </span>
          </div>
          <p className="text-[11px] font-mono text-[var(--color-on-surface-variant)] border-t border-[var(--color-outline-variant)] pt-2">
            Rail: VDD 3.3V Active
          </p>
        </div>
      </div>

      {/* Clinical Sensor Contact & Health Bar */}
      <div className={`card-clinical p-5 space-y-4 transition-opacity ${isStale ? 'opacity-70' : 'opacity-100'}`}>
        <div className="flex items-center justify-between border-b border-[var(--color-outline-variant)] pb-3">
          <div className="flex items-center gap-2">
            <Heart className="w-5 h-5 text-rose-600" />
            <h2 className="text-sm font-bold text-[var(--color-on-surface)] uppercase tracking-wider">
              Real-Time Sensor Contact & Lead Attachment Status
            </h2>
          </div>
          <div className="flex items-center gap-2 text-xs font-mono">
            <span className="text-[var(--color-on-surface-variant)]">ECG SQI Metric:</span>
            <span className="font-bold text-[var(--color-on-surface)]">{health.ecgSqi} / 255</span>
          </div>
        </div>

        {/* 3 Sensor Status Indicators */}
        <div className="grid grid-cols-3 gap-4">
          {/* ECG Lead Status */}
          <div className={`p-4 rounded-xl border flex items-center justify-between ${
            !health.ecgLeadOff ? 'bg-emerald-50/60 border-emerald-200' : 'bg-rose-50/80 border-rose-300'
          }`}>
            <div>
              <p className="text-xs font-bold text-[var(--color-on-surface)]">AD8232 ECG Electrodes</p>
              <p className="text-[11px] font-mono text-[var(--color-on-surface-variant)] mt-0.5">
                {!health.ecgLeadOff ? 'Skin Contact Established' : 'Electrodes Detached / Saturated'}
              </p>
            </div>
            <span className={`px-2.5 py-1 rounded text-[11px] font-mono font-bold ${
              !health.ecgLeadOff ? 'bg-emerald-200 text-emerald-800' : 'bg-rose-200 text-rose-800'
            }`}>
              {!health.ecgLeadOff ? 'ATTACHED' : 'LEAD OFF'}
            </span>
          </div>

          {/* PPG Finger Presence */}
          <div className={`p-4 rounded-xl border flex items-center justify-between ${
            health.ppgFingerPresent ? 'bg-emerald-50/60 border-emerald-200' : 'bg-amber-50/80 border-amber-300'
          }`}>
            <div>
              <p className="text-xs font-bold text-[var(--color-on-surface)]">MAX30102 PPG Optical</p>
              <p className="text-[11px] font-mono text-[var(--color-on-surface-variant)] mt-0.5">
                {health.ppgFingerPresent ? 'Tissue Contact (IR > 8k DC)' : 'No Finger Detected (Open Air)'}
              </p>
            </div>
            <span className={`px-2.5 py-1 rounded text-[11px] font-mono font-bold ${
              health.ppgFingerPresent ? 'bg-emerald-200 text-emerald-800' : 'bg-amber-200 text-amber-800'
            }`}>
              {health.ppgFingerPresent ? 'CONTACT OK' : 'NO FINGER'}
            </span>
          </div>

          {/* IMU Health */}
          <div className={`p-4 rounded-xl border flex items-center justify-between ${
            health.imuOk ? 'bg-emerald-50/60 border-emerald-200' : 'bg-rose-50/80 border-rose-300'
          }`}>
            <div>
              <p className="text-xs font-bold text-[var(--color-on-surface)]">MPU6050 Motion IMU</p>
              <p className="text-[11px] font-mono text-[var(--color-on-surface-variant)] mt-0.5">
                {health.imuOk ? '100 Hz Continuous Burst OK' : 'I2C Bus Error / Frozen'}
              </p>
            </div>
            <span className={`px-2.5 py-1 rounded text-[11px] font-mono font-bold ${
              health.imuOk ? 'bg-emerald-200 text-emerald-800' : 'bg-rose-200 text-rose-800'
            }`}>
              {health.imuOk ? 'HEALTHY' : 'FAULT'}
            </span>
          </div>
        </div>

        {/* Live SQI Bar */}
        <div className="space-y-1.5 pt-1">
          <div className="flex justify-between text-xs font-mono">
            <span className="text-[var(--color-on-surface-variant)]">ECG Signal Quality Index (SQI):</span>
            <span className="font-bold">{health.ecgSqi >= 128 ? 'ACCEPTABLE CLINICAL QUALITY' : 'POOR SIGNAL / NOISY'}</span>
          </div>
          <div className="w-full bg-[var(--color-surface-container-high)] rounded-full h-3 overflow-hidden border border-[var(--color-outline-variant)]">
            <div
              className={`h-full transition-all duration-300 ${
                health.ecgSqi >= 180 ? 'bg-emerald-500' : health.ecgSqi >= 128 ? 'bg-blue-500' : health.ecgSqi >= 64 ? 'bg-amber-500' : 'bg-rose-500'
              }`}
              style={{ width: `${Math.min(100, Math.max(5, (health.ecgSqi / 255) * 100))}%` }}
            />
          </div>
        </div>
      </div>

      {/* Fault Counters & Technical Details */}
      <div className="grid grid-cols-2 gap-6">
        {/* Left: Live Pipeline Fault & Overrun Counters */}
        <div className="card-clinical p-5 space-y-4">
          <div className="flex items-center gap-2 border-b border-[var(--color-outline-variant)] pb-3">
            <Gauge className="w-5 h-5 text-[var(--color-primary)]" />
            <h2 className="text-sm font-bold text-[var(--color-on-surface)] uppercase tracking-wider">
              Live Pipeline Fault & Overrun Counters
            </h2>
          </div>

          <div className="space-y-3 font-mono text-xs">
            <div className="flex justify-between py-2 border-b border-[var(--color-outline-variant)] items-center">
              <span className="text-[var(--color-on-surface-variant)]">DMA Ring Overruns:</span>
              <span className={`font-bold px-2 py-0.5 rounded border ${getFaultBadge(health.ecgOverrunCount)}`}>
                {health.ecgOverrunCount} events
              </span>
            </div>
            <div className="flex justify-between py-2 border-b border-[var(--color-outline-variant)] items-center">
              <span className="text-[var(--color-on-surface-variant)]">DSP Queue Overflows:</span>
              <span className={`font-bold px-2 py-0.5 rounded border ${getFaultBadge(health.dspOverflowCount)}`}>
                {health.dspOverflowCount} dropped
              </span>
            </div>
            <div className="flex justify-between py-2 border-b border-[var(--color-outline-variant)] items-center">
              <span className="text-[var(--color-on-surface-variant)]">I2C Bus Recoveries:</span>
              <span className={`font-bold px-2 py-0.5 rounded border ${getFaultBadge(health.i2cFailureCount)}`}>
                {health.i2cFailureCount} ticks
              </span>
            </div>
            <div className="flex justify-between py-2 items-center">
              <span className="text-[var(--color-on-surface-variant)]">Total BLE Packets:</span>
              <span className="font-bold text-emerald-700">{(diagnostics.packetsReceived ?? 0).toLocaleString()} pkts</span>
            </div>
          </div>
        </div>

        {/* Right: Firmware Identity & Session Metadata */}
        <div className="card-clinical p-5 space-y-4">
          <div className="flex items-center gap-2 border-b border-[var(--color-outline-variant)] pb-3">
            <Cpu className="w-5 h-5 text-[var(--color-primary)]" />
            <h2 className="text-sm font-bold text-[var(--color-on-surface)] uppercase tracking-wider">
              Firmware Identity & Session Metadata
            </h2>
          </div>

          <div className="space-y-3 font-mono text-xs">
            <div className="flex justify-between py-1.5 border-b border-[var(--color-outline-variant)]">
              <span className="text-[var(--color-on-surface-variant)]">Target SoC:</span>
              <span className="font-bold text-[var(--color-on-surface)]">{diagnostics.deviceName || 'EFR32MG26 (BRD2709A)'}</span>
            </div>
            <div className="flex justify-between py-1.5 border-b border-[var(--color-outline-variant)]">
              <span className="text-[var(--color-on-surface-variant)]">Firmware Version:</span>
              <span className="font-bold text-[var(--color-primary)]">v{health.fwVersion || '1.0.0'}</span>
            </div>
            <div className="flex justify-between py-1.5 border-b border-[var(--color-outline-variant)]">
              <span className="text-[var(--color-on-surface-variant)]">Active Session ID:</span>
              <span className="font-bold text-[11px] text-[var(--color-on-surface)]">{health.sessionId || 'sess_active_link'}</span>
            </div>
            <div className="flex justify-between py-1.5 border-b border-[var(--color-outline-variant)]">
              <span className="text-[var(--color-on-surface-variant)]">Telemetry Service UUID:</span>
              <span className="font-bold text-[10px] text-[var(--color-on-surface)]">b4cf8877-ba1a-414c-a99d-de85a13fd66a</span>
            </div>
            <div className="flex justify-between py-1.5">
              <span className="text-[var(--color-on-surface-variant)]">Health Service UUID:</span>
              <span className="font-bold text-[10px] text-[var(--color-on-surface)]">c5da9988-ca2b-425d-b00e-ef96b24ee77b</span>
            </div>
          </div>
        </div>
      </div>
    </div>
  );
};
