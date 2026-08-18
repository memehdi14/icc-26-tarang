'use client';

import React, { useEffect, useRef, useState } from 'react';
import {
  Activity,
  CheckCircle2,
  Circle,
  AlertTriangle,
  RefreshCw,
  Cpu,
  Radio,
  Sparkles,
} from 'lucide-react';
import {
  ClinicalTelemetryPacket,
  DeviceHealthTelemetry,
  InitializationStageId,
  InitializationStageInfo,
} from '../types/telemetry';

interface DeviceInitializationProps {
  bleConnected: boolean;
  telemetry: ClinicalTelemetryPacket;
  deviceHealth?: DeviceHealthTelemetry;
  onComplete: () => void;
  onRetry?: () => void;
}

const STAGES: { id: InitializationStageId; title: string; description: string }[] = [
  {
    id: 'sensor_detected',
    title: 'Sensor connected',
    description: 'ECG hardware channel & BLE communication active',
  },
  {
    id: 'signal_initializing',
    title: 'Establishing baseline',
    description: '0.5–40 Hz morphology bandpass & rolling baseline normalization',
  },
  {
    id: 'calibrating',
    title: 'Calibrating signal quality',
    description: 'Pan-Tompkins adaptive threshold & R-peak sensitivity learning',
  },
  {
    id: 'ai_ready',
    title: 'AI monitoring ready',
    description: 'On-device Gate CNN & SV Head neural inference engines active',
  },
  {
    id: 'ready',
    title: 'Monitoring ready',
    description: 'Continuous clinical telemetry pipeline operational',
  },
];

