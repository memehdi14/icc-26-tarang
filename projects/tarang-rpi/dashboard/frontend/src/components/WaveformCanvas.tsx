'use client';

import React, { useEffect, useRef, useState } from 'react';
import { ClinicalEvent, EcgSnippet, BeatAnnotation } from '../types/telemetry';
import { Radio, Sparkles, CheckCircle2, AlertOctagon, RefreshCw, Cpu, Zap } from 'lucide-react';

interface WaveformCanvasProps {
  currentEvent?: ClinicalEvent | null;
  activeSnippet?: EcgSnippet | null;
  onClearSnapshot?: () => void;
}

export const WaveformCanvas: React.FC<WaveformCanvasProps> = ({
  currentEvent,
  activeSnippet,
  onClearSnapshot,
}) => {
  const canvasRef = useRef<HTMLCanvasElement | null>(null);
  const [hoveredAnnotation, setHoveredAnnotation] = useState<BeatAnnotation | null>(null);

  const hasEvent = !!activeSnippet && (activeSnippet.waveform?.length ?? 0) > 0;

  useEffect(() => {
    const canvas = canvasRef.current;
    if (!canvas) return;
    const ctx = canvas.getContext('2d');
    if (!ctx) return;

    let animationId: number;
    let phase = 0;

    const render = () => {
      const width = canvas.width;
      const height = canvas.height;

      ctx.clearRect(0, 0, width, height);

      // ── Background Grid ─────────────────────────────────────────────────────
      ctx.strokeStyle = 'rgba(0, 78, 71, 0.05)';
      ctx.lineWidth = 1;
      for (let x = 0; x < width; x += 20) {
        ctx.beginPath();
        ctx.moveTo(x, 0);
        ctx.lineTo(x, height);
        ctx.stroke();
      }
      for (let y = 0; y < height; y += 20) {
        ctx.beginPath();
        ctx.moveTo(0, y);
        ctx.lineTo(width, y);
        ctx.stroke();
      }

      if (!hasEvent) {
        // ── MODE A IDLE STATE: Ambient Low-Power Scan Line Animation ──────────
        phase += 0.02;
        const midY = height / 2;

        // Subtle pulsing ambient wave
        ctx.strokeStyle = 'rgba(0, 131, 120, 0.35)';
        ctx.lineWidth = 2.0;
        ctx.beginPath();
        for (let x = 0; x < width; x++) {
          const normX = x / width;
          const y = midY + Math.sin(normX * 8 + phase) * 8 * Math.sin(normX * Math.PI);
          if (x === 0) ctx.moveTo(x, y);
          else ctx.lineTo(x, y);
        }
        ctx.stroke();

        // Scanning light sweep
        const sweepX = ((phase * 120) % (width + 200)) - 100;
        const grad = ctx.createLinearGradient(sweepX - 80, 0, sweepX + 80, 0);
        grad.addColorStop(0, 'rgba(0, 131, 120, 0)');
        grad.addColorStop(0.5, 'rgba(0, 131, 120, 0.15)');
        grad.addColorStop(1, 'rgba(0, 131, 120, 0)');
        ctx.fillStyle = grad;
        ctx.fillRect(sweepX - 80, 0, 160, height);

        animationId = requestAnimationFrame(render);
        return;
      }

      // ── MODE A EVENT SNAPSHOT: 4s High-Resolution ECG Waveform Display ─────
      const waveform = activeSnippet?.waveform || [];
      const len = waveform.length;

      if (len > 0) {
        const midY = height / 2;
        const scaleY = height * 0.35;

        // Draw Baseline Trace
        ctx.strokeStyle = '#008378';
        ctx.lineWidth = 2.4;
        ctx.lineJoin = 'round';
        ctx.beginPath();

        for (let i = 0; i < len; i++) {
          const x = (i / (len - 1)) * width;
          const y = midY - waveform[i] * scaleY;
          if (i === 0) ctx.moveTo(x, y);
          else ctx.lineTo(x, y);
        }
        ctx.stroke();

        // Glow effect
        ctx.strokeStyle = 'rgba(0, 131, 120, 0.15)';
        ctx.lineWidth = 6;
        ctx.stroke();

        // ── Render AI Beat Annotations (Markers & Vertical Guides) ────────────
        const annotations = activeSnippet?.annotations || [];
        annotations.forEach((annot) => {
          // offset_ms mapped to 0..4000ms
          const annotX = (annot.offsetMs / 4000) * width;

          // Vertical guideline
          ctx.strokeStyle = annot.label === 'V' ? 'rgba(239, 68, 68, 0.3)' : annot.label === 'S' ? 'rgba(245, 158, 11, 0.3)' : 'rgba(16, 185, 129, 0.2)';
          ctx.setLineDash([4, 4]);
          ctx.beginPath();
          ctx.moveTo(annotX, 30);
          ctx.lineTo(annotX, height - 30);
          ctx.stroke();
          ctx.setLineDash([]);

          // Circle anchor on waveform
          const sampleIdx = Math.min(len - 1, Math.max(0, Math.round((annot.offsetMs / 4000) * len)));
          const anchorY = midY - (waveform[sampleIdx] || 0) * scaleY;

          ctx.fillStyle = annot.label === 'V' ? '#ef4444' : annot.label === 'S' ? '#f59e0b' : '#10b981';
          ctx.beginPath();
          ctx.arc(annotX, anchorY, 4, 0, Math.PI * 2);
          ctx.fill();
        });
      }
    };

    render();
    return () => cancelAnimationFrame(animationId);
  }, [hasEvent, activeSnippet]);

  return (
    <div className="card-clinical p-4 relative overflow-hidden flex flex-col h-[490px]">
      {/* Header Bar */}
      <div className="flex items-center justify-between pb-3 border-b border-[var(--color-outline-variant)]">
        <div className="flex items-center gap-4">
          <div className="flex items-center gap-2">
            {hasEvent ? (
              <span className="w-3 h-3 rounded-full bg-amber-500 animate-pulse"></span>
            ) : (
              <span className="w-3 h-3 rounded-full bg-emerald-500"></span>
            )}
            <span className="text-xs font-bold tracking-wide text-[var(--color-on-surface)] uppercase">
              {hasEvent ? 'ANOMALY SNAPSHOT: 4s ECG WAVEFORM' : 'MODE A: EVENT-DRIVEN WAVEFORM VIEWER'}
            </span>
          </div>

          {hasEvent && (
            <span className="px-2.5 py-0.5 rounded text-[11px] font-mono font-bold bg-amber-100 text-amber-900 border border-amber-300 flex items-center gap-1">
              <Zap className="w-3 h-3" /> Event Triggered Snapshot
            </span>
          )}
        </div>

        <div className="flex items-center gap-3 text-xs font-mono text-[var(--color-on-surface-variant)]">
          {hasEvent ? (
            <>
              <span>Sample Rate: 250 Hz (1000 pts)</span>
              {onClearSnapshot && (
                <button
                  onClick={onClearSnapshot}
                  className="px-2.5 py-1 rounded bg-[var(--color-surface-container-high)] text-[var(--color-primary)] font-semibold hover:bg-emerald-50 flex items-center gap-1 transition-colors"
                >
                  <RefreshCw className="w-3 h-3" /> Return to Low-Power Standby
                </button>
              )}
            </>
          ) : (
            <span className="px-2.5 py-1 rounded bg-emerald-50 text-emerald-800 border border-emerald-200 font-semibold flex items-center gap-1.5">
              <Radio className="w-3.5 h-3.5 text-emerald-600 animate-pulse" />
              EM2 Low-Power Standby
            </span>
          )}
        </div>
      </div>

      {/* Main Canvas Viewport */}
      <div className="flex-1 relative mt-2 rounded-lg overflow-hidden border border-[var(--color-surface-container-high)] waveform-grid bg-white">
        <canvas
          ref={canvasRef}
          width={800}
          height={400}
          className="w-full h-full block cursor-crosshair"
        />

        {/* ── Idle State Hero Banner Overlay ─────────────────────────────────── */}
        {!hasEvent && (
          <div className="absolute inset-0 flex flex-col items-center justify-center bg-white/60 backdrop-blur-[1px] text-center p-6 pointer-events-none">
            <div className="w-12 h-12 rounded-full bg-emerald-100 flex items-center justify-center text-emerald-700 mb-3 shadow-sm border border-emerald-200">
              <Cpu className="w-6 h-6 animate-pulse" />
            </div>
            <h3 className="text-base font-extrabold text-[var(--color-on-surface)] tracking-tight">
              Monitoring in Low-Power Mode (EM2 Standby)
            </h3>
            <p className="text-xs text-[var(--color-on-surface-variant)] mt-1 max-w-md">
              Continuous streaming disabled to conserve energy (~92% EM2 sleep). High-resolution 4s ECG snippets and AI annotations are captured and pushed instantly on anomaly detection.
            </p>
            <div className="mt-4 flex items-center gap-4 text-[11px] font-mono text-emerald-800">
              <span className="flex items-center gap-1 bg-white/90 px-2.5 py-1 rounded-full border border-emerald-200">
                <CheckCircle2 className="w-3.5 h-3.5 text-emerald-600" /> Pan-Tompkins Tier-0 Active
              </span>
              <span className="flex items-center gap-1 bg-white/90 px-2.5 py-1 rounded-full border border-emerald-200">
                <Sparkles className="w-3.5 h-3.5 text-teal-600" /> TFLite Micro Armed
              </span>
            </div>
          </div>
        )}

        {/* ── Event Beat Annotation Badges Overlay ────────────────────────────── */}
        {hasEvent && activeSnippet?.annotations && (
          <div className="absolute top-3 left-3 right-3 flex justify-between pointer-events-none">
            {activeSnippet.annotations.map((annot, idx) => (
              <div
                key={idx}
                className={`px-2.5 py-1 rounded shadow-sm text-[11px] font-mono font-bold border pointer-events-auto transition-transform hover:scale-105 ${
                  annot.label === 'V'
                    ? 'bg-red-50 text-red-900 border-red-300'
                    : annot.label === 'S'
                    ? 'bg-amber-50 text-amber-900 border-amber-300'
                    : 'bg-emerald-50 text-emerald-900 border-emerald-300'
                }`}
                title={`Offset: ${annot.offsetMs}ms | Conf: ${(annot.confidence * 100).toFixed(1)}%`}
              >
                <div className="flex items-center gap-1">
                  <span>
                    {annot.label === 'V'
                      ? 'PVC (V-Class)'
                      : annot.label === 'S'
                      ? 'PAC (S-Class)'
                      : 'NORMAL (N)'}
                  </span>
                  <span className="text-[10px] opacity-75 font-normal">
                    {(annot.confidence * 100).toFixed(0)}%
                  </span>
                </div>
                <div className="text-[9px] opacity-70">t = {annot.offsetMs}ms</div>
              </div>
            ))}
          </div>
        )}

        {/* Bottom Time Axis */}
        <div className="absolute bottom-2 left-4 right-4 flex justify-between text-[10px] font-mono text-[var(--color-on-surface-variant)] pointer-events-none">
          <span>0.0s (Trigger -1.0s)</span>
          <span>1.0s</span>
          <span>2.0s (Anomaly Center)</span>
          <span>3.0s</span>
          <span>4.0s (Trigger +3.0s)</span>
        </div>
      </div>
    </div>
  );
};
