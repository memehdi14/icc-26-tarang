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

// ==========================================
// RENDERING & ANATOMICAL CONSTANTS (LIGHT THEME)
// ==========================================
const CANVAS_WIDTH = 960;
const CANVAS_HEIGHT = 540;
const FOCAL_LENGTH = 500;
const CAMERA_DISTANCE = 350;
const CLIP_Z = 20;

const SYSTOLE_DURATION = 0.22;
const DIASTOLE_DURATION = 0.20;
const SYSTOLE_CONTRACTION_MAX = 0.10;
const DIASTOLE_EXPANSION_MAX = 0.04;

// Light Clinical Theme Canvas Background
const BACKGROUND_COLOR = '#FAFAF9';
const GRID_STEP = 32;
const GRID_STROKE = 'rgba(24, 24, 22, 0.035)';

interface DeviceInitializationProps {
  backendOnline: boolean;
  bleConnected: boolean;
  telemetry: ClinicalTelemetryPacket;
  telemetryReady: boolean;
  deviceHealth?: DeviceHealthTelemetry;
  deviceName?: string;
  sessionLabel?: string;
  lowPower?: boolean;
  onComplete: () => void;
  onRetry: () => void;
  onBack: () => void;
}

interface VoxelPoint {
  tx: number;
  ty: number;
  tz: number;
  ox: number;
  oy: number;
  oz: number;
  delay: number;
  size: number;
  baseBrightness: number;
  isCore?: boolean;
  isVessel?: boolean;
  isArtery?: boolean;
}

interface RingParticle {
  angle: number;
  radius: number;
  speed: number;
  yOffset: number;
  tilt: number;
  size: number;
  alpha: number;
}

const STAGES = [
  { title: 'Clinical services', detail: 'Database and monitoring session ready', icon: Database },
  { title: 'BLE channel', detail: 'Tarang GATT services connected', icon: Radio },
  { title: 'Telemetry path', detail: 'First measured vitals received from wearable', icon: Activity },
  { title: 'Inference runtime', detail: 'Edge DSP and AI runtime settling', icon: Cpu },
  { title: 'Ready', detail: 'Clinical telemetry can begin', icon: ShieldCheck },
];

/**
 * Procedural Generator for 3D Anatomical Human Heart Voxels.
 */
