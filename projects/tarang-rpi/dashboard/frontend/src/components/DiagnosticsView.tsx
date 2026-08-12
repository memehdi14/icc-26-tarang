'use client';

import React from 'react';
import { TelemetryDiagnostics } from '../types/telemetry';
import { ShieldCheck, Cpu, Radio, Wifi, Zap, Activity, CheckCircle, RefreshCw, HardDrive, AlertCircle } from 'lucide-react';

interface DiagnosticsViewProps {
  diagnostics: TelemetryDiagnostics;
}

export const DiagnosticsView: React.FC<DiagnosticsViewProps> = ({ diagnostics }) => {
  return (
    <div className="space-y-6">
      {/* Title & Refresh Action Header */}
      <div className="flex items-center justify-between bg-white p-4 rounded-xl border border-[var(--color-outline-variant)] shadow-sm">
        <div>
          <h1 className="text-2xl font-extrabold text-[var(--color-on-surface)] flex items-center gap-2">
            <ShieldCheck className="w-7 h-7 text-[var(--color-primary)]" />
            Telemetry Diagnostics & Hardware Health
          </h1>
          <p className="text-xs text-[var(--color-on-surface-variant)] mt-1">
            Real-time link status, GATT notification latency, BLE signal metrics & EFR32MG26 sensor bus health.
          </p>
        </div>

        <button className="py-2 px-4 rounded-lg bg-[var(--color-surface-container-high)] text-[var(--color-primary)] text-xs font-bold flex items-center gap-2 border border-[var(--color-outline-variant)] hover:bg-[var(--color-surface-container-highest)] transition-colors">
          <RefreshCw className="w-4 h-4" />
          <span>Run Self-Diagnostic Check</span>
        </button>
      </div>

      {/* Primary Diagnostic Status Cards */}
      <div className="grid grid-cols-4 gap-4">
        {/* Connection Link Status */}
        <div className="card-clinical p-4 space-y-2">
          <div className="flex items-center justify-between text-xs font-bold text-[var(--color-on-surface-variant)]">
            <span>BLE Connection</span>
            <Wifi className={`w-4 h-4 ${diagnostics.bleConnected ? 'text-emerald-600' : 'text-red-500'}`} />
          </div>
          <p className={`text-xl font-mono font-extrabold flex items-center gap-2 ${diagnostics.bleConnected ? 'text-emerald-700' : 'text-red-600'}`}>
            {diagnostics.bleConnected ? (
              <>
                <CheckCircle className="w-5 h-5 text-emerald-600" />
                CONNECTED
              </>
            ) : (
              <>
                <AlertCircle className="w-5 h-5 text-red-600" />
                DISCONNECTED
              </>
            )}
          </p>
          <p className="text-[11px] font-mono text-[var(--color-on-surface-variant)] border-t border-[var(--color-outline-variant)] pt-2">
            Interval: 20 ms • GATT Notifications
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
          <p className="text-xl font-mono font-extrabold text-[var(--color-on-surface)]">
            {diagnostics.rssiDbm ?? -100} dBm
          </p>
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
          <p className="text-xl font-mono font-extrabold text-[var(--color-on-surface)]">
            {diagnostics.batteryPct ?? 0}%
          </p>
          <p className="text-[11px] font-mono text-[var(--color-on-surface-variant)] border-t border-[var(--color-outline-variant)] pt-2">
            Power Mode: EM0 Active
          </p>
        </div>
      </div>

      {/* Detailed Technical Specifications Grid */}
      <div className="grid grid-cols-2 gap-6">
        {/* Left: Device & GATT Details */}
        <div className="card-clinical p-5 space-y-4">
          <div className="flex items-center gap-2 border-b border-[var(--color-outline-variant)] pb-3">
            <Cpu className="w-5 h-5 text-[var(--color-primary)]" />
            <h2 className="text-sm font-bold text-[var(--color-on-surface)] uppercase tracking-wider">
              Silicon Labs EFR32 Specifications
            </h2>
          </div>

          <div className="space-y-3 font-mono text-xs">
            <div className="flex justify-between py-1.5 border-b border-[var(--color-outline-variant)]">
              <span className="text-[var(--color-on-surface-variant)]">Target SoC Board:</span>
              <span className="font-bold text-[var(--color-on-surface)]">{diagnostics.deviceName || 'EFR32MG26'}</span>
            </div>
            <div className="flex justify-between py-1.5 border-b border-[var(--color-outline-variant)]">
              <span className="text-[var(--color-on-surface-variant)]">BLE MAC Address:</span>
              <span className="font-bold text-[var(--color-on-surface)]">{diagnostics.deviceMac || '—'}</span>
            </div>
            <div className="flex justify-between py-1.5 border-b border-[var(--color-outline-variant)]">
              <span className="text-[var(--color-on-surface-variant)]">Firmware Build:</span>
              <span className="font-bold text-[var(--color-primary)]">{diagnostics.firmwareVersion || 'v1.0.0'}</span>
            </div>
            <div className="flex justify-between py-1.5 border-b border-[var(--color-outline-variant)]">
              <span className="text-[var(--color-on-surface-variant)]">Telemetry UUID:</span>
              <span className="font-bold text-[11px] text-[var(--color-on-surface)]">b4cf8877-ba1a-414c-a99d-de85a13fd66a</span>
            </div>
            <div className="flex justify-between py-1.5">
              <span className="text-[var(--color-on-surface-variant)]">Total Packets Rx:</span>
              <span className="font-bold text-emerald-700">{(diagnostics.packetsReceived ?? 0).toLocaleString()}</span>
            </div>
          </div>
        </div>

        {/* Right: Sensor Subsystem Bus Health */}
        <div className="card-clinical p-5 space-y-4">
          <div className="flex items-center gap-2 border-b border-[var(--color-outline-variant)] pb-3">
            <HardDrive className="w-5 h-5 text-[var(--color-primary)]" />
            <h2 className="text-sm font-bold text-[var(--color-on-surface)] uppercase tracking-wider">
              Sensor Subsystem Hardware Health
            </h2>
          </div>

          <div className="space-y-3 text-xs">
            {/* ECG DMA */}
            <div className="p-3 rounded-lg bg-[var(--color-surface-container-low)] border border-[var(--color-outline-variant)] flex items-center justify-between">
              <div>
                <p className="font-bold text-[var(--color-on-surface)]">ECG Analog Front-End (IADC DMA)</p>
                <p className="text-[11px] font-mono text-[var(--color-on-surface-variant)]">Sample Rate: 250 Hz • Dual Half-Buffer Atomic Check</p>
              </div>
              <span className={`px-2.5 py-1 rounded text-[10px] font-mono font-bold border ${
                diagnostics.ecgDmaHealth
                  ? 'bg-emerald-100 text-emerald-800 border-emerald-300'
                  : 'bg-red-100 text-red-800 border-red-300'
              }`}>
                {diagnostics.ecgDmaHealth ? 'HEALTHY' : 'FAULT'}
              </span>
            </div>

            {/* PPG I2C */}
            <div className="p-3 rounded-lg bg-[var(--color-surface-container-low)] border border-[var(--color-outline-variant)] flex items-center justify-between">
              <div>
                <p className="font-bold text-[var(--color-on-surface)]">MAX30102 PPG Optical Sensor (I2C)</p>
                <p className="text-[11px] font-mono text-[var(--color-on-surface-variant)]">Sample Rate: 100 Hz • Bus Recovery Auto-Clear</p>
              </div>
              <span className={`px-2.5 py-1 rounded text-[10px] font-mono font-bold border ${
                diagnostics.ppgI2cHealth
                  ? 'bg-emerald-100 text-emerald-800 border-emerald-300'
                  : 'bg-red-100 text-red-800 border-red-300'
              }`}>
                {diagnostics.ppgI2cHealth ? 'HEALTHY' : 'FAULT'}
              </span>
            </div>

            {/* IMU FIFO */}
            <div className="p-3 rounded-lg bg-[var(--color-surface-container-low)] border border-[var(--color-outline-variant)] flex items-center justify-between">
              <div>
                <p className="font-bold text-[var(--color-on-surface)]">MPU6050 Motion IMU (I2C)</p>
                <p className="text-[11px] font-mono text-[var(--color-on-surface-variant)]">Sample Rate: 100 Hz • Atomic Flag Reset</p>
              </div>
              <span className={`px-2.5 py-1 rounded text-[10px] font-mono font-bold border ${
                diagnostics.imuFifoHealth
                  ? 'bg-emerald-100 text-emerald-800 border-emerald-300'
                  : 'bg-red-100 text-red-800 border-red-300'
              }`}>
                {diagnostics.imuFifoHealth ? 'HEALTHY' : 'FAULT'}
              </span>
            </div>
          </div>
        </div>
      </div>
    </div>
  );
};
