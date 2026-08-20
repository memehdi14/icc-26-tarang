'use client';

import React, { useEffect, useRef } from 'react';
import { Activity, CheckCircle2, RefreshCw, Radio, Zap } from 'lucide-react';
import { ClinicalEvent, EcgSnippet } from '../types/telemetry';

interface WaveformCanvasProps {
  currentEvent?: ClinicalEvent | null;
  activeSnippet?: EcgSnippet | null;
  onClearSnapshot?: () => void;
}

export const WaveformCanvas: React.FC<WaveformCanvasProps> = ({ activeSnippet, onClearSnapshot }) => {
  const containerRef = useRef<HTMLDivElement | null>(null);
  const canvasRef = useRef<HTMLCanvasElement | null>(null);
  const hasEvent = Boolean(activeSnippet && (activeSnippet.waveform?.length ?? 0) > 0);

  useEffect(() => {
    const canvas = canvasRef.current;
    const container = containerRef.current;
    if (!canvas || !container) return;

    const resizeCanvas = () => {
      const rect = container.getBoundingClientRect();
      const dpr = window.devicePixelRatio || 1;
      canvas.width = Math.max(300, rect.width * dpr);
      canvas.height = Math.max(160, rect.height * dpr);
    };

    resizeCanvas();
    window.addEventListener('resize', resizeCanvas);

    const context = canvas.getContext('2d');
    if (!context) return () => window.removeEventListener('resize', resizeCanvas);
    let animationId = 0;
    let phase = 0;

    const render = () => {
      const width = canvas.width;
      const height = canvas.height;
      context.clearRect(0, 0, width, height);

      const dpr = window.devicePixelRatio || 1;
      const gridSize = 20 * dpr;

      context.strokeStyle = 'rgba(40, 89, 197, 0.055)';
      context.lineWidth = 1 * dpr;
      for (let x = 0; x < width; x += gridSize) {
        context.beginPath(); context.moveTo(x, 0); context.lineTo(x, height); context.stroke();
      }
      for (let y = 0; y < height; y += gridSize) {
        context.beginPath(); context.moveTo(0, y); context.lineTo(width, y); context.stroke();
      }

      if (!hasEvent) {
        phase += 0.022;
        const center = height / 2;
        context.strokeStyle = 'rgba(0,131,120,0.5)';
        context.lineWidth = 1.5 * dpr;
        context.beginPath();
        context.moveTo(0, center);
        context.lineTo(width, center);
        context.stroke();

        const sweepWidth = 180 * dpr;
        const sweepX = (phase * 160 * dpr) % (width + sweepWidth) - (sweepWidth / 2);
        const sweep = context.createLinearGradient(sweepX - (sweepWidth / 2), 0, sweepX + (sweepWidth / 2), 0);
        sweep.addColorStop(0, 'rgba(0,131,120,0)');
        sweep.addColorStop(0.5, 'rgba(0,131,120,0.1)');
        sweep.addColorStop(1, 'rgba(0,131,120,0)');
        context.fillStyle = sweep;
        context.fillRect(sweepX - (sweepWidth / 2), 0, sweepWidth, height);
        animationId = requestAnimationFrame(render);
        return;
      }

      const waveform = activeSnippet?.waveform ?? [];
      const center = height / 2;
      const scaleY = height * 0.34;
      context.strokeStyle = '#2859c5';
      context.lineWidth = 2 * dpr;
      context.lineJoin = 'round';
      context.beginPath();
      waveform.forEach((sample, index) => {
        const x = index / Math.max(1, waveform.length - 1) * width;
        const y = center - sample * scaleY;
        if (index === 0) context.moveTo(x, y); else context.lineTo(x, y);
      });
      context.stroke();

      (activeSnippet?.annotations ?? []).forEach((annotation) => {
        const x = annotation.offsetMs / 4000 * width;
        context.strokeStyle = annotation.label === 'V' ? 'rgba(186,26,26,0.45)' : annotation.label === 'S' ? 'rgba(154,93,0,0.42)' : 'rgba(0,108,85,0.28)';
        context.setLineDash([4 * dpr, 5 * dpr]);
        context.beginPath(); context.moveTo(x, 24 * dpr); context.lineTo(x, height - 24 * dpr); context.stroke();
        context.setLineDash([]);
      });
    };

    render();
    return () => {
      window.removeEventListener('resize', resizeCanvas);
      cancelAnimationFrame(animationId);
    };
  }, [activeSnippet, hasEvent]);

  return (
    <div className="clinical-panel overflow-hidden bg-[var(--paper-card)]">
      <div className="flex min-h-[48px] items-center justify-between gap-3 border-b border-[var(--line)] px-4 py-2.5 max-md:items-start max-md:flex-col">
        <div className="flex items-center gap-2.5">
          <span className={`h-2 w-2 rounded-full ${hasEvent ? 'bg-[var(--cardiac-rose)] animate-ping' : 'bg-[var(--clinical-teal)]'}`} />
          <div>
            <h2 className="text-xs sm:text-sm font-bold text-[var(--ink)]">
              {hasEvent ? 'Triggered Event ECG Snapshot' : 'Mode A: Low-Power Event-Driven Viewer'}
            </h2>
            <p className="discovery-eyebrow !text-[9px] !text-[var(--muted)] mt-0.5">
              {hasEvent ? '4-Second High-Res Arrhythmia Capture' : 'Awaiting Event Trigger • Radio Idle (30+ Day Battery Mode)'}
            </p>
          </div>
        </div>
        <div className="flex items-center gap-2.5">
          <span className="font-mono text-[10px] text-[var(--muted)]">
            {hasEvent ? '250 Hz Motion-Compensated' : 'On-Device Tier 0-3 Inference Active'}
          </span>
          {hasEvent && onClearSnapshot && (
            <button className="discovery-pill-secondary !py-1 !px-2.5 !min-h-[28px] !text-[10px]" onClick={onClearSnapshot}>
              <RefreshCw size={12} /> Return to Low-Power Mode
            </button>
          )}
        </div>
      </div>

      <div ref={containerRef} className="waveform-grid relative h-[210px] sm:h-[260px] lg:h-[310px] bg-white">
        <canvas ref={canvasRef} className="block h-full w-full" />
        {!hasEvent && (
          <div className="absolute bottom-3 left-3.5 flex items-center gap-2 rounded-full border border-[var(--line)] bg-[var(--paper-card)]/95 backdrop-blur-sm px-3 py-1 text-[10px] font-semibold text-[var(--ink)] shadow-sm">
            <Radio size={13} className="text-[var(--clinical-teal)] animate-pulse" />
            <span>Awaiting Event Trigger… <span className="text-[var(--muted)] font-normal hidden sm:inline">(Continuous healthy ECG suppressed to maintain 30+ day battery life)</span></span>
          </div>
        )}
        {hasEvent && (
          <div className="absolute left-3.5 top-3 flex flex-wrap gap-1.5">
            {(activeSnippet?.annotations ?? []).map((annotation, index) => (
              <span key={`${annotation.offsetMs}-${index}`} className={`inline-flex items-center gap-1 rounded-full border px-2 py-0.5 font-mono text-[9px] font-bold shadow-sm ${annotation.label === 'V' ? 'border-red-300 bg-red-50 text-red-700' : annotation.label === 'S' ? 'border-amber-300 bg-amber-50 text-amber-700' : 'border-emerald-300 bg-emerald-50 text-emerald-700'}`}>
                <Zap size={10} /> {annotation.label === 'V' ? 'PVC' : annotation.label === 'S' ? 'PAC' : 'Normal'} ({Math.round(annotation.confidence * 100)}%)
              </span>
            ))}
          </div>
        )}
        <div className="pointer-events-none absolute bottom-3 right-3.5 flex items-center gap-1.5 font-mono text-[9px] text-[var(--muted)]">
          {hasEvent ? <><Activity size={12} className="text-[var(--deep-ocean)]" /> 4s Event Context</> : <><CheckCircle2 size={12} className="text-[var(--clinical-teal)]" /> Inference Armed</>}
        </div>
      </div>
    </div>
  );
};