function generateAnatomicalHeartVoxels(lowPower: boolean = false): VoxelPoint[] {
  const points: VoxelPoint[] = [];
  // Volumetric scale: denser for a thick, solid anatomical heart
  const scaleMultiplier = lowPower ? 0.72 : 1.25;

  const addVoxel = (
    tx: number,
    ty: number,
    tz: number,
    opts: { delay?: number; size?: number; brightness?: number; isCore?: boolean; isVessel?: boolean; isArtery?: boolean } = {}
  ) => {
    const scatterDist = 180 + Math.random() * 260;
    const scatterTheta = Math.random() * Math.PI * 2;
    const scatterPhi = (Math.random() - 0.5) * Math.PI;

    // Thicker voxel particles (3.6px - 5.0px) for dense solid appearance
    const defaultSize = Math.random() > 0.75 ? 4.8 : 3.6;

    points.push({
      tx: tx * 3.4,
      ty: ty * 3.4,
      tz: tz * 3.4,
      ox: Math.cos(scatterTheta) * Math.cos(scatterPhi) * scatterDist,
      oy: Math.sin(scatterPhi) * scatterDist,
      oz: Math.sin(scatterTheta) * Math.cos(scatterPhi) * scatterDist,
      delay: opts.delay ?? (Math.random() * 0.45),
      size: opts.size ?? defaultSize,
      baseBrightness: opts.brightness ?? (0.55 + Math.random() * 0.45),
      isCore: opts.isCore,
      isVessel: opts.isVessel,
      isArtery: opts.isArtery,
    });
  };

  // 1. Thick Muscular Ventricles (Dense point cloud)
  const ventricleCount = Math.round(920 * scaleMultiplier);
  for (let i = 0; i < ventricleCount; i++) {
    const yRel = Math.random();
    const y = -3 + yRel * 31;

    const taper = Math.pow(1 - yRel * 0.90, 0.78);
    const radX = (13.5 + Math.sin(yRel * Math.PI) * 3.8) * taper;
    const radZ = (10.5 + Math.sin(yRel * Math.PI) * 2.8) * taper;

    const angle = Math.random() * Math.PI * 2;
    // Volumetric layering (from thick core to muscular surface)
    const radFactor = Math.pow(Math.random(), 0.42);

    const isLeftVentricle = Math.cos(angle) < -0.1;
    const lvThickening = isLeftVentricle ? 1.25 : 0.92;

    let x = Math.cos(angle) * radX * radFactor * lvThickening;
    let z = Math.sin(angle) * radZ * radFactor;

    x -= yRel * 7.8;
    z += yRel * 3.8;

    if (Math.abs(angle - Math.PI * 0.42) < 0.32) {
      x *= 0.86;
      z *= 0.86;
    }

    addVoxel(x, y, z, {
      isCore: yRel < 0.65 && radFactor < 0.55,
      brightness: isLeftVentricle ? 0.92 : 0.70,
    });
  }

  // 2. Right & Left Atrial Chambers
  const rightAtriumCount = Math.round(180 * scaleMultiplier);
  for (let i = 0; i < rightAtriumCount; i++) {
    const u = Math.random() * Math.PI;
    const v = Math.random() * Math.PI * 2;
    const rx = 7.2; const ry = 6.2; const rz = 6.8;
    const rFactor = Math.pow(Math.random(), 0.45);
    const x = 9.5 + rx * Math.sin(u) * Math.cos(v) * rFactor;
    const y = -10.5 + ry * Math.cos(u) * rFactor;
    const z = -3.5 + rz * Math.sin(u) * Math.sin(v) * rFactor;
    addVoxel(x, y, z, { brightness: 0.75 });
  }

  const leftAtriumCount = Math.round(160 * scaleMultiplier);
  for (let i = 0; i < leftAtriumCount; i++) {
    const u = Math.random() * Math.PI;
    const v = Math.random() * Math.PI * 2;
    const rx = 7.0; const ry = 5.8; const rz = 6.2;
    const rFactor = Math.pow(Math.random(), 0.45);
    const x = -7.5 + rx * Math.sin(u) * Math.cos(v) * rFactor;
    const y = -11.5 + ry * Math.cos(u) * rFactor;
    const z = -7.0 + rz * Math.sin(u) * Math.sin(v) * rFactor;
    addVoxel(x, y, z, { brightness: 0.72 });
  }

  // 3. Thick Aorta Arch & Branching Arteries (Arterial Red)
  const archSteps = Math.round(230 * scaleMultiplier);
  for (let i = 0; i < archSteps; i++) {
    const t = i / archSteps;
    const curveAngle = t * Math.PI * 1.08;
    const archRadiusX = 9.8;
    const archRadiusY = 12.5;

    const cx = 1.0 - Math.cos(curveAngle) * archRadiusX;
    const cy = -8.5 - Math.sin(curveAngle) * archRadiusY;
    const cz = 3.0 - t * 14.5;

    const tubeRadius = (4.4 - t * 0.8) * Math.sqrt(Math.random());
    const tubeTheta = Math.random() * Math.PI * 2;

    const x = cx + Math.cos(tubeTheta) * tubeRadius;
    const y = cy + Math.sin(tubeTheta) * tubeRadius * 0.7;
    const z = cz + Math.sin(tubeTheta) * tubeRadius;

    addVoxel(x, y, z, {
      isVessel: true,
      isArtery: true,
      brightness: 0.94,
      size: 4.2,
    });
  }

  // 3 Superior Aortic Branches
  const branches = [
    { x0: -3.5, y0: -20.5, z0: 1.5, dx: -2.2, dy: -9.5, dz: 1.0, count: Math.round(36 * scaleMultiplier) },
    { x0: 0.5, y0: -21.5, z0: -1.0, dx: 0.5, dy: -9.0, dz: 0.5, count: Math.round(28 * scaleMultiplier) },
    { x0: 4.5, y0: -20.5, z0: -3.5, dx: 2.5, dy: -8.5, dz: -0.5, count: Math.round(24 * scaleMultiplier) },
  ];

  branches.forEach((br) => {
    for (let i = 0; i < br.count; i++) {
      const frac = i / br.count;
      const pipeRad = (2.2 - frac * 0.4) * Math.sqrt(Math.random());
      const pipeAng = Math.random() * Math.PI * 2;
      const x = br.x0 + br.dx * frac + Math.cos(pipeAng) * pipeRad;
      const y = br.y0 + br.dy * frac + Math.sin(pipeAng) * pipeRad;
      const z = br.z0 + br.dz * frac + Math.sin(pipeAng) * pipeRad;
      addVoxel(x, y, z, { isVessel: true, isArtery: true, brightness: 0.96, size: 3.8 });
    }
  });

  // 4. Thick Pulmonary Trunk & Bifurcation (Venous Blue)
  const pulmonaryCount = Math.round(140 * scaleMultiplier);
  for (let i = 0; i < pulmonaryCount; i++) {
    const t = i / pulmonaryCount;
    const cx = -3.2 + t * 4.2;
    const cy = -5.0 - t * 12.5;
    const cz = 7.5 - t * 5.2;

    const tubeRad = 4.0 * Math.sqrt(Math.random());
    const tubeAng = Math.random() * Math.PI * 2;

    const x = cx + Math.cos(tubeAng) * tubeRad;
    const y = cy + Math.sin(tubeAng) * tubeRad;
    const z = cz + Math.sin(tubeAng) * tubeRad;

    addVoxel(x, y, z, { isVessel: true, isArtery: false, brightness: 0.88, size: 4.0 });
  }

  // Left & Right Pulmonary Branches
  const pulmonaryBranchCount = Math.round(75 * scaleMultiplier);
  for (let i = 0; i < pulmonaryBranchCount; i++) {
    const t = (Math.random() - 0.5) * 16;
    const x = 1.0 + t;
    const y = -17.5 + Math.abs(t) * 0.15;
    const z = 2.2 - Math.abs(t) * 0.45;
    const rad = 2.4 * Math.sqrt(Math.random());
    const ang = Math.random() * Math.PI * 2;
    addVoxel(x + Math.cos(ang) * rad, y + Math.sin(ang) * rad, z + Math.sin(ang) * rad, {
      isVessel: true,
      isArtery: false,
      brightness: 0.84,
      size: 3.6,
    });
  }

  // 5. Thick Superior Vena Cava (SVC)
  const svcCount = Math.round(95 * scaleMultiplier);
  for (let i = 0; i < svcCount; i++) {
    const t = i / svcCount;
    const cx = 13.5;
    const cy = -26.5 + t * 18.0;
    const cz = -3.5;

    const tubeRad = 3.6 * Math.sqrt(Math.random());
    const tubeAng = Math.random() * Math.PI * 2;

    const x = cx + Math.cos(tubeAng) * tubeRad;
    const y = cy + Math.sin(tubeAng) * tubeRad;
    const z = cz + Math.sin(tubeAng) * tubeRad;

    addVoxel(x, y, z, { isVessel: true, isArtery: false, brightness: 0.82, size: 3.8 });
  }

  // 6. Coronary Artery LAD (Arterial Red)
  const coronaryCount = Math.round(55 * scaleMultiplier);
  for (let i = 0; i < coronaryCount; i++) {
    const frac = i / coronaryCount;
    const y = -3.0 + frac * 28.0;
    const x = -frac * 7.2 + Math.sin(frac * 12) * 0.8;
    const z = 10.8 * (1 - frac * 0.82) + Math.cos(frac * 8) * 0.6;
    addVoxel(x, y, z, {
      isVessel: true,
      isArtery: true,
      brightness: 1.0,
      size: 4.2,
      delay: 0.35 + frac * 0.2,
    });
  }

  return points;
}

