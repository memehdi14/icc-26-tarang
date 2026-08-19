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
  const canvasRef = useRef<HTMLCanvasElement | null>(null);
  const hasEvent = Boolean(activeSnippet && (activeSnippet.waveform?.length ?? 0) > 0);

  useEffect(() => {
    const canvas = canvasRef.current;
    const context = canvas?.getContext('2d');
    if (!canvas || !context) return;
    let animationId = 0;
    let phase = 0;

    const render = () => {
      const width = canvas.width;
      const height = canvas.height;
      context.clearRect(0, 0, width, height);
      context.strokeStyle = 'rgba(40, 89, 197, 0.055)';
      context.lineWidth = 1;
      for (let x = 0; x < width; x += 20) {
        context.beginPath(); context.moveTo(x, 0); context.lineTo(x, height); context.stroke();
      }
      for (let y = 0; y < height; y += 20) {
        context.beginPath(); context.moveTo(0, y); context.lineTo(width, y); context.stroke();
      }

      if (!hasEvent) {
        phase += 0.022;
        const center = height / 2;
        context.strokeStyle = '#008378';
        context.lineWidth = 1.8;
        context.beginPath();
        for (let x = 0; x < width; x += 1) {
          const cycle = ((x / width) * 7 + phase * 0.8) % 1;
          let y = center + Math.sin(x * 0.028 + phase) * 2.5;
          if (cycle > 0.35 && cycle < 0.39) y -= Math.sin((cycle - 0.35) / 0.04 * Math.PI) * 11;
          if (cycle > 0.46 && cycle < 0.48) y -= Math.sin((cycle - 0.46) / 0.02 * Math.PI) * 48;
          if (cycle > 0.48 && cycle < 0.51) y += Math.sin((cycle - 0.48) / 0.03 * Math.PI) * 18;
          if (cycle > 0.60 && cycle < 0.70) y -= Math.sin((cycle - 0.60) / 0.10 * Math.PI) * 9;
          if (x === 0) context.moveTo(x, y); else context.lineTo(x, y);
        }
        context.stroke();

        const sweepX = (phase * 160) % (width + 180) - 90;
        const sweep = context.createLinearGradient(sweepX - 90, 0, sweepX + 90, 0);
        sweep.addColorStop(0, 'rgba(0,131,120,0)');
        sweep.addColorStop(0.5, 'rgba(0,131,120,0.1)');
        sweep.addColorStop(1, 'rgba(0,131,120,0)');
        context.fillStyle = sweep;
        context.fillRect(sweepX - 90, 0, 180, height);
        animationId = requestAnimationFrame(render);
        return;
      }

      const waveform = activeSnippet?.waveform ?? [];
      const center = height / 2;
      const scaleY = height * 0.34;
      context.strokeStyle = '#2859c5';
      context.lineWidth = 2;
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
        context.setLineDash([4, 5]);
        context.beginPath(); context.moveTo(x, 24); context.lineTo(x, height - 24); context.stroke();
        context.setLineDash([]);
      });
    };

    render();
    return () => cancelAnimationFrame(animationId);
  }, [activeSnippet, hasEvent]);

  return (
    <div className="clinical-panel overflow-hidden bg-white">
      <div className="flex min-h-[60px] items-center justify-between gap-4 border-b border-[var(--color-outline-variant)] px-5 py-3 max-md:items-start max-md:flex-col">
        <div className="flex items-center gap-3">
          <span className={`status-dot ${hasEvent ? 'text-[var(--color-warning)]' : 'pulse-dot text-[var(--color-success)]'}`} />
          <div>
            <h2 className="text-sm font-bold">{hasEvent ? 'Event ECG snapshot' : 'ECG lead II'}</h2>
            <p className="eyebrow mt-0.5">{hasEvent ? '4-second high-resolution capture' : 'Event-driven live preview'}</p>
          </div>
        </div>
        <div className="flex items-center gap-3">
          <span className="eyebrow">25 mm/s&nbsp;&nbsp;10 mm/mV&nbsp;&nbsp;250 Hz</span>
          {hasEvent && onClearSnapshot && <button className="button-quiet" onClick={onClearSnapshot}><RefreshCw size={15} /> Return live</button>}
        </div>
      </div>

      <div className="waveform-grid relative h-[310px] bg-white">
        <canvas ref={canvasRef} width={1100} height={310} className="block h-full w-full" />
        {!hasEvent && (
          <div className="absolute bottom-3 left-4 flex items-center gap-2 rounded bg-white/90 px-2.5 py-1.5 text-[11px] font-semibold text-[var(--color-primary)]">
            <Radio size={14} /> Monitoring active / high-resolution capture on anomaly
          </div>
        )}
        {hasEvent && (
          <div className="absolute left-4 top-3 flex flex-wrap gap-2">
            {(activeSnippet?.annotations ?? []).map((annotation, index) => (
              <span key={`${annotation.offsetMs}-${index}`} className={`inline-flex items-center gap-1 rounded border bg-white px-2 py-1 font-mono text-[10px] font-bold ${annotation.label === 'V' ? 'border-red-300 text-red-800' : annotation.label === 'S' ? 'border-amber-300 text-amber-800' : 'border-emerald-300 text-emerald-800'}`}>
                <Zap size={11} /> {annotation.label} / {Math.round(annotation.confidence * 100)}%
              </span>
            ))}
          </div>
        )}
        <div className="pointer-events-none absolute bottom-3 right-4 flex items-center gap-2 font-mono text-[10px] text-[var(--color-on-surface-variant)]">
          {hasEvent ? <><Activity size={13} /> Trigger -1.0s to +3.0s</> : <><CheckCircle2 size={13} /> Inference armed</>}
        </div>
      </div>
    </div>
  );
};
