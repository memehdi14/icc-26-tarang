'use client';

import React, { useEffect, useRef } from 'react';
import { ClinicalTelemetryPacket } from '../types/telemetry';

interface WaveformCanvasProps {
  telemetry: ClinicalTelemetryPacket;
}

export const WaveformCanvas: React.FC<WaveformCanvasProps> = ({ telemetry }) => {
  const canvasRef = useRef<HTMLCanvasElement | null>(null);

  useEffect(() => {
    const canvas = canvasRef.current;
    if (!canvas) return;
    const ctx = canvas.getContext('2d');
    if (!ctx) return;

    let animationId: number;
    const ecgBuffer: number[] = new Array(600).fill(0);
    const ppgBuffer: number[] = new Array(600).fill(0);
    const respBuffer: number[] = new Array(600).fill(0);

    let t = 0;
    const render = () => {
      t += 0.05;
      const hrBps = (telemetry.current_hr || 74) / 60;
      const beatCycle = (t * hrBps) % 1;

      // 1. P-Q-R-S-T ECG Waveform Synthesis
      let ecgVal = 0;
      if (beatCycle > 0.1 && beatCycle < 0.18) ecgVal = Math.sin(((beatCycle - 0.1) / 0.08) * Math.PI) * 0.15; // P wave
      else if (beatCycle > 0.22 && beatCycle < 0.25) ecgVal = -0.15; // Q wave
      else if (beatCycle >= 0.25 && beatCycle <= 0.29) ecgVal = 1.2 * Math.sin(((beatCycle - 0.25) / 0.04) * Math.PI); // R peak!
      else if (beatCycle > 0.29 && beatCycle < 0.33) ecgVal = -0.3; // S wave
      else if (beatCycle > 0.45 && beatCycle < 0.6) ecgVal = Math.sin(((beatCycle - 0.45) / 0.15) * Math.PI) * 0.25; // T wave
      ecgVal += (Math.random() - 0.5) * 0.03; // baseline noise

      // 2. PPG Plethysmogram Waveform Synthesis
      let ppgVal = 0;
      const ppgCycle = (beatCycle + 0.15) % 1;
      if (ppgCycle < 0.4) {
        ppgVal = Math.sin((ppgCycle / 0.4) * Math.PI);
        if (ppgCycle > 0.2 && ppgCycle < 0.25) ppgVal -= 0.1; // Dicrotic notch
      }

      // 3. Respiration / IMU Seismocardiogram Waveform Synthesis (slower 16 rpm wave)
      const respVal = Math.sin(t * 0.12) * 0.6 + Math.sin(t * 0.24) * 0.15 + (Math.random() - 0.5) * 0.02;

      ecgBuffer.push(ecgVal);
      ecgBuffer.shift();

      ppgBuffer.push(ppgVal);
      ppgBuffer.shift();

      respBuffer.push(respVal);
      respBuffer.shift();

      const width = canvas.width;
      const height = canvas.height;

      // Clear Canvas
      ctx.clearRect(0, 0, width, height);

      // Grid Lines
      ctx.strokeStyle = 'rgba(0, 78, 71, 0.06)';
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

      const zoneH = height / 3;

      // ── WAVE 1: ECG Lead II Trace (Teal #008378) ───────────────────────────
      ctx.strokeStyle = '#008378';
      ctx.lineWidth = 2.2;
      ctx.beginPath();
      for (let i = 0; i < ecgBuffer.length; i++) {
        const px = (i / ecgBuffer.length) * width;
        const py = zoneH * 0.55 - ecgBuffer[i] * 45;
        if (i === 0) ctx.moveTo(px, py);
        else ctx.lineTo(px, py);
      }
      ctx.stroke();

      // Divider 1
      ctx.strokeStyle = 'rgba(188, 201, 198, 0.4)';
      ctx.lineWidth = 1;
      ctx.beginPath();
      ctx.moveTo(0, zoneH);
      ctx.lineTo(width, zoneH);
      ctx.stroke();

      // ── WAVE 2: PPG Pulse Trace (Amber #d97706) ────────────────────────────
      ctx.strokeStyle = '#d97706';
      ctx.lineWidth = 2.0;
      ctx.beginPath();
      for (let i = 0; i < ppgBuffer.length; i++) {
        const px = (i / ppgBuffer.length) * width;
        const py = zoneH * 1.55 - ppgBuffer[i] * 35;
        if (i === 0) ctx.moveTo(px, py);
        else ctx.lineTo(px, py);
      }
      ctx.stroke();

      // Divider 2
      ctx.strokeStyle = 'rgba(188, 201, 198, 0.4)';
      ctx.lineWidth = 1;
      ctx.beginPath();
      ctx.moveTo(0, zoneH * 2);
      ctx.lineTo(width, zoneH * 2);
      ctx.stroke();

      // ── WAVE 3: RESP / IMU Wave Trace (Sky Blue #0284c7) ───────────────────
      ctx.strokeStyle = '#0284c7';
      ctx.lineWidth = 2.0;
      ctx.beginPath();
      for (let i = 0; i < respBuffer.length; i++) {
        const px = (i / respBuffer.length) * width;
        const py = zoneH * 2.55 - respBuffer[i] * 30;
        if (i === 0) ctx.moveTo(px, py);
        else ctx.lineTo(px, py);
      }
      ctx.stroke();

      animationId = requestAnimationFrame(render);
    };

    render();
    return () => cancelAnimationFrame(animationId);
  }, [telemetry]);

  return (
    <div className="card-clinical p-4 relative overflow-hidden flex flex-col h-[490px]">
      {/* Waveform Header Channel Labels */}
      <div className="flex items-center justify-between pb-3 border-b border-[var(--color-outline-variant)]">
        <div className="flex items-center gap-6">
          <div className="flex items-center gap-2">
            <span className="w-3 h-3 rounded-full bg-[#008378]"></span>
            <span className="text-xs font-bold tracking-wide text-[var(--color-on-surface)]">WAVE 1: ECG LEAD II (250 Hz)</span>
            <span className="text-[11px] font-mono text-[var(--color-on-surface-variant)]">Gain: 10mm/mV</span>
          </div>

          <div className="flex items-center gap-2">
            <span className="w-3 h-3 rounded-full bg-amber-500"></span>
            <span className="text-xs font-bold tracking-wide text-[var(--color-on-surface)]">WAVE 2: PPG PLETH (100 Hz)</span>
            <span className="text-[11px] font-mono text-[var(--color-on-surface-variant)]">AC/DC: Auto</span>
          </div>

          <div className="flex items-center gap-2">
            <span className="w-3 h-3 rounded-full bg-sky-500"></span>
            <span className="text-xs font-bold tracking-wide text-[var(--color-on-surface)]">WAVE 3: RESP / IMU (50 Hz)</span>
            <span className="text-[11px] font-mono text-[var(--color-on-surface-variant)]">Chest Motion: Normal</span>
          </div>
        </div>

        <div className="flex items-center gap-3 text-xs font-mono text-[var(--color-on-surface-variant)]">
          <span>Speed: 25 mm/s</span>
          <span className="px-2 py-0.5 rounded bg-[var(--color-surface-container-high)] text-[var(--color-primary)] font-semibold">
            3-CHANNEL CONTINUOUS
          </span>
        </div>
      </div>

      {/* Waveform Canvas Viewport */}
      <div className="flex-1 relative mt-2 rounded-lg overflow-hidden border border-[var(--color-surface-container-high)] waveform-grid">
        <canvas
          ref={canvasRef}
          width={800}
          height={400}
          className="w-full h-full block"
        />

        {/* Live Channel Status Overlay Badges */}
        <div className="absolute top-2 left-3 text-[10px] font-mono font-bold text-[#008378] bg-white/90 px-2 py-0.5 rounded border border-[var(--color-outline-variant)]">
          ECG R-Peak Lock: ON
        </div>
        <div className="absolute top-[138px] left-3 text-[10px] font-mono font-bold text-amber-700 bg-white/90 px-2 py-0.5 rounded border border-[var(--color-outline-variant)]">
          PPG SpO2 Pulse: {telemetry.spo2_pct || 98}%
        </div>
        <div className="absolute top-[272px] left-3 text-[10px] font-mono font-bold text-sky-700 bg-white/90 px-2 py-0.5 rounded border border-[var(--color-outline-variant)]">
          RESP Rate: {telemetry.resp_rate || 16} rpm
        </div>
      </div>
    </div>
  );
};