// Generate orbiting data rings (Light Theme subtle charcoal)
function generateOrbitRings(count: number = 75): RingParticle[] {
  const particles: RingParticle[] = [];
  for (let i = 0; i < count; i++) {
    particles.push({
      angle: Math.random() * Math.PI * 2,
      radius: 95 + Math.random() * 45,
      speed: (0.015 + Math.random() * 0.02) * (Math.random() > 0.5 ? 1 : -1),
      yOffset: (Math.random() - 0.5) * 35,
      tilt: 0.38 + (Math.random() - 0.5) * 0.15,
      size: Math.random() > 0.8 ? 2.6 : 1.6,
      alpha: 0.25 + Math.random() * 0.45,
    });
  }
  return particles;
}

export const DeviceInitialization: React.FC<DeviceInitializationProps> = ({
  backendOnline,
  bleConnected,
  telemetry,
  telemetryReady,
  deviceHealth,
  deviceName = 'Tarang pod',
  sessionLabel,
  lowPower = true,
  onComplete,
  onRetry,
  onBack,
}) => {
  const canvasRef = useRef<HTMLCanvasElement | null>(null);
  const targetStage = !backendOnline ? 0 : !bleConnected ? 1 : !telemetryReady ? 2 : 4;
  const [displayStage, setDisplayStage] = useState(0);
  const [finishing, setFinishing] = useState(false);

  const hrRef = useRef(telemetry.current_hr);
  useEffect(() => {
    hrRef.current = telemetry.current_hr;
  }, [telemetry.current_hr]);

  const progressRef = useRef(0);
  const progressRatio = Math.min(1, Math.max(0, displayStage / 4));
  useEffect(() => {
    progressRef.current = progressRatio;
  }, [progressRatio]);

  useEffect(() => {
    if (targetStage < displayStage) {
      setDisplayStage(targetStage);
      setFinishing(false);
      return;
    }
    if (displayStage >= targetStage) return;
    const delay = displayStage === 3 ? 1600 : 750;
    const timer = window.setTimeout(() => setDisplayStage((s) => Math.min(s + 1, targetStage)), delay);
    return () => window.clearTimeout(timer);
  }, [displayStage, targetStage]);

  useEffect(() => {
    if (displayStage !== 4 || targetStage !== 4) return;
    const finishTimer = window.setTimeout(() => setFinishing(true), 900);
    const completeTimer = window.setTimeout(onComplete, 1500);
    return () => {
      window.clearTimeout(finishTimer);
      window.clearTimeout(completeTimer);
    };
  }, [displayStage, targetStage, onComplete]);

  // Single-mount 3D Voxel Anatomical Heart Engine (Light Theme)
  useEffect(() => {
    const canvas = canvasRef.current;
    if (!canvas) return;
    const ctx = canvas.getContext('2d', { alpha: false });
    if (!ctx) return;

    const dpr = lowPower ? 1 : Math.min(window.devicePixelRatio || 1, 1.5);
    canvas.width = CANVAS_WIDTH * dpr;
    canvas.height = CANVAS_HEIGHT * dpr;
    if (dpr !== 1) {
      ctx.scale(dpr, dpr);
    }

    const prefersReducedMotion = window.matchMedia('(prefers-reduced-motion: reduce)').matches;

    const voxels = generateAnatomicalHeartVoxels(lowPower);
    const rings = generateOrbitRings(lowPower ? 45 : 80);

    const totalParticles = voxels.length;
    const projX = new Float32Array(totalParticles);
    const projY = new Float32Array(totalParticles);
    const projZ = new Float32Array(totalParticles);
    const projSize = new Float32Array(totalParticles);
    const projAlpha = new Float32Array(totalParticles);
    const sortIndices = new Uint16Array(totalParticles);
    for (let i = 0; i < totalParticles; i++) sortIndices[i] = i;

    let animationFrameId: number;
    let frameCount = 0;
    let yaw = -0.35;
    let pitch = 0.15;
    let beatPhase = 0;
    let smoothedProgress = prefersReducedMotion ? 1.0 : 0.05;

    const centerX = CANVAS_WIDTH / 2;
    const centerY = CANVAS_HEIGHT / 2 + 10;

    const render = () => {
      frameCount++;
      const targetProgress = progressRef.current;
      smoothedProgress += prefersReducedMotion
        ? (targetProgress - smoothedProgress) * 0.2
        : (targetProgress - smoothedProgress) * 0.06;

      if (!prefersReducedMotion) {
        yaw += 0.007;
      }
      const cosYaw = Math.cos(yaw);
      const sinYaw = Math.sin(yaw);
      const cosPitch = Math.cos(pitch);
      const sinPitch = Math.sin(pitch);

      const currentHr = hrRef.current || 75;
      const beatFrequency = (currentHr / 60) * 0.038;
      beatPhase = (beatPhase + beatFrequency) % 1;

      let cardiacScale = 1.0;
      let ventricleGlow = 0.0;
      if (smoothedProgress > 0.4 && !prefersReducedMotion) {
        const beatWeight = Math.min(1, (smoothedProgress - 0.4) / 0.6);
        if (beatPhase < SYSTOLE_DURATION) {
          const p = beatPhase / SYSTOLE_DURATION;
          const contraction = Math.sin(p * Math.PI);
          cardiacScale = 1.0 - contraction * SYSTOLE_CONTRACTION_MAX * beatWeight;
          ventricleGlow = contraction * beatWeight;
        } else if (beatPhase < SYSTOLE_DURATION + DIASTOLE_DURATION) {
          const p = (beatPhase - SYSTOLE_DURATION) / DIASTOLE_DURATION;
          const expansion = Math.sin(p * Math.PI);
          cardiacScale = 1.0 + expansion * DIASTOLE_EXPANSION_MAX * beatWeight;
          ventricleGlow = expansion * 0.3 * beatWeight;
        }
      }

      // 1. Clear background to Light Clinical Paper
      ctx.fillStyle = BACKGROUND_COLOR;
      ctx.fillRect(0, 0, CANVAS_WIDTH, CANVAS_HEIGHT);

      // 2. Batched Background Grid
      ctx.strokeStyle = GRID_STROKE;
      ctx.lineWidth = 1;
      ctx.beginPath();
      for (let x = 0; x < CANVAS_WIDTH; x += GRID_STEP) {
        ctx.moveTo(x, 0);
        ctx.lineTo(x, CANVAS_HEIGHT);
      }
      for (let y = 0; y < CANVAS_HEIGHT; y += GRID_STEP) {
        ctx.moveTo(0, y);
        ctx.lineTo(CANVAS_WIDTH, y);
      }
      ctx.stroke();

      // 3. Calculate 3D Voxel Coordinates
      let validCount = 0;
      for (let i = 0; i < totalParticles; i++) {
        const v = voxels[i];

        const voxelP = prefersReducedMotion
          ? 1.0
          : Math.min(1, Math.max(0, (smoothedProgress - v.delay) / (1 - v.delay + 0.001)));
        const ease = 1 - Math.pow(1 - voxelP, 3);

        let lx = v.ox + (v.tx - v.ox) * ease;
        let ly = v.oy + (v.ty - v.oy) * ease;
        let lz = v.oz + (v.tz - v.oz) * ease;

        if (ease > 0.8) {
          const vesselDamping = v.isVessel ? 0.3 : 1.0;
          const scale = 1.0 + (cardiacScale - 1.0) * vesselDamping;
          lx *= scale;
          ly *= scale;
          lz *= scale;
        }

        const x1 = lx * cosYaw + lz * sinYaw;
        const z1 = -lx * sinYaw + lz * cosYaw;
        const y2 = ly * cosPitch - z1 * sinPitch;
        const z2 = ly * sinPitch + z1 * cosPitch + CAMERA_DISTANCE;

        if (z2 <= CLIP_Z) continue;

        projX[i] = (x1 * FOCAL_LENGTH) / z2 + centerX;
        projY[i] = (y2 * FOCAL_LENGTH) / z2 + centerY;
        projZ[i] = z2;
        projSize[i] = Math.max(1.2, (v.size * FOCAL_LENGTH) / z2);

        const depthFactor = Math.max(0.2, Math.min(1.0, 1.0 - (z2 - 250) / 280));
        projAlpha[i] = Math.min(1.0, v.baseBrightness * depthFactor * (0.35 + ease * 0.65));
        sortIndices[validCount++] = i;
      }

      // 4. Render Orbiting Telemetry Rings (Light Theme charcoal particles)
      if (smoothedProgress > 0.2 && !prefersReducedMotion) {
        const ringAlphaMultiplier = Math.min(1, (smoothedProgress - 0.2) / 0.6);
        for (let i = 0; i < rings.length; i++) {
          const r = rings[i];
          r.angle += r.speed;

          const rx = Math.cos(r.angle) * r.radius;
          const rz = Math.sin(r.angle) * r.radius;
          const ry = r.yOffset + Math.sin(r.angle) * 16 * r.tilt;

          const rx1 = rx * cosYaw + rz * sinYaw;
          const rz1 = -rx * sinYaw + rz * cosYaw;
          const ry2 = ry * cosPitch - rz1 * sinPitch;
          const rz2 = ry * sinPitch + rz1 * cosPitch + CAMERA_DISTANCE;

          if (rz2 <= CLIP_Z) continue;

          const px = (rx1 * FOCAL_LENGTH) / rz2 + centerX;
          const py = (ry2 * FOCAL_LENGTH) / rz2 + centerY;
          const pSize = Math.max(1, (r.size * FOCAL_LENGTH) / rz2);

          const depthAlpha = Math.max(0.15, Math.min(1, 1 - (rz2 - 250) / 280));
          const finalAlpha = r.alpha * depthAlpha * ringAlphaMultiplier * 0.7;

          ctx.fillStyle = `rgba(24, 24, 22, ${finalAlpha})`;
          ctx.fillRect(px - pSize / 2, py - pSize / 2, pSize, pSize);
        }
      }

      // 5. Interleaved Depth Sort
      if (frameCount % 3 === 0) {
        sortIndices.subarray(0, validCount).sort((a, b) => projZ[b] - projZ[a]);
      }

      // 6. Draw 3D Voxels in Light Clinical Theme (Duotone Arterial Red & Venous Blue)
      for (let k = 0; k < validCount; k++) {
        const i = sortIndices[k];
        const px = projX[i];
        const py = projY[i];
        const sz = projSize[i];
        const alpha = projAlpha[i];
        const v = voxels[i];

        if (v.isArtery) {
          // -------------------------------------------------------------
          // ARTERIAL VESSELS (Aorta & LAD) - Warm Cardiac Rose/Red
          // -------------------------------------------------------------
          if (alpha > 0.75) {
            ctx.fillStyle = `rgba(225, 29, 72, ${alpha})`; // vivid rose-red
          } else if (alpha > 0.45) {
            ctx.fillStyle = `rgba(190, 24, 60, ${alpha * 0.9})`;
          } else {
            ctx.fillStyle = `rgba(136, 19, 55, ${alpha * 0.8})`;
          }
        } else if (v.isVessel) {
          // -------------------------------------------------------------
          // VENOUS / PULMONARY VESSELS (Pulmonary Trunk & SVC) - Cool Ocean Blue
          // -------------------------------------------------------------
          if (alpha > 0.75) {
            ctx.fillStyle = `rgba(0, 113, 227, ${alpha})`; // clinical blue
          } else if (alpha > 0.45) {
            ctx.fillStyle = `rgba(2, 90, 180, ${alpha * 0.9})`;
          } else {
            ctx.fillStyle = `rgba(30, 64, 175, ${alpha * 0.8})`;
          }
        } else {
          // -------------------------------------------------------------
          // MUSCULAR STRUCTURES (Ventricles, Atria) - High-Contrast Dark Slate/Ink
          // -------------------------------------------------------------
          if (v.isCore && ventricleGlow > 0.1) {
            // Systolic flash highlight
            ctx.fillStyle = `rgba(0, 131, 120, ${Math.min(1, 0.4 + ventricleGlow * 0.6)})`; // clinical teal glow
          } else if (alpha > 0.8) {
            ctx.fillStyle = '#181816'; // sharp ink black
          } else if (alpha > 0.5) {
            ctx.fillStyle = `rgba(60, 60, 65, ${alpha})`;
          } else {
            ctx.fillStyle = `rgba(140, 140, 148, ${alpha})`;
          }
        }

        ctx.fillRect(px - sz / 2, py - sz / 2, sz, sz);
      }

      // 7. HUD Telemetry Callouts (Light Theme Typography)
      ctx.font = '600 10px "JetBrains Mono", Consolas, monospace';
      ctx.fillStyle = 'rgba(24, 24, 22, 0.45)';
      ctx.fillText('CARDIAC VITALITY', centerX - 190, centerY - 85);

      ctx.font = '700 16px "JetBrains Mono", Consolas, monospace';
      ctx.fillStyle = '#181816';
      const liveHr = hrRef.current || (smoothedProgress > 0.5 ? 75 : '--');
      ctx.fillText(`${liveHr} BPM`, centerX - 190, centerY - 65);

      ctx.font = '600 10px "JetBrains Mono", Consolas, monospace';
      ctx.fillStyle = 'rgba(24, 24, 22, 0.45)';
      ctx.fillText('ASSEMBLY READINESS', centerX + 90, centerY - 85);

      ctx.font = '700 16px "JetBrains Mono", Consolas, monospace';
      ctx.fillStyle = '#008378'; // Tarang Clinical Green/Teal
      ctx.fillText(`${Math.round(smoothedProgress * 100)}%`, centerX + 90, centerY - 65);

      // Bottom subtext
      ctx.font = '500 9px "JetBrains Mono", Consolas, monospace';
      ctx.fillStyle = 'rgba(24, 24, 22, 0.40)';
      const subLabel = smoothedProgress < 0.3
        ? 'DISPERSED ANATOMICAL POINT CLOUD'
        : smoothedProgress < 0.75
        ? 'AORTIC & VENTRICULAR CAVITY ASSEMBLY'
        : 'ORGANIC SYSTOLE / DIASTOLE ACTIVE';
      ctx.fillText(`● ${subLabel}`, centerX - 190, centerY + 135);

      animationFrameId = requestAnimationFrame(render);
    };

    render();

    return () => {
      cancelAnimationFrame(animationFrameId);
    };
  }, [lowPower]);

  return (
    <main className={`min-h-screen bg-[var(--paper)] text-[var(--ink)] flex flex-col justify-between transition-all duration-700 ${finishing ? 'opacity-0 scale-[0.99]' : 'opacity-100'}`}>
      {/* Light Clinical Top Bar */}
      <header className="flex h-[58px] items-center justify-between border-b border-[var(--line)] px-6 bg-white/90 backdrop-blur-md">
        <div className="flex items-center gap-3">
          <img
            src="/logo_mark.svg"
            alt="Tarang"
            className="h-8.5 w-8.5 shrink-0 object-contain"
            onError={(e) => { (e.currentTarget as HTMLImageElement).src = '/tarang_logo.png'; }}
          />
          <div>
            <p className="text-xs font-bold tracking-wider uppercase text-[var(--ink)] leading-none">Tarang Clinical</p>
            <p className="text-[10px] font-mono text-[var(--muted)] mt-0.5">Pod Commissioning</p>
          </div>
          <div className="hidden sm:flex items-center pl-2.5 border-l border-[var(--line)]">
            <img
              src="/images/ocelleon-logo.png"
              alt="Ocelleon"
              className="h-4.5 w-auto object-contain opacity-80"
              onError={(e) => { (e.currentTarget as HTMLElement).style.display = 'none'; }}
            />
          </div>
        </div>
        <div className="flex items-center gap-3">
          <span className="hidden sm:inline-block font-mono text-[10px] text-[var(--muted)] border border-[var(--line)] bg-[var(--paper-2)] px-2.5 py-0.5 rounded">
            {sessionLabel || 'GATT ENCRYPTED LINK'}
          </span>
          <button onClick={onBack} className="discovery-pill-secondary !py-1 !px-3 !text-xs">
            <ArrowLeft size={13} /> Exit
          </button>
        </div>
      </header>

      {/* Main 3D Voxel Anatomical Heart Centerpiece */}
      <div className="flex-1 flex flex-col items-center justify-center p-4 max-sm:px-2">
        <div className="relative w-full max-w-4xl aspect-[16/10] sm:aspect-[16/9] max-h-[540px] rounded-xl border border-[var(--line)] bg-[#FAFAF9] overflow-hidden shadow-sm">
          <canvas
            ref={canvasRef}
            aria-hidden="true"
            className="w-full h-full block object-contain"
          />

          {/* Bottom Live Progress Bar in Green / Teal */}
          <div className="absolute bottom-0 left-0 right-0 h-1 bg-[var(--line-soft)]">
            <div
              className="h-full bg-[var(--clinical-teal)] transition-all duration-500 ease-out shadow-[0_0_8px_rgba(0,131,120,0.4)]"
              style={{ width: `${Math.round(progressRatio * 100)}%` }}
            />
          </div>
        </div>

        {/* 5 Milestone Tags in Green / Clinical Teal Theme */}
        <div className="w-full max-w-4xl mt-4 grid grid-cols-2 sm:grid-cols-3 lg:grid-cols-5 gap-2.5" role="status" aria-label="Commissioning progress">
          {STAGES.map((st, i) => {
            const isDone = i < displayStage || displayStage === 4;
            const isActive = i === displayStage && displayStage < 4;
            const Icon = st.icon;

            return (
              <div
                key={st.title}
                className={`p-3 rounded-lg border text-xs transition-all duration-300 ${
                  isDone
                    ? 'border-emerald-300 bg-emerald-50/80 text-emerald-950 shadow-xs'
                    : isActive
                    ? 'border-[var(--clinical-teal)] bg-[#0083780d] text-[var(--ink)] animate-pulse shadow-xs'
                    : 'border-[var(--line)] bg-white text-[var(--muted)] opacity-60'
                }`}
              >
                <div className="flex items-center gap-1.5 mb-1 font-mono text-[10px]">
                  {isDone ? (
                    <span className="flex h-4 w-4 shrink-0 items-center justify-center rounded-full bg-emerald-600 text-white font-bold text-[9px]">
                      <Check size={10} strokeWidth={3} />
                    </span>
                  ) : isActive ? (
                    <span className="flex h-4 w-4 shrink-0 items-center justify-center rounded-full bg-[var(--clinical-teal)] text-white font-mono text-[9px]">
                      <RefreshCw size={9} className="animate-spin" />
                    </span>
                  ) : (
                    <span className="flex h-4 w-4 shrink-0 items-center justify-center rounded-full border border-[var(--line)] text-[var(--muted)] font-mono text-[9px]">
                      {i + 1}
                    </span>
                  )}
                  <span className={`truncate uppercase tracking-wider font-semibold ${isDone ? 'text-emerald-800' : isActive ? 'text-[var(--clinical-teal)]' : 'text-[var(--muted)]'}`}>
                    {st.title}
                  </span>
                </div>
                <p className="text-[10px] text-[var(--ink-soft)] leading-tight line-clamp-2">{st.detail}</p>
              </div>
            );
          })}
        </div>
      </div>

      {/* Footer Status */}
      <footer className="h-10 border-t border-[var(--line)] px-6 flex items-center justify-between font-mono text-[10px] text-[var(--muted)] bg-white">
        <div className="flex items-center gap-2">
          <span className={`h-1.5 w-1.5 rounded-full ${bleConnected ? 'bg-emerald-600 shadow-[0_0_6px_rgba(5,150,105,0.6)]' : 'bg-amber-500'}`} />
          <span className="font-semibold text-[var(--ink)]">{bleConnected ? `LINKED: ${deviceName}` : 'AWAITING GATT BOND...'}</span>
        </div>
        <div>
          {displayStage >= 4 ? (
            <span className="text-emerald-700 font-bold">INITIALIZATION COMPLETE • ENTERING WORKSTATION</span>
          ) : (
            <span>AUTOMATIC PROGRESSION IN PROGRESS</span>
          )}
        </div>
      </footer>
    </main>
  );
};
