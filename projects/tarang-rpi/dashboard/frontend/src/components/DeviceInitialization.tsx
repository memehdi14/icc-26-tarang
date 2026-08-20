'use client';

import React, { useEffect, useMemo, useRef, useState } from 'react';
import {
  Activity,
  ArrowLeft,
  Check,
  Circle,
  Cpu,
  Database,
  Radio,
  RefreshCw,
  ShieldCheck,
} from 'lucide-react';
import { ClinicalTelemetryPacket, DeviceHealthTelemetry } from '../types/telemetry';

interface DeviceInitializationProps {
  backendOnline: boolean;
  bleConnected: boolean;
  telemetry: ClinicalTelemetryPacket;
  telemetryReady: boolean;
  deviceHealth?: DeviceHealthTelemetry;
  deviceName?: string;
  sessionLabel?: string;
  onComplete: () => void;
  onRetry: () => void;
  onBack: () => void;
}

const STAGES = [
  { title: 'Clinical services', detail: 'Database and monitoring session ready', icon: Database },
  { title: 'BLE channel', detail: 'Tarang GATT services connected', icon: Radio },
  { title: 'Telemetry path', detail: 'First measured vitals received from the wearable', icon: Activity },
  { title: 'Inference runtime', detail: 'Edge DSP and AI runtime settling', icon: Cpu },
  { title: 'Ready', detail: 'Clinical telemetry can begin', icon: ShieldCheck },
];

