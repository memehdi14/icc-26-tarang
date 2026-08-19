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
      context.strokeStyle = connected ? '#008378' : '#8a9794';
      context.lineWidth = 2;
      context.beginPath();
      samples.forEach((sample, index) => {
        const x = index / (samples.length - 1) * width;
        const y = center - sample * 66;
        if (index === 0) context.moveTo(x, y); else context.lineTo(x, y);
      });
      context.stroke();

      const sweepX = (phase * 95) % (width + 120) - 60;
      const sweep = context.createLinearGradient(sweepX - 60, 0, sweepX + 60, 0);
      sweep.addColorStop(0, 'rgba(0,131,120,0)');
      sweep.addColorStop(0.5, 'rgba(0,131,120,0.09)');
      sweep.addColorStop(1, 'rgba(0,131,120,0)');
      context.fillStyle = sweep;
      context.fillRect(sweepX - 60, 0, 120, height);
      frame = requestAnimationFrame(render);
    };
    render();
    return () => cancelAnimationFrame(frame);
  }, [backendOnline, bleConnected, displayStage, telemetry.current_hr]);

  return (
    <main className={`min-h-screen bg-white transition-all duration-500 ${finishing ? 'scale-[0.995] opacity-0' : 'opacity-100'}`}>
      <header className="flex h-[72px] items-center justify-between border-b border-[var(--color-outline-variant)] px-7">
        <div className="flex items-center gap-3">
          <img src="/tarang_logo.png" alt="" className="h-8 w-8 object-contain" />
          <div><p className="text-xl font-extrabold text-[var(--color-primary)]">Tarang Clinical</p><p className="eyebrow">Device commissioning</p></div>
        </div>
        <button onClick={onBack} className="button-secondary"><ArrowLeft size={16} /> Patient worklist</button>
      </header>

      <div className="mx-auto max-w-6xl px-7 py-10 max-sm:px-4">
        <section className="view-header view-enter">
          <div>
            <p className="eyebrow mb-2 text-[var(--color-primary)]">{sessionLabel || 'Active monitoring session'}</p>
            <h1>Preparing {deviceName}</h1>
            <p aria-live="polite">{statusText}</p>
          </div>
          <div className="text-right"><p className="eyebrow">Readiness</p><p className="font-mono text-3xl font-bold text-[var(--color-primary)]">{Math.round((displayStage / 4) * 100)}%</p></div>
        </section>

        <div className="grid grid-cols-[minmax(0,1fr)_340px] gap-8 max-lg:grid-cols-1">
          <section className="view-enter" style={{ animationDelay: '70ms' }}>
            <div className="mb-3 flex items-center justify-between">
              <div className="flex items-center gap-2 text-sm font-bold"><Activity size={17} className="text-[var(--color-primary)]" /> Signal pipeline activity</div>
              <span className="eyebrow">{hasLiveHealth ? `SQI ${deviceHealth?.ecgSqi}/255` : bleConnected ? 'Synchronizing' : 'Offline'}</span>
            </div>
            <div className="waveform-grid relative h-[250px] overflow-hidden rounded-lg border border-[var(--color-outline-variant)] bg-white">
              <canvas ref={canvasRef} width={920} height={250} className="block h-full w-full" />
              <div className="absolute bottom-3 left-4 flex gap-5 font-mono text-[10px] text-[var(--color-on-surface-variant)]">
                <span>Commissioning trace</span><span>{telemetry.current_hr || '--'} bpm measured</span>
              </div>
            </div>

            <div className={`mt-6 border-y border-[var(--color-outline-variant)] py-5 transition-opacity ${displayStage === 3 ? 'opacity-100' : 'opacity-45'}`}>
              <div className="mb-4 flex items-end justify-between">
                <div><p className="text-sm font-bold">Inference memory map</p><p className="mt-1 text-xs text-[var(--color-on-surface-variant)]">Quantized INT8 weights loaded into the on-device arena</p></div>
                <span className="eyebrow">Gate CNN / SV head</span>
              </div>
              <div className="grid grid-cols-[repeat(18,minmax(0,1fr))] gap-1" aria-label="Inference weights loading">
                {Array.from({ length: 72 }).map((_, index) => (
                  <span key={index} className="weight-cell h-7 rounded-sm bg-[var(--color-primary-container)]" style={{ animationDelay: `${index * 30}ms` }} />
                ))}
              </div>
            </div>
          </section>

          <aside className="view-enter border-l border-[var(--color-outline-variant)] pl-7 max-lg:border-l-0 max-lg:border-t max-lg:pl-0 max-lg:pt-7" style={{ animationDelay: '130ms' }}>
            <div className="mb-4 flex items-center justify-between"><h2 className="text-sm font-bold">Readiness checks</h2><span className="eyebrow">Live status</span></div>
            <ol>
              {STAGES.map((stage, index) => {
                const done = index < displayStage || displayStage === 4;
                const active = index === displayStage && displayStage < 4;
                const Icon = stage.icon;
                return (
                  <li key={stage.title} className={`relative flex gap-3 border-t border-[var(--color-surface-container-high)] py-4 first:border-0 ${!done && !active ? 'opacity-45' : ''}`}>
                    <div className={`mt-0.5 grid h-7 w-7 shrink-0 place-items-center rounded-full border ${done ? 'border-[var(--color-success)] bg-[var(--color-success)] text-white' : active ? 'border-[var(--color-primary-container)] text-[var(--color-primary)]' : 'border-[var(--color-outline-variant)] text-[var(--color-outline)]'}`}>
                      {done ? <Check size={15} /> : active ? <RefreshCw size={14} className="animate-spin" /> : <Circle size={12} />}
                    </div>
                    <div className="min-w-0"><p className="flex items-center gap-2 text-sm font-bold"><Icon size={15} /> {stage.title}</p><p className="mt-1 text-xs leading-5 text-[var(--color-on-surface-variant)]">{stage.detail}</p></div>
                  </li>
                );
              })}
            </ol>

            {(!backendOnline || !bleConnected || !telemetryReady) && (
              <div className="mt-5 border-t border-[var(--color-outline-variant)] pt-5">
                <p className="mb-3 text-xs text-[var(--color-on-surface-variant)]">The workstation will continue automatically when the missing signal becomes available.</p>
                <button onClick={onRetry} className="button-primary w-full"><RefreshCw size={16} /> Refresh device status</button>
              </div>
            )}
          </aside>
        </div>
      </div>
    </main>
  );
};
