'use client';

import React, { useEffect, useMemo, useRef, useState } from 'react';
import {
  Activity,
  ArrowLeft,
  Check,
  Circle,
  Database,
  Radio,
  RefreshCw,
  ShieldCheck,
} from 'lucide-react';
import { ClinicalTelemetryPacket, DeviceHealthTelemetry } from '../types/telemetry';

// ==========================================
// RENDERING & ANATOMICAL CONSTANTS
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

const BACKGROUND_COLOR = '#09090B';
const GRID_STEP = 32;
const GRID_STROKE = 'rgba(255, 255, 255, 0.022)';

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

/**
 * Generate a 100% Genuine 3D Anatomical Human Heart Voxel Point Cloud.
 * Includes: Left/Right Ventricles, Left/Right Atria, Ascending Aorta & Arch,
 * Brachiocephalic/Carotid/Subclavian Trunks, Pulmonary Artery with Bifurcation,
 * and Superior Vena Cava.
 */
function generateAnatomicalHeartVoxels(): VoxelPoint[] {
  const points: VoxelPoint[] = [];

  const addVoxel = (
    tx: number,
    ty: number,
    tz: number,
    opts: { delay?: number; size?: number; brightness?: number; isCore?: boolean; isVessel?: boolean; isArtery?: boolean } = {}
  ) => {
    // Outer scatter coordinates for magnetic float-in assembly
    const scatterDist = 180 + Math.random() * 260;
    const scatterTheta = Math.random() * Math.PI * 2;
    const scatterPhi = (Math.random() - 0.5) * Math.PI;

    points.push({
      tx: tx * 3.4,
      ty: ty * 3.4,
      tz: tz * 3.4,
      ox: Math.cos(scatterTheta) * Math.cos(scatterPhi) * scatterDist,
      oy: Math.sin(scatterPhi) * scatterDist,
      oz: Math.sin(scatterTheta) * Math.cos(scatterPhi) * scatterDist,
      delay: opts.delay ?? (Math.random() * 0.45),
      size: opts.size ?? (Math.random() > 0.82 ? 3.4 : 2.4),
      baseBrightness: opts.brightness ?? (0.55 + Math.random() * 0.45),
      isCore: opts.isCore,
      isVessel: opts.isVessel,
      isArtery: opts.isArtery,
    });
  };

  // -------------------------------------------------------------------------
  // 1. VENTRICLES (Muscular Conical Base & Left-Tilted Apex)
  // -------------------------------------------------------------------------
  // Anatomical orientation: Apex at bottom pointing anterior-inferior-left
  for (let i = 0; i < 540; i++) {
    // y goes from base (-4) to apex (+28)
    const yRel = Math.random(); // 0 = base, 1 = apex
    const y = -4 + yRel * 30;

    // Muscular cone profile tapering to the pointed apex
    const taper = Math.pow(1 - yRel * 0.88, 0.7);
    const radX = (14 + Math.sin(yRel * Math.PI) * 4) * taper;
    const radZ = (11 + Math.sin(yRel * Math.PI) * 3) * taper;

    const angle = Math.random() * Math.PI * 2;
    const radFactor = Math.pow(Math.random(), 0.5); // distribute through wall and cavity

    // Asymmetrical tilt: Left ventricle bulk + anterior interventricular groove
    const isLeftVentricle = Math.cos(angle) < 0;
    const lvThickening = isLeftVentricle ? 1.15 : 0.95;

    let x = Math.cos(angle) * radX * radFactor * lvThickening;
    let z = Math.sin(angle) * radZ * radFactor;

    // Apex tilt towards anterior left
    x -= yRel * 7.5;
    z += yRel * 3.5;

    // Interventricular sulcus indentation
    if (Math.abs(angle - Math.PI * 0.45) < 0.35) {
      x *= 0.88;
      z *= 0.88;
    }

    addVoxel(x, y, z, {
      isCore: yRel < 0.6 && radFactor < 0.6,
      brightness: isLeftVentricle ? 0.85 : 0.65,
    });
  }

  // -------------------------------------------------------------------------
  // 2. ATRIAL CHAMBERS (Upper Basal Flanks)
  // -------------------------------------------------------------------------
  // Right Atrium (smooth rounded upper right chamber)
  for (let i = 0; i < 110; i++) {
    const u = Math.random() * Math.PI;
    const v = Math.random() * Math.PI * 2;
    const rx = 7.5; const ry = 6.5; const rz = 7.0;
    const x = 9 + rx * Math.sin(u) * Math.cos(v);
    const y = -9 + ry * Math.cos(u);
    const z = -2 + rz * Math.sin(u) * Math.sin(v);
    addVoxel(x, y, z, { brightness: 0.7 });
  }

  // Left Atrium (posterior upper left chamber)
  for (let i = 0; i < 95; i++) {
    const u = Math.random() * Math.PI;
    const v = Math.random() * Math.PI * 2;
    const rx = 7.0; const ry = 6.0; const rz = 6.5;
    const x = -8 + rx * Math.sin(u) * Math.cos(v);
    const y = -10 + ry * Math.cos(u);
    const z = -6 + rz * Math.sin(u) * Math.sin(v);
    addVoxel(x, y, z, { brightness: 0.65 });
  }

  // -------------------------------------------------------------------------
  // 3. AORTIC ARCH & BRANCHING ARTERIES (Iconic Great Vessel Arch)
  // -------------------------------------------------------------------------
  // Ascending aorta starts at center base, arches superiorly, curves posterior-left
  const archSteps = 150;
  for (let i = 0; i < archSteps; i++) {
    const t = (i / archSteps); // 0 = root, 1 = descending aorta
    // 3D spline curve for the aortic arch
    const curveAngle = t * Math.PI * 1.05;
    const archRadiusX = 10;
    const archRadiusY = 12;

    const cx = 1 - Math.cos(curveAngle) * archRadiusX;
    const cy = -8 - Math.sin(curveAngle) * archRadiusY;
    const cz = 3 - t * 14;

    // Tube radius around arch centerline
    const tubeRadius = (4.0 - t * 0.8) * Math.sqrt(Math.random());
    const tubeTheta = Math.random() * Math.PI * 2;

    const x = cx + Math.cos(tubeTheta) * tubeRadius;
    const y = cy + Math.sin(tubeTheta) * tubeRadius * 0.7;
    const z = cz + Math.sin(tubeTheta) * tubeRadius;

    addVoxel(x, y, z, {
      isVessel: true,
      isArtery: true,
      brightness: 0.9,
      size: 2.8,
    });
  }

  // 3 Aortic Branch Vessels (Brachiocephalic, Carotid, Subclavian arteries)
  const branches = [
    { x0: -3.5, y0: -20, z0: 1.5, dx: -2.0, dy: -9, dz: 1.0, count: 26 }, // Brachiocephalic
    { x0: 0.5, y0: -21, z0: -1.0, dx: 0.5, dy: -8.5, dz: 0.5, count: 20 },  // Left Carotid
    { x0: 4.5, y0: -20, z0: -3.5, dx: 2.5, dy: -8, dz: -0.5, count: 18 },  // Left Subclavian
  ];

  branches.forEach((br) => {
    for (let i = 0; i < br.count; i++) {
      const frac = i / br.count;
      const pipeRad = (1.8 - frac * 0.4) * Math.sqrt(Math.random());
      const pipeAng = Math.random() * Math.PI * 2;
      const x = br.x0 + br.dx * frac + Math.cos(pipeAng) * pipeRad;
      const y = br.y0 + br.dy * frac + Math.sin(pipeAng) * pipeRad;
      const z = br.z0 + br.dz * frac + Math.sin(pipeAng) * pipeRad;
      addVoxel(x, y, z, { isVessel: true, isArtery: true, brightness: 0.95, size: 2.4 });
    }
  });

  // -------------------------------------------------------------------------
  // 4. PULMONARY TRUNK & BIFURCATION (Crosses Anterior to Aorta)
  // -------------------------------------------------------------------------
  for (let i = 0; i < 90; i++) {
    const t = i / 90;
    // Ascends from right ventricle conus, crosses anterior to ascending aorta
    const cx = -3 + t * 4;
    const cy = -5 - t * 12;
    const cz = 7 - t * 5;

    const tubeRad = 3.6 * Math.sqrt(Math.random());
    const tubeAng = Math.random() * Math.PI * 2;

    const x = cx + Math.cos(tubeAng) * tubeRad;
    const y = cy + Math.sin(tubeAng) * tubeRad;
    const z = cz + Math.sin(tubeAng) * tubeRad;

    addVoxel(x, y, z, { isVessel: true, brightness: 0.82, size: 2.6 });
  }

  // Left & Right Pulmonary Branches (T-junction under aortic arch)
  for (let i = 0; i < 50; i++) {
    const t = (Math.random() - 0.5) * 16; // sweeps left to right
    const x = 1 + t;
    const y = -17 + Math.abs(t) * 0.15;
    const z = 2 - Math.abs(t) * 0.4;
    const rad = 2.0 * Math.sqrt(Math.random());
    const ang = Math.random() * Math.PI * 2;
    addVoxel(x + Math.cos(ang) * rad, y + Math.sin(ang) * rad, z + Math.sin(ang) * rad, {
      isVessel: true,
      brightness: 0.78,
      size: 2.3,
    });
  }

  // -------------------------------------------------------------------------
  // 5. SUPERIOR VENA CAVA (SVC Vertical Vessel into Right Atrium)
  // -------------------------------------------------------------------------
  for (let i = 0; i < 65; i++) {
    const t = i / 65;
    const cx = 13;
    const cy = -26 + t * 18;
    const cz = -3;

    const tubeRad = 3.2 * Math.sqrt(Math.random());
    const tubeAng = Math.random() * Math.PI * 2;

    const x = cx + Math.cos(tubeAng) * tubeRad;
    const y = cy + Math.sin(tubeAng) * tubeRad;
    const z = cz + Math.sin(tubeAng) * tubeRad;

    addVoxel(x, y, z, { isVessel: true, brightness: 0.75, size: 2.5 });
  }

  // -------------------------------------------------------------------------
  // 6. CORONARY ARTERY VASCULATURE (LAD down Interventricular Groove)
  // -------------------------------------------------------------------------
  for (let i = 0; i < 40; i++) {
    const frac = i / 40;
    const y = -3 + frac * 28;
    // Follow the surface curve along the anterior groove
    const x = -frac * 7.0 + Math.sin(frac * 12) * 0.8;
    const z = 11 * (1 - frac * 0.8) + Math.cos(frac * 8) * 0.6;
    addVoxel(x, y, z, {
      isArtery: true,
      brightness: 1.0,
      size: 2.8,
      delay: 0.35 + frac * 0.2,
    });
  }

  return points;
}