export const DeviceInitialization: React.FC<DeviceInitializationProps> = ({
  backendOnline,
  bleConnected,
  telemetry,
  telemetryReady,
  deviceHealth,
  deviceName = 'Tarang wearable',
  sessionLabel,
  onComplete,
  onRetry,
  onBack,
}) => {
  const canvasRef = useRef<HTMLCanvasElement | null>(null);
  const hasLiveHealth = deviceHealth !== undefined;
  const targetStage = !backendOnline ? 0 : !bleConnected ? 1 : !telemetryReady ? 2 : 4;
  const [displayStage, setDisplayStage] = useState(0);
  const [finishing, setFinishing] = useState(false);

  useEffect(() => {
    if (targetStage < displayStage) {
      setDisplayStage(targetStage);
      setFinishing(false);
      return;
    }
    if (displayStage >= targetStage) return;
    const delay = displayStage === 3 ? 1500 : 650;
    const timer = window.setTimeout(() => setDisplayStage((stage) => Math.min(stage + 1, targetStage)), delay);
    return () => window.clearTimeout(timer);
  }, [displayStage, targetStage]);

  useEffect(() => {
    if (displayStage !== 4 || targetStage !== 4) return;
    const finishTimer = window.setTimeout(() => setFinishing(true), 700);
    const completeTimer = window.setTimeout(onComplete, 1300);
    return () => {
      window.clearTimeout(finishTimer);
      window.clearTimeout(completeTimer);
    };
  }, [displayStage, targetStage, onComplete]);

  const statusText = useMemo(() => {
    if (!backendOnline) return 'Waiting for the clinical backend';
    if (!bleConnected) return 'Waiting for the bonded Tarang wearable';
    if (!telemetryReady) return 'Waiting for the first measured vitals packet';
    if (displayStage === 3) return 'Settling the edge inference runtime';
    return 'Monitoring context is ready';
  }, [backendOnline, bleConnected, telemetryReady, displayStage]);

  useEffect(() => {
    const canvas = canvasRef.current;
    const context = canvas?.getContext('2d');
    if (!canvas || !context) return;
    let frame = 0;
    let phase = 0;
    const samples = new Array(520).fill(0);

    const render = () => {
      phase += 0.045;
      const width = canvas.width;
      const height = canvas.height;
      const center = height / 2;
      const connected = bleConnected && backendOnline;
      const heartRate = Math.max(55, telemetry.current_hr || 72);
      const beat = (phase * heartRate / 60 * 0.55) % 1;
      let value = (Math.random() - 0.5) * (connected ? 0.02 : 0.045);
      if (connected && displayStage >= 2) {
        if (beat > 0.12 && beat < 0.19) value += Math.sin((beat - 0.12) / 0.07 * Math.PI) * 0.14;
        if (beat > 0.25 && beat < 0.29) value += Math.sin((beat - 0.25) / 0.04 * Math.PI) * 1.2;
        if (beat > 0.29 && beat < 0.33) value -= Math.sin((beat - 0.29) / 0.04 * Math.PI) * 0.32;
        if (beat > 0.48 && beat < 0.62) value += Math.sin((beat - 0.48) / 0.14 * Math.PI) * 0.25;
      } else if (connected) {
        value += Math.sin(phase * 1.7) * 0.1;
      }
      samples.push(value);
      samples.shift();

      context.clearRect(0, 0, width, height);
      context.strokeStyle = 'rgba(40, 89, 197, 0.06)';
      context.lineWidth = 1;
      for (let x = 0; x <= width; x += 24) {
        context.beginPath(); context.moveTo(x, 0); context.lineTo(x, height); context.stroke();
      }
      for (let y = 0; y <= height; y += 24) {
        context.beginPath(); context.moveTo(0, y); context.lineTo(width, y); context.stroke();
      }
      context.shadowBlur = connected ? 8 : 0;
      context.shadowColor = connected ? 'rgba(0, 113, 227, 0.45)' : 'transparent';
      context.strokeStyle = connected ? '#0071E3' : '#8a9794';
      context.lineWidth = 2.2;
      context.beginPath();
      samples.forEach((sample, index) => {
        const x = index / (samples.length - 1) * width;
        const y = center - sample * 72;
        if (index === 0) context.moveTo(x, y); else context.lineTo(x, y);
      });
      context.stroke();
      context.shadowBlur = 0;

      const sweepX = (phase * 120) % (width + 160) - 80;
      const sweep = context.createLinearGradient(sweepX - 80, 0, sweepX + 80, 0);
      sweep.addColorStop(0, 'rgba(0,113,227,0)');
      sweep.addColorStop(0.5, 'rgba(0,113,227,0.12)');
      sweep.addColorStop(1, 'rgba(0,113,227,0)');
      context.fillStyle = sweep;
      context.fillRect(sweepX - 80, 0, 160, height);
      frame = requestAnimationFrame(render);
    };
    render();
    return () => cancelAnimationFrame(frame);
  }, [backendOnline, bleConnected, displayStage, telemetry.current_hr]);

  return (
    <main className={`min-h-screen bg-[var(--paper)] transition-all duration-500 ${finishing ? 'scale-[0.995] opacity-0' : 'opacity-100'}`}>
      <header className="flex h-[58px] items-center justify-between border-b border-[var(--line)] px-6 bg-white">
        <div className="flex items-center gap-3">
          <img
            src="/logo_mark.svg"
            alt="Tarang"
            className="h-7 w-7 shrink-0 object-contain"
            onError={(e) => { (e.currentTarget as HTMLImageElement).src = '/tarang_logo.png'; }}
          />
          <div>
            <p className="text-sm font-bold text-[var(--ink)]">Tarang Clinical</p>
            <p className="text-[10px] text-[var(--muted)]">Device commissioning</p>
          </div>
        </div>
        <div className="flex items-center gap-3">
          <button onClick={onBack} className="discovery-pill-secondary !py-1 !px-3 !text-xs">
            <ArrowLeft size={13} /> Back to worklist
          </button>
        </div>
      </header>

      <div className="mx-auto max-w-5xl px-6 py-6 max-sm:px-4">
        <section className="view-header view-enter !pb-3">
          <div>
            <span className="text-xs font-semibold text-[var(--muted)]">{sessionLabel || 'Encrypted telemetry session'}</span>
            <h1 className="text-2xl font-bold text-[var(--ink)]">Connecting {deviceName}</h1>
            <p className="text-xs text-[var(--ink-soft)] mt-0.5" aria-live="polite">{statusText}</p>
          </div>
          <div className="text-right">
            <p className="text-[10px] uppercase tracking-wider text-[var(--muted)]">Readiness</p>
            <p className="font-mono text-2xl font-bold text-[var(--clinical-teal)]">{Math.round((displayStage / 4) * 100)}%</p>
          </div>
        </section>

        <div className="grid grid-cols-[minmax(0,1fr)_320px] gap-6 max-lg:grid-cols-1">
          <section className="view-enter" style={{ animationDelay: '70ms' }}>
            <div className="mb-2 flex items-center justify-between">
              <div className="flex items-center gap-2 text-xs font-bold uppercase tracking-wider text-[var(--ink)]">
                <Activity size={14} className="text-[var(--clinical-teal)]" /> Physiological signal calibration
              </div>
              <span className="font-mono text-[10px] text-[var(--muted)]">
                {hasLiveHealth ? `SQI ${deviceHealth?.ecgSqi}/255` : bleConnected ? '250 Hz acquisition' : 'Scanning'}
              </span>
            </div>
            <div className="waveform-grid relative h-[210px] overflow-hidden rounded-lg border border-[var(--line)] bg-white shadow-xs">
              <canvas ref={canvasRef} width={920} height={210} className="block h-full w-full" />
              <div className="absolute bottom-2.5 left-3 flex gap-3 font-mono text-[10px] text-[var(--muted)] bg-white/90 px-2.5 py-0.5 rounded border border-[var(--line-soft)]">
                <span>Signal calibration</span>
                <span>{telemetry.current_hr || '--'} bpm</span>
              </div>
            </div>

            <div className="mt-4 rounded-lg border border-[var(--line)] bg-white p-4 shadow-xs">
              <div className="mb-2.5 flex items-center justify-between border-b border-[var(--line-soft)] pb-2">
                <div>
                  <p className="text-xs font-bold text-[var(--ink)] uppercase tracking-wider">Edge inference pipeline</p>
                  <p className="text-[10px] text-[var(--muted)]">Quantized INT8 cascade on EFR32MG26</p>
                </div>
                <span className="font-mono text-[10px] font-medium text-[var(--clinical-teal)]">
                  Tier 0-3 active
                </span>
              </div>
              <div className="grid grid-cols-4 gap-2 text-center text-xs">
                <div className="p-2 rounded bg-[var(--paper-2)] border border-[var(--line-soft)]">
                  <p className="text-[10px] text-[var(--muted)]">Tier 0</p>
                  <p className="font-semibold text-[var(--ink)]">DSP heuristic</p>
                </div>
                <div className="p-2 rounded bg-[var(--paper-2)] border border-[var(--line-soft)]">
                  <p className="text-[10px] text-[var(--muted)]">Tier 1</p>
                  <p className="font-semibold text-[var(--ink)]">Gate CNN</p>
                </div>
                <div className="p-2 rounded bg-[var(--paper-2)] border border-[var(--line-soft)]">
                  <p className="text-[10px] text-[var(--muted)]">Tier 2</p>
                  <p className="font-semibold text-[var(--ink)]">SV Head</p>
                </div>
                <div className="p-2 rounded bg-[var(--paper-2)] border border-[var(--line-soft)]">
                  <p className="text-[10px] text-[var(--muted)]">Tier 3</p>
                  <p className="font-semibold text-[var(--ink)]">Event engine</p>
                </div>
              </div>
            </div>
          </section>

          <aside className="view-enter rounded-lg border border-[var(--line)] bg-white p-4 shadow-xs" style={{ animationDelay: '130ms' }}>
            <div className="mb-3 flex items-center justify-between border-b border-[var(--line-soft)] pb-2">
              <h2 className="text-xs font-bold uppercase tracking-wider text-[var(--ink)]">Readiness pipeline</h2>
              <span className="text-[10px] font-mono text-[var(--muted)]">Automated</span>
            </div>
            <ol className="divide-y divide-[var(--line-soft)]">
              {STAGES.map((stage, index) => {
                const done = index < displayStage || displayStage === 4;
                const active = index === displayStage && displayStage < 4;
                const Icon = stage.icon;
                return (
                  <li key={stage.title} className={`flex items-start gap-2.5 py-2.5 ${!done && !active ? 'opacity-40' : ''}`}>
                    <div className={`mt-0.5 grid h-5 w-5 shrink-0 place-items-center rounded-full border text-xs ${
                      done
                        ? 'border-[var(--clinical-teal)] bg-[var(--clinical-teal)] text-white'
                        : active
                        ? 'border-[var(--deep-ocean)] bg-blue-50 text-[var(--deep-ocean)]'
                        : 'border-[var(--line)] text-[var(--muted)]'
                    }`}>
                      {done ? <Check size={11} strokeWidth={2.5} /> : active ? <RefreshCw size={10} className="animate-spin" /> : <Circle size={8} />}
                    </div>
                    <div className="min-w-0">
                      <p className="text-xs font-semibold text-[var(--ink)]">{stage.title}</p>
                      <p className="text-[10px] text-[var(--muted)] leading-tight mt-0.5">{stage.detail}</p>
                    </div>
                  </li>
                );
              })}
            </ol>

            {(!backendOnline || !bleConnected || !telemetryReady) && (
              <div className="mt-3 border-t border-[var(--line-soft)] pt-3">
                <button onClick={onRetry} className="discovery-pill-primary w-full !py-1.5 !text-xs justify-center">
                  <RefreshCw size={12} /> <span>Re-scan BLE</span>
                </button>
              </div>
            )}
          </aside>
        </div>
      </div>
    </main>
  );
};
