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
      <header className="flex h-[64px] items-center justify-between border-b border-[var(--line)] px-6 bg-[var(--paper-card)]">
        <div className="flex items-center gap-3">
          <img src="/images/tarang-logo.png" alt="Tarang" className="h-7 w-auto object-contain" />
          <div>
            <p className="text-sm font-bold text-[var(--ink)]">Tarang Clinical</p>
            <p className="discovery-eyebrow !text-[9px]">Device Commissioning</p>
          </div>
        </div>
        <div className="flex items-center gap-3">
          <img src="/images/ocelleon-logo.png" alt="Ocelleon" className="hidden sm:block h-3.5 w-auto opacity-75" />
          <button onClick={onBack} className="discovery-pill-secondary !py-1.5 !px-3 !text-xs"><ArrowLeft size={14} /> Back to Worklist</button>
        </div>
      </header>

      <div className="mx-auto max-w-5xl px-6 py-8 max-sm:px-4">
        <section className="view-header view-enter">
          <div>
            <span className="discovery-eyebrow mb-1.5">{sessionLabel || 'Encrypted GATT Session'}</span>
            <h1>Commissioning {deviceName}</h1>
            <p aria-live="polite">{statusText}</p>
          </div>
          <div className="text-right">
            <p className="eyebrow">Pipeline Readiness</p>
            <p className="font-mono text-3xl font-bold text-[var(--accent)]">{Math.round((displayStage / 4) * 100)}%</p>
          </div>
        </section>

        <div className="grid grid-cols-[minmax(0,1fr)_320px] gap-7 max-lg:grid-cols-1">
          <section className="view-enter" style={{ animationDelay: '70ms' }}>
            <div className="mb-2.5 flex items-center justify-between">
              <div className="flex items-center gap-2 text-xs font-bold uppercase tracking-wider text-[var(--ink)]">
                <Activity size={15} className="text-[var(--accent)]" /> Biosignal Pipeline Stream
              </div>
              <span className="font-mono text-[10px] text-[var(--muted)]">
                {hasLiveHealth ? `SQI ${deviceHealth?.ecgSqi}/255` : bleConnected ? 'GATT 250 Hz Synchronizing' : 'Searching for Signal'}
              </span>
            </div>
            <div className="waveform-grid relative h-[230px] overflow-hidden rounded-xl border border-[var(--line)] bg-[var(--paper-card)] shadow-sm">
              <canvas ref={canvasRef} width={920} height={230} className="block h-full w-full" />
              <div className="absolute bottom-2.5 left-3.5 flex gap-4 font-mono text-[10px] text-[var(--muted)] bg-[var(--paper-card)]/90 px-2.5 py-1 rounded-full border border-[var(--line-soft)] backdrop-blur-sm">
                <span>Calibration Sweep</span><span>{telemetry.current_hr || '--'} bpm verified</span>
              </div>
            </div>

            <div className={`mt-5 rounded-xl border border-[var(--line)] bg-[var(--paper-card)] p-4 shadow-sm transition-all duration-300 ${displayStage >= 3 ? 'opacity-100' : 'opacity-60'}`}>
              <div className="mb-3 flex items-end justify-between">
                <div>
                  <p className="text-xs font-bold text-[var(--ink)] uppercase tracking-wider">Edge Inference Weights Arena</p>
                  <p className="mt-0.5 text-[11px] text-[var(--muted)]">Quantized INT8 CNN loaded into EFR32MG26 SRAM memory</p>
                </div>
                <span className="font-mono text-[9px] font-bold px-2 py-0.5 rounded-full bg-[var(--accent-soft)] text-[var(--accent)]">
                  Tier 1-2 Arrhythmia Engine
                </span>
              </div>
              <div className="grid grid-cols-[repeat(18,minmax(0,1fr))] gap-1.5" aria-label="Inference weights loading">
                {Array.from({ length: 54 }).map((_, index) => (
                  <span
                    key={index}
                    className={`h-4 rounded-sm transition-all duration-300 ${
                      displayStage >= 3
                        ? 'bg-[var(--accent)] animate-pulse'
                        : index % 3 === 0
                        ? 'bg-[var(--clinical-teal)] opacity-40'
                        : 'bg-[var(--line)]'
                    }`}
                    style={{ animationDelay: `${(index * 25) % 800}ms` }}
                  />
                ))}
              </div>
            </div>
          </section>

          <aside className="view-enter rounded-xl border border-[var(--line)] bg-[var(--paper-card)] p-5 shadow-sm" style={{ animationDelay: '130ms' }}>
            <div className="mb-3.5 flex items-center justify-between border-b border-[var(--line-soft)] pb-2.5">
              <h2 className="text-xs font-bold uppercase tracking-wider text-[var(--ink)]">Readiness Pipeline</h2>
              <span className="discovery-eyebrow !text-[9px]">Automated</span>
            </div>
            <ol>
              {STAGES.map((stage, index) => {
                const done = index < displayStage || displayStage === 4;
                const active = index === displayStage && displayStage < 4;
                const Icon = stage.icon;
                return (
                  <li key={stage.title} className={`relative flex gap-3 border-t border-[var(--line-soft)] py-3 first:border-0 ${!done && !active ? 'opacity-40' : ''}`}>
                    <div className={`mt-0.5 grid h-6 w-6 shrink-0 place-items-center rounded-full border transition-all duration-300 ${
                      done
                        ? 'border-[var(--clinical-teal)] bg-[var(--clinical-teal)] text-white shadow-sm'
                        : active
                        ? 'border-[var(--accent)] bg-[var(--accent-soft)] text-[var(--accent)] animate-pulse'
                        : 'border-[var(--line)] text-[var(--muted)]'
                    }`}>
                      {done ? <Check size={13} strokeWidth={2.5} /> : active ? <RefreshCw size={12} className="animate-spin text-[var(--accent)]" /> : <Circle size={10} />}
                    </div>
                    <div className="min-w-0">
                      <p className="flex items-center gap-1.5 text-xs font-bold text-[var(--ink)]">
                        <Icon size={13} className={done ? 'text-[var(--clinical-teal)]' : active ? 'text-[var(--accent)]' : 'text-[var(--muted)]'} />
                        {stage.title}
                      </p>
                      <p className="mt-0.5 text-[11px] leading-4 text-[var(--muted)]">{stage.detail}</p>
                    </div>
                  </li>
                );
              })}
            </ol>

            {(!backendOnline || !bleConnected || !telemetryReady) && (
              <div className="mt-4 border-t border-[var(--line-soft)] pt-4">
                <p className="mb-2.5 text-[11px] text-[var(--muted)] leading-relaxed">
                  The dashboard will advance automatically as soon as the GATT link is bonded.
                </p>
                <button onClick={onRetry} className="discovery-pill-primary w-full !py-2 !text-xs"><RefreshCw size={13} /> Re-scan BLE</button>
              </div>
            )}
          </aside>
        </div>
      </div>
    </main>
  );
};