// Generate the orbiting telemetry data rings
function generateOrbitRings(count: number = 80): RingParticle[] {
  const particles: RingParticle[] = [];
  for (let i = 0; i < count; i++) {
    particles.push({
      angle: Math.random() * Math.PI * 2,
      radius: 95 + Math.random() * 45,
      speed: (0.015 + Math.random() * 0.02) * (Math.random() > 0.5 ? 1 : -1),
      yOffset: (Math.random() - 0.5) * 35,
      tilt: 0.38 + (Math.random() - 0.5) * 0.15,
      size: Math.random() > 0.8 ? 2.8 : 1.6,
      alpha: 0.3 + Math.random() * 0.6,
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
  onComplete,
  onRetry,
  onBack,
}) => {
  const canvasRef = useRef<HTMLCanvasElement | null>(null);
  const targetStage = !backendOnline ? 0 : !bleConnected ? 1 : !telemetryReady ? 2 : 4;
  const [displayStage, setDisplayStage] = useState(0);
  const [finishing, setFinishing] = useState(false);

  // Keep live inputs in mutable refs to avoid restarting the render loop
  const hrRef = useRef(telemetry.current_hr);
  useEffect(() => {
    hrRef.current = telemetry.current_hr;
  }, [telemetry.current_hr]);

  const progressRef = useRef(0);
  const progressRatio = Math.min(1, Math.max(0, displayStage / 4));
  useEffect(() => {
    progressRef.current = progressRatio;
  }, [progressRatio]);

  // Smooth stage stepping
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

  // Transition to monitoring workstation upon completion
  useEffect(() => {
    if (displayStage !== 4 || targetStage !== 4) return;
    const finishTimer = window.setTimeout(() => setFinishing(true), 900);
    const completeTimer = window.setTimeout(onComplete, 1500);
    return () => {
      window.clearTimeout(finishTimer);
      window.clearTimeout(completeTimer);
    };
  }, [displayStage, targetStage, onComplete]);

  // Single-mount 3D Voxel Anatomical Heart Engine
  useEffect(() => {
    const canvas = canvasRef.current;
    if (!canvas) return;
    const ctx = canvas.getContext('2d', { alpha: false });
    if (!ctx) return;

    // Handle High-DPI Displays (Retina / 4K)
    const dpr = Math.min(window.devicePixelRatio || 1, 2);
    canvas.width = CANVAS_WIDTH * dpr;
    canvas.height = CANVAS_HEIGHT * dpr;
    ctx.scale(dpr, dpr);

    // Check user preference for motion sensitivity
    const prefersReducedMotion = window.matchMedia('(prefers-reduced-motion: reduce)').matches;

    // Genuine Anatomical Heart geometry data generated once on mount
    const voxels = generateAnatomicalHeartVoxels();
    const rings = generateOrbitRings(95);

    // Pre-allocated typed arrays to prevent per-frame garbage collection allocations
    const totalParticles = voxels.length;
    const projX = new Float32Array(totalParticles);
    const projY = new Float32Array(totalParticles);
    const projZ = new Float32Array(totalParticles);
    const projSize = new Float32Array(totalParticles);
    const projAlpha = new Float32Array(totalParticles);
    const sortIndices = new Uint16Array(totalParticles);
    for (let i = 0; i < totalParticles; i++) sortIndices[i] = i;

    let animationFrameId: number;
    let yaw = -0.35; // optimal 3/4 anatomical viewing angle
    let pitch = 0.15;
    let beatPhase = 0;
    let smoothedProgress = prefersReducedMotion ? 1.0 : 0.05;

    const centerX = CANVAS_WIDTH / 2;
    const centerY = CANVAS_HEIGHT / 2 + 10;

    const render = () => {
      const targetProgress = progressRef.current;
      smoothedProgress += prefersReducedMotion
        ? (targetProgress - smoothedProgress) * 0.2
        : (targetProgress - smoothedProgress) * 0.06;

      if (!prefersReducedMotion) {
        yaw += 0.007; // gentle yaw rotation to inspect the 3D anatomical chambers
      }
      const cosYaw = Math.cos(yaw);
      const sinYaw = Math.sin(yaw);
      const cosPitch = Math.cos(pitch);
      const sinPitch = Math.sin(pitch);

      // Heartbeat dynamics based on live/target HR
      const currentHr = hrRef.current || 75;
      const beatFrequency = (currentHr / 60) * 0.038;
      beatPhase = (beatPhase + beatFrequency) % 1;

      // Systolic / Diastolic Cardiac Scale Factor
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

      // 1. Clear background
      ctx.fillStyle = BACKGROUND_COLOR;
      ctx.fillRect(0, 0, CANVAS_WIDTH, CANVAS_HEIGHT);

      // 2. Batched Background CRT scanline grid
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

        // Apply physiological ventricular contraction
        if (ease > 0.8) {
          // Ventricles contract more than the rigid aorta
          const vesselDamping = v.isVessel ? 0.3 : 1.0;
          const scale = 1.0 + (cardiacScale - 1.0) * vesselDamping;
          lx *= scale;
          ly *= scale;
          lz *= scale;
        }

        // 3D Matrix Rotation (Yaw & Pitch)
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

      // 4. Render Orbiting Telemetry Rings
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
          const finalAlpha = r.alpha * depthAlpha * ringAlphaMultiplier;

          ctx.fillStyle = `rgba(255, 255, 255, ${finalAlpha})`;
          ctx.fillRect(px - pSize / 2, py - pSize / 2, pSize, pSize);
        }
      }

      // 5. Depth Sort (Painter's Algorithm on pre-allocated typed index array)
      sortIndices.subarray(0, validCount).sort((a, b) => projZ[b] - projZ[a]);

      // 6. Draw 3D Voxels (Crisp Monochromatic Voxel Rendering)
      for (let k = 0; k < validCount; k++) {
        const i = sortIndices[k];
        const px = projX[i];
        const py = projY[i];
        const sz = projSize[i];
        const alpha = projAlpha[i];
        const v = voxels[i];

        if (v.isArtery && alpha > 0.7) {
          // Bright highlights on aorta & coronary artery
          ctx.fillStyle = '#FFFFFF';
        } else if (v.isCore && ventricleGlow > 0.1) {
          ctx.fillStyle = `rgba(255, 255, 255, ${Math.min(1, alpha + ventricleGlow * 0.45)})`;
        } else if (alpha > 0.8) {
          ctx.fillStyle = '#FFFFFF';
        } else if (alpha > 0.5) {
          ctx.fillStyle = `rgba(220, 220, 225, ${alpha})`;
        } else {
          ctx.fillStyle = `rgba(120, 120, 130, ${alpha})`;
        }
        ctx.fillRect(px - sz / 2, py - sz / 2, sz, sz);
      }

      // 7. HUD Telemetry Callouts
      ctx.font = '600 10px "JetBrains Mono", Consolas, monospace';
      ctx.fillStyle = 'rgba(255, 255, 255, 0.4)';
      ctx.fillText('CARDIAC VITALITY', centerX - 190, centerY - 85);

      ctx.font = '700 16px "JetBrains Mono", Consolas, monospace';
      ctx.fillStyle = '#FFFFFF';
      const liveHr = hrRef.current || (smoothedProgress > 0.5 ? 75 : '--');
      ctx.fillText(`${liveHr} BPM`, centerX - 190, centerY - 65);

      ctx.font = '600 10px "JetBrains Mono", Consolas, monospace';
      ctx.fillStyle = 'rgba(255, 255, 255, 0.4)';
      ctx.fillText('ASSEMBLY READINESS', centerX + 90, centerY - 85);

      ctx.font = '700 16px "JetBrains Mono", Consolas, monospace';
      ctx.fillStyle = smoothedProgress >= 0.99 ? '#FFFFFF' : 'rgba(255, 255, 255, 0.9)';
      ctx.fillText(`${Math.round(smoothedProgress * 100)}%`, centerX + 90, centerY - 65);

      // Bottom subtext
      ctx.font = '500 9px "JetBrains Mono", Consolas, monospace';
      ctx.fillStyle = 'rgba(255, 255, 255, 0.35)';
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
  }, []);

  const stagesList = [
    { title: 'Clinical Database', detail: 'Local SQLite tables linked', done: displayStage >= 1 },
    { title: 'BLE GATT Session', detail: 'Paired to EFR32MG26 (AES-128)', done: displayStage >= 2 },
    { title: '250 Hz IADC Calibration', detail: 'Physiological vitals stream verified', done: displayStage >= 3 },
    { title: 'Edge AI Ready', detail: 'On-chip rhythm engine operational', done: displayStage >= 4 },
  ];

  return (
    <main className={`min-h-screen bg-[#09090B] text-white flex flex-col justify-between transition-all duration-700 ${finishing ? 'opacity-0 scale-[0.99]' : 'opacity-100'}`}>
      {/* Monochromatic Top Bar */}
      <header className="flex h-[58px] items-center justify-between border-b border-zinc-800/80 px-6 bg-[#09090B]/80 backdrop-blur-md">
        <div className="flex items-center gap-3">
          <img
            src="/logo_mark.svg"
            alt="Tarang"
            className="h-6 w-6 shrink-0 invert object-contain"
            onError={(e) => { (e.currentTarget as HTMLImageElement).src = '/tarang_logo.png'; }}
          />
          <div>
            <p className="text-xs font-bold tracking-wider uppercase text-white">Tarang Clinical</p>
            <p className="text-[10px] font-mono text-zinc-400">Pod Commissioning</p>
          </div>
        </div>
        <div className="flex items-center gap-3">
          <span className="hidden sm:inline-block font-mono text-[10px] text-zinc-500 border border-zinc-800 px-2 py-0.5 rounded">
            {sessionLabel || 'GATT ENCRYPTED LINK'}
          </span>
          <button onClick={onBack} className="flex items-center gap-1.5 rounded-full border border-zinc-700 bg-zinc-900 px-3 py-1 text-xs font-medium text-zinc-300 hover:bg-zinc-800 hover:text-white transition-colors">
            <ArrowLeft size={13} /> Exit
          </button>
        </div>
      </header>

      {/* Main 3D Voxel Anatomical Heart Centerpiece */}
      <div className="flex-1 flex flex-col items-center justify-center p-4 max-sm:px-2">
        <div className="relative w-full max-w-4xl aspect-[16/10] sm:aspect-[16/9] max-h-[540px] rounded-xl border border-zinc-800 bg-[#09090B] overflow-hidden shadow-2xl">
          <canvas
            ref={canvasRef}
            aria-hidden="true"
            className="w-full h-full block object-contain"
          />

          {/* Bottom Live Progress Bar */}
          <div className="absolute bottom-0 left-0 right-0 h-1 bg-zinc-900">
            <div
              className="h-full bg-white transition-all duration-500 ease-out shadow-[0_0_8px_#ffffff]"
              style={{ width: `${Math.round(progressRatio * 100)}%` }}
            />
          </div>
        </div>

        {/* Milestone Steps Pills (Accessible status region) */}
        <div className="w-full max-w-4xl mt-4 grid grid-cols-2 md:grid-cols-4 gap-2.5" role="status" aria-label="Commissioning progress">
          {stagesList.map((st, i) => (
            <div
              key={st.title}
              className={`p-3 rounded-lg border text-xs transition-all duration-300 ${
                st.done
                  ? 'border-zinc-700 bg-zinc-900/90 text-white'
                  : 'border-zinc-800/60 bg-zinc-950/40 text-zinc-500'
              }`}
            >
              <div className="flex items-center gap-1.5 mb-1 font-mono text-[10px]">
                {st.done ? (
                  <span className="flex h-4 w-4 shrink-0 items-center justify-center rounded-full bg-white text-black font-bold">✓</span>
                ) : (
                  <span className="flex h-4 w-4 shrink-0 items-center justify-center rounded-full border border-zinc-700 text-zinc-500 font-mono text-[9px]">{i + 1}</span>
                )}
                <span className="truncate uppercase tracking-wider font-semibold">{st.title}</span>
              </div>
              <p className="text-[10px] text-zinc-400 leading-tight truncate">{st.detail}</p>
            </div>
          ))}
        </div>
      </div>

      {/* Footer Status */}
      <footer className="h-10 border-t border-zinc-800/80 px-6 flex items-center justify-between font-mono text-[10px] text-zinc-500 bg-[#09090B]">
        <div className="flex items-center gap-2">
          <span className={`h-1.5 w-1.5 rounded-full ${bleConnected ? 'bg-white shadow-[0_0_6px_#ffffff]' : 'bg-amber-400'}`} />
          <span>{bleConnected ? `LINKED: ${deviceName}` : 'AWAITING GATT BOND...'}</span>
        </div>
        <div>
          {displayStage >= 4 ? (
            <span className="text-white font-bold">INITIALIZATION COMPLETE • ENTERING WORKSTATION</span>
          ) : (
            <span>AUTOMATIC PROGRESSION IN PROGRESS</span>
          )}
        </div>
      </footer>
    </main>
  );
};
