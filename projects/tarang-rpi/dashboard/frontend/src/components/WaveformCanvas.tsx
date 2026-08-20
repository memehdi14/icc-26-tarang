'use client';

import React, { useEffect, useRef } from 'react';
import { Activity, CheckCircle2, Radio, RefreshCw, Zap } from 'lucide-react';
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
      canvas.width = Math.max(300, Math.floor(rect.width * dpr));
      canvas.height = Math.max(160, Math.floor(rect.height * dpr));
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
      const center = height / 2;

      // 1. Clinical 1mm/5mm ECG Grid
      const minorGrid = 6 * dpr;
      const majorGrid = 30 * dpr;

      // Minor grid
      context.strokeStyle = 'rgba(200, 205, 215, 0.25)';
      context.lineWidth = 0.5 * dpr;
      context.beginPath();
      for (let x = 0; x < width; x += minorGrid) {
        context.moveTo(x, 0);
        context.lineTo(x, height);
      }
      for (let y = 0; y < height; y += minorGrid) {
        context.moveTo(0, y);
        context.lineTo(width, y);
      }
      context.stroke();

      // Major grid
      context.strokeStyle = 'rgba(180, 190, 205, 0.45)';
      context.lineWidth = 1 * dpr;
      context.beginPath();
      for (let x = 0; x < width; x += majorGrid) {
        context.moveTo(x, 0);
        context.lineTo(x, height);
      }
      for (let y = 0; y < height; y += majorGrid) {
        context.moveTo(0, y);
        context.lineTo(width, y);
      }
      context.stroke();

      // 2. Idle State vs Triggered Event Waveform
      if (!hasEvent) {
        phase += 0.02;
        context.strokeStyle = '#059669'; // Clinical Emerald
        context.lineWidth = 1.8 * dpr;
        context.beginPath();
        context.moveTo(0, center);
        context.lineTo(width, center);
        context.stroke();

        // Subtle sweep laser indicator
        const sweepWidth = 140 * dpr;
        const sweepX = (phase * 140 * dpr) % (width + sweepWidth) - (sweepWidth / 2);
        const sweep = context.createLinearGradient(sweepX - (sweepWidth / 2), 0, sweepX + (sweepWidth / 2), 0);
        sweep.addColorStop(0, 'rgba(5, 150, 105, 0)');
        sweep.addColorStop(0.5, 'rgba(5, 150, 105, 0.15)');
        sweep.addColorStop(1, 'rgba(5, 150, 105, 0)');
        context.fillStyle = sweep;
        context.fillRect(sweepX - (sweepWidth / 2), 0, sweepWidth, height);
        animationId = requestAnimationFrame(render);
        return;
      }

      // 3. Render Captured Event Waveform with Robust Amplitude Scaling
      const rawSamples = activeSnippet?.waveform ?? [];
      if (rawSamples.length > 0) {
        // Calculate statistical range to prevent vertical bar artifact
        let minVal = Infinity;
        let maxVal = -Infinity;
        let sum = 0;
        for (let i = 0; i < rawSamples.length; i++) {
          const v = rawSamples[i];
          if (v < minVal) minVal = v;
          if (v > maxVal) maxVal = v;
          sum += v;
        }
        const mean = sum / rawSamples.length;
        const dynamicRange = Math.max(maxVal - minVal, 0.01);
        const scaleY = (height * 0.72) / dynamicRange;

        context.strokeStyle = '#1d4ed8'; // Crisp Clinical Blue
        context.lineWidth = 1.8 * dpr;
        context.lineCap = 'round';
        context.lineJoin = 'round';
        context.beginPath();

        for (let index = 0; index < rawSamples.length; index++) {
          const sample = rawSamples[index];
          const x = (index / Math.max(1, rawSamples.length - 1)) * width;
          const y = center - (sample - mean) * scaleY;
          if (index === 0) {
            context.moveTo(x, y);
          } else {
            context.lineTo(x, y);
          }
        }
        context.stroke();

        // 4. Beat Annotations markers
        (activeSnippet?.annotations ?? []).forEach((annotation) => {
          const x = (annotation.offsetMs / 4000) * width;
          context.strokeStyle =
            annotation.label === 'V'
              ? 'rgba(220, 38, 38, 0.6)'
              : annotation.label === 'S'
              ? 'rgba(217, 119, 6, 0.6)'
              : 'rgba(5, 150, 105, 0.4)';
          context.setLineDash([3 * dpr, 4 * dpr]);
          context.beginPath();
          context.moveTo(x, 16 * dpr);
          context.lineTo(x, height - 16 * dpr);
          context.stroke();
          context.setLineDash([]);
        });
      }
    };

    render();
    return () => {
      window.removeEventListener('resize', resizeCanvas);
      cancelAnimationFrame(animationId);
    };
  }, [activeSnippet, hasEvent]);

  return (
    <div className="rounded-lg border border-[var(--line)] bg-white overflow-hidden shadow-sm">
      <div className="flex min-h-[42px] items-center justify-between gap-3 border-b border-[var(--line)] px-4 py-2 bg-[var(--paper-2)]">
        <div className="flex items-center gap-2.5">
          <span className={`h-2 w-2 rounded-full ${hasEvent ? 'bg-[var(--cardiac-rose)]' : 'bg-[var(--clinical-teal)]'}`} />
          <div>
            <h2 className="text-xs font-semibold text-[var(--ink)]">
              {hasEvent ? 'ECG anomaly snapshot (4-second capture)' : 'Continuous ECG lead monitoring'}
            </h2>
          </div>
        </div>
        <div className="flex items-center gap-3">
          <span className="font-mono text-[10px] text-[var(--muted)]">
            Lead II • 25 mm/s • 250 Hz
          </span>
          {hasEvent && onClearSnapshot && (
            <button className="discovery-pill-secondary !py-0.5 !px-2.5 !min-h-[26px] !text-[10px]" onClick={onClearSnapshot}>
              <RefreshCw size={11} /> Return to live mode
            </button>
          )}
        </div>
      </div>

      <div ref={containerRef} className="waveform-grid relative h-[210px] sm:h-[240px] lg:h-[270px] bg-[#FFFFFF]">
        <canvas ref={canvasRef} className="block h-full w-full" />
        {!hasEvent && (
          <div className="absolute bottom-2.5 left-3 flex items-center gap-1.5 rounded bg-white/90 border border-[var(--line-soft)] px-2.5 py-1 text-[11px] font-medium text-[var(--ink)] shadow-xs">
            <Radio size={12} className="text-[var(--clinical-teal)]" />
            <span>Monitoring active • Awaiting event trigger</span>
          </div>
        )}
        {hasEvent && (
          <div className="absolute left-3 top-2.5 flex flex-wrap gap-1.5">
            {(activeSnippet?.annotations ?? []).map((annotation, index) => (
              <span
                key={`${annotation.offsetMs}-${index}`}
                className={`inline-flex items-center gap-1 rounded border px-1.5 py-0.5 font-mono text-[9px] font-semibold ${
                  annotation.label === 'V'
                    ? 'border-red-200 bg-red-50 text-red-700'
                    : annotation.label === 'S'
                    ? 'border-amber-200 bg-amber-50 text-amber-700'
                    : 'border-emerald-200 bg-emerald-50 text-emerald-700'
                }`}
              >
                <Zap size={9} /> {annotation.label === 'V' ? 'PVC' : annotation.label === 'S' ? 'PAC' : 'Normal'} ({Math.round(annotation.confidence * 100)}%)
              </span>
            ))}
          </div>
        )}
        <div className="pointer-events-none absolute bottom-2.5 right-3 flex items-center gap-1 font-mono text-[10px] text-[var(--muted)]">
          {hasEvent ? <><Activity size={12} className="text-[var(--deep-ocean)]" /> 4s event context</> : <><CheckCircle2 size={12} className="text-[var(--clinical-teal)]" /> Lead connected</>}
        </div>
      </div>
    </div>
  );
};