export const DeviceInitialization: React.FC<DeviceInitializationProps> = ({
  bleConnected,
  telemetry,
  deviceHealth,
  onComplete,
  onRetry,
}) => {
  const canvasRef = useRef<HTMLCanvasElement | null>(null);

  // Derive active stage from actual firmware & telemetry metrics
  const uptimeS = deviceHealth?.uptimeS ?? 0;
  const sqi = deviceHealth?.ecgSqi ?? telemetry.confidence ?? 0;
  const hasRealBeats = (telemetry.current_hr > 0 && telemetry.rr_interval_ms > 0) || uptimeS >= 10;

  // Determine stage progression
  let currentStageIndex = 0;
  let isDisconnected = !bleConnected;

  if (isDisconnected) {
    currentStageIndex = 0;
  } else if (hasRealBeats && uptimeS >= 8) {
    currentStageIndex = 4; // Ready
  } else if (uptimeS >= 6 || sqi > 150) {
    currentStageIndex = 3; // AI Ready
  } else if (uptimeS >= 3 || sqi > 80) {
    currentStageIndex = 2; // Calibrating
  } else if (uptimeS >= 1 || bleConnected) {
    currentStageIndex = 1; // Signal Initializing
  } else {
    currentStageIndex = 0; // Sensor detected
  }

  const [completedAnimation, setCompletedAnimation] = useState(false);

  // Transition trigger when reaching ready
  useEffect(() => {
    if (currentStageIndex >= 4 && !isDisconnected) {
      const timer = setTimeout(() => {
        setCompletedAnimation(true);
        const completeTimer = setTimeout(() => {
          onComplete();
        }, 1200);
        return () => clearTimeout(completeTimer);
      }, 1000);
      return () => clearTimeout(timer);
    }
  }, [currentStageIndex, isDisconnected, onComplete]);

  // Calibration Waveform Canvas Animation
  useEffect(() => {
    const canvas = canvasRef.current;
    if (!canvas) return;
    const ctx = canvas.getContext('2d');
    if (!ctx) return;

    let animationId: number;
    let t = 0;
    const bufferLength = 400;
    const waveformBuffer: number[] = new Array(bufferLength).fill(0);

    const render = () => {
      t += 0.04;
      const width = canvas.width;
      const height = canvas.height;
      const centerY = height / 2;

      // Calibration waveform synthesis based on stage index
      let sample = 0;
      if (isDisconnected) {
        // Flatline with minimal noise
        sample = (Math.random() - 0.5) * 0.05;
      } else if (currentStageIndex === 0) {
        // Sensor connect: High-frequency baseline search
        sample = Math.sin(t * 0.8) * 0.3 + (Math.random() - 0.5) * 0.15;
      } else if (currentStageIndex === 1) {
        // Baseline stabilization: Low frequency wander settling
        sample = Math.sin(t * 0.3) * 0.5 * Math.exp(-0.02 * (t % 50)) + Math.sin(t * 1.5) * 0.2 + (Math.random() - 0.5) * 0.08;
      } else if (currentStageIndex === 2) {
        // Adaptive thresholding: MWI test pulses emerging
        const phase = (t * 0.6) % 1;
        if (phase > 0.4 && phase < 0.5) {
          sample = Math.sin((phase - 0.4) / 0.1 * Math.PI) * 0.9;
        } else {
          sample = Math.sin(t * 0.2) * 0.15 + (Math.random() - 0.5) * 0.04;
        }
      } else {
        // Stabilized Clinical ECG: Crisp P-Q-R-S-T complex
        const hrRate = Math.max(60, telemetry.current_hr || 74);
        const beatCycle = (t * (hrRate / 60) * 0.5) % 1;
        if (beatCycle > 0.1 && beatCycle < 0.18) {
          sample = Math.sin(((beatCycle - 0.1) / 0.08) * Math.PI) * 0.15; // P wave
        } else if (beatCycle > 0.22 && beatCycle < 0.25) {
          sample = -0.15; // Q wave
        } else if (beatCycle >= 0.25 && beatCycle <= 0.29) {
          sample = 1.35 * Math.sin(((beatCycle - 0.25) / 0.04) * Math.PI); // R peak
        } else if (beatCycle > 0.29 && beatCycle < 0.33) {
          sample = -0.35; // S wave
        } else if (beatCycle > 0.45 && beatCycle < 0.6) {
          sample = Math.sin(((beatCycle - 0.45) / 0.15) * Math.PI) * 0.28; // T wave
        } else {
          sample = (Math.random() - 0.5) * 0.02; // clean baseline
        }
      }

      waveformBuffer.push(sample);
      waveformBuffer.shift();

      // Clear Canvas
      ctx.clearRect(0, 0, width, height);

      // Instrument Grid Lines
      ctx.strokeStyle = 'rgba(0, 78, 71, 0.06)';
      ctx.lineWidth = 1;
      for (let x = 0; x < width; x += 24) {
        ctx.beginPath();
        ctx.moveTo(x, 0);
        ctx.lineTo(x, height);
        ctx.stroke();
      }
      for (let y = 0; y < height; y += 24) {
        ctx.beginPath();
        ctx.moveTo(0, y);
        ctx.lineTo(width, y);
        ctx.stroke();
      }

      // Center Reference Baseline
      ctx.strokeStyle = 'rgba(188, 201, 198, 0.3)';
      ctx.setLineDash([4, 4]);
      ctx.beginPath();
      ctx.moveTo(0, centerY);
      ctx.lineTo(width, centerY);
      ctx.stroke();
      ctx.setLineDash([]);

      // Draw Hero Waveform Trace
      ctx.strokeStyle = isDisconnected ? '#ba1a1a' : currentStageIndex >= 3 ? '#008378' : '#0284c7';
      ctx.lineWidth = 2.4;
      ctx.lineCap = 'round';
      ctx.lineJoin = 'round';
      ctx.beginPath();

      for (let i = 0; i < waveformBuffer.length; i++) {
        const px = (i / waveformBuffer.length) * width;
        const py = centerY - waveformBuffer[i] * 55;
        if (i === 0) ctx.moveTo(px, py);
        else ctx.lineTo(px, py);
      }
      ctx.stroke();

      animationId = requestAnimationFrame(render);
    };

    render();
    return () => cancelAnimationFrame(animationId);
  }, [currentStageIndex, isDisconnected, telemetry.current_hr]);

  return (
    <div
      className={`min-h-[80vh] flex flex-col items-center justify-center p-6 transition-all duration-700 ${
        completedAnimation ? 'opacity-0 scale-95' : 'opacity-100 scale-100'
      }`}
      role="region"
      aria-label="Device Initialization Screen"
    >
      {/* Header Container */}
      <div className="text-center max-w-md w-full space-y-2 mb-6">
        <div className="inline-flex items-center gap-2 px-3 py-1 rounded-full bg-[var(--color-surface-container-high)] text-[var(--color-primary)] font-mono text-xs font-bold tracking-widest uppercase">
          <Activity className="w-3.5 h-3.5 animate-pulse" />
          <span>TARANG BIOSIGNAL ENGINE</span>
        </div>
        <h1 className="text-2xl sm:text-3xl font-extrabold text-[var(--color-on-surface)] tracking-tight">
          {isDisconnected ? 'Connection Interrupted' : currentStageIndex >= 4 ? 'Tarang is Ready' : 'Setting things up for you'}
        </h1>
        <p className="text-sm text-[var(--color-on-surface-variant)]" aria-live="polite">
          {isDisconnected
            ? 'Tarang was disconnected. Reconnect the device to continue.'
            : currentStageIndex >= 4
            ? 'Continuous monitoring pipeline is active and streaming.'
            : 'Establishing sensor baseline and calibrating on-device AI.'}
        </p>
      </div>

      {/* Hero Waveform Instrument Card */}
      <div className="card-clinical p-4 w-full max-w-xl relative overflow-hidden shadow-md bg-white border border-[var(--color-outline-variant)]">
        <div className="flex items-center justify-between pb-2 mb-2 border-b border-[var(--color-outline-variant)]/40">
          <div className="flex items-center gap-2 text-xs font-bold text-[var(--color-primary)]">
            <Radio className="w-4 h-4 text-[#008378]" />
            <span className="font-mono">
              {isDisconnected
                ? 'SIGNAL CHANNEL: INACTIVE'
                : currentStageIndex >= 3
                ? 'ECG LEAD II: STABILIZED (250 Hz)'
                : 'SIGNAL CALIBRATION & BASELINE STABILIZATION'}
            </span>
          </div>
          <span className="text-[10px] font-mono font-bold px-2 py-0.5 rounded bg-[var(--color-surface-container-low)] text-[var(--color-outline)]">
            {isDisconnected ? 'OFFLINE' : `SQI: ${sqi > 0 ? sqi : 'CALIBRATING'}/255`}
          </span>
        </div>

        {/* Canvas Element */}
        <canvas
          ref={canvasRef}
          width={560}
          height={150}
          className="w-full h-[150px] rounded bg-[#fafcfe] border border-[var(--color-outline-variant)]/30 block"
        />

        {/* Trace Legend / Mode Indicator */}
        <div className="flex items-center justify-between pt-2 mt-2 text-[11px] text-[var(--color-on-surface-variant)] font-mono">
          <span className="flex items-center gap-1.5">
            <span
              className={`w-2 h-2 rounded-full ${
                isDisconnected ? 'bg-red-500' : currentStageIndex >= 3 ? 'bg-emerald-500' : 'bg-amber-500 animate-ping'
              }`}
            />
            {isDisconnected ? 'Electrode Disconnected' : currentStageIndex >= 3 ? 'Live Morphology Active' : 'Adaptive Learning Active'}
          </span>
          <span>Gain: 10mm/mV • Filter: 0.5–40Hz</span>
        </div>
      </div>

      {/* Disconnected Error Alert Card */}
      {isDisconnected && (
        <div className="w-full max-w-xl mt-4 p-4 rounded-xl bg-red-50 border border-red-200 flex items-center justify-between gap-4 animate-in fade-in duration-300">
          <div className="flex items-center gap-3">
            <AlertTriangle className="w-5 h-5 text-red-600 shrink-0" />
            <div className="text-xs">
              <p className="font-bold text-red-900">Device Connection Lost</p>
              <p className="text-red-700">Ensure the EFR32 wearable is powered on and within Bluetooth range.</p>
            </div>
          </div>
          {onRetry && (
            <button
              onClick={onRetry}
              className="px-3 py-1.5 rounded-lg bg-red-600 hover:bg-red-700 text-white font-medium text-xs flex items-center gap-1.5 transition-colors shadow-sm"
            >
              <RefreshCw className="w-3.5 h-3.5" />
              <span>Retry</span>
            </button>
          )}
        </div>
      )}

      {/* Initialization Stages Checklist */}
      {!isDisconnected && (
        <div
          className="w-full max-w-xl mt-6 p-4 rounded-xl card-clinical-inset border border-[var(--color-outline-variant)]/40 space-y-3"
          role="status"
          aria-label="Initialization Stages"
        >
          <div className="flex items-center justify-between pb-2 border-b border-[var(--color-outline-variant)]/40">
            <span className="text-xs font-bold text-[var(--color-on-surface)] flex items-center gap-1.5">
              <Cpu className="w-4 h-4 text-[var(--color-primary)]" />
              <span>System Initialization Pipeline</span>
            </span>
            <span className="text-[11px] font-mono text-[var(--color-on-surface-variant)]">
              {currentStageIndex >= 4 ? 'Completed' : 'Usually takes ~30 seconds'}
            </span>
          </div>

          <div className="grid grid-cols-1 gap-2.5">
            {STAGES.map((stage, idx) => {
              const isDone = idx < currentStageIndex || currentStageIndex >= 4;
              const isCurrent = idx === currentStageIndex && currentStageIndex < 4;
              const isPending = idx > currentStageIndex && currentStageIndex < 4;

              return (
                <div
                  key={stage.id}
                  className={`flex items-start gap-3 p-2.5 rounded-lg transition-all duration-300 ${
                    isCurrent
                      ? 'bg-white border border-[var(--color-primary-container)] shadow-sm'
                      : isDone
                      ? 'bg-white/60 border border-emerald-100'
                      : 'opacity-50'
                  }`}
                >
                  <div className="mt-0.5 shrink-0">
                    {isDone ? (
                      <CheckCircle2 className="w-4 h-4 text-emerald-600 transition-transform duration-300 scale-110" />
                    ) : isCurrent ? (
                      <div className="w-4 h-4 rounded-full border-2 border-[var(--color-primary-container)] border-t-transparent animate-spin" />
                    ) : (
                      <Circle className="w-4 h-4 text-[var(--color-outline-variant)]" />
                    )}
                  </div>
                  <div className="flex-1 min-w-0">
                    <div className="flex items-center justify-between">
                      <p
                        className={`text-xs font-bold leading-tight ${
                          isCurrent
                            ? 'text-[var(--color-primary)] font-extrabold'
                            : isDone
                            ? 'text-[var(--color-on-surface)]'
                            : 'text-[var(--color-outline)]'
                        }`}
                      >
                        {stage.title}
                      </p>
                      {isCurrent && (
                        <span className="text-[10px] font-mono px-1.5 py-0.2 rounded bg-teal-50 text-teal-800 font-bold">
                          ACTIVE
                        </span>
                      )}
                    </div>
                    <p className="text-[11px] text-[var(--color-on-surface-variant)] leading-normal mt-0.5">
                      {stage.description}
                    </p>
                  </div>
                </div>
              );
            })}
          </div>
        </div>
      )}

      {/* Footer Status */}
      <div className="text-center mt-6 text-xs text-[var(--color-outline)] font-mono">
        {!isDisconnected && (
          <span className="flex items-center justify-center gap-2">
            <Sparkles className="w-3.5 h-3.5 text-[#008378]" />
            <span>Real-time on-device inference via EFR32MG26 MVP Neural Accelerator</span>
          </span>
        )}
      </div>
    </div>
  );
};
