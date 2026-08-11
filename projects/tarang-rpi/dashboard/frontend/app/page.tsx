'use client';

import React, { useState, useEffect, useCallback } from 'react';
import { Sidebar } from '../src/components/Sidebar';
import { WorkstationView } from '../src/components/WorkstationView';
import { PatientSummarySidebar } from '../src/components/PatientSummarySidebar';
import { DiagnosticsView } from '../src/components/DiagnosticsView';
import { SettingsView } from '../src/components/SettingsView';
import {
  ClinicalTelemetryPacket,
  PatientInfo,
  TelemetryDiagnostics,
  SystemSettings,
} from '../src/types/telemetry';

// ── API Configuration ─────────────────────────────────────────────────────────
const API_BASE = process.env.NEXT_PUBLIC_API_URL ?? 'http://localhost:8000';
const WS_URL = process.env.NEXT_PUBLIC_WS_URL ?? 'ws://localhost:8000/ws/telemetry';
const PATIENT_MRN = '884219';

// ── Default fallback data (shown while loading / backend offline) ─────────────
const DEFAULT_TELEMETRY: ClinicalTelemetryPacket = {
  timestamp_ms: Date.now(),
  beat_class: 0,
  confidence: 255,
  rr_interval_ms: 810,
  rhythm_flags: 0x00,
  pac_burden_pct: 0,
  pvc_burden_pct: 0,
  current_hr: 0,
  sdnn_ms: 0,
  rmssd_ms: 0,
};

const DEFAULT_PATIENT: PatientInfo = {
  name: 'Loading...',
  age: 0,
  gender: 'Male',
  id: PATIENT_MRN,
  bed: '—',
  admitDate: '—',
  attendingPhysician: '—',
  bloodType: '—',
  allergies: [],
  medicalHistory: [],
};

const DEFAULT_DIAGNOSTICS: TelemetryDiagnostics = {
  bleConnected: false,
  deviceName: 'EFR32MG26 (Tarang SoC)',
  deviceMac: '—',
  firmwareVersion: 'v1.0.0-EFR32MG26',
  rssiDbm: -100,
  packetsReceived: 0,
  packetsDropped: 0,
  latencyMs: 0,
  batteryPct: 0,
  ecgDmaHealth: true,
  ppgI2cHealth: true,
  imuFifoHealth: true,
  lastSyncTimestamp: '—',
};

const DEFAULT_SETTINGS: SystemSettings = {
  hrLowThreshold: 60,
  hrHighThreshold: 100,
  spo2LowThreshold: 92,
  rrLowThreshold: 10,
  rrHighThreshold: 24,
  bleSyncIntervalMs: 1000,
  gridDensity: 'standard',
  audioAlertsEnabled: true,
  attendingDoctor: 'Dr. Aris',
};

// ── Telemetry packet from API (snake_case) → frontend type (camelCase) ────────
function mapApiTelemetry(raw: Record<string, unknown>): ClinicalTelemetryPacket {
  return {
    timestamp_ms: (raw.timestamp_ms as number) ?? Date.now(),
    beat_class: (raw.beat_class as 0 | 1 | 2) ?? 0,
    confidence: (raw.confidence as number) ?? 0,
    rr_interval_ms: (raw.rr_interval_ms as number) ?? 0,
    rhythm_flags: (raw.rhythm_flags as number) ?? 0,
    pac_burden_pct: (raw.pac_burden_pct as number) ?? 0,
    pvc_burden_pct: (raw.pvc_burden_pct as number) ?? 0,
    current_hr: (raw.current_hr as number) ?? 0,
    sdnn_ms: (raw.sdnn_ms as number) ?? 0,
    rmssd_ms: (raw.rmssd_ms as number) ?? 0,
  };
}

// ── Diagnostics from API → frontend type ─────────────────────────────────────
function mapApiDiagnostics(raw: Record<string, unknown>): TelemetryDiagnostics {
  return {
    bleConnected: (raw.bleConnected as boolean) ?? false,
    deviceName: (raw.deviceName as string) ?? 'EFR32MG26',
    deviceMac: (raw.deviceMac as string) ?? '—',
    firmwareVersion: (raw.firmwareVersion as string) ?? 'Unknown',
    rssiDbm: (raw.rssiDbm as number) ?? -100,
    packetsReceived: (raw.packetsReceived as number) ?? 0,
    packetsDropped: (raw.packetsDropped as number) ?? 0,
    latencyMs: (raw.latencyMs as number) ?? 0,
    batteryPct: (raw.batteryPct as number) ?? 0,
    ecgDmaHealth: (raw.ecgDmaHealth as boolean) ?? true,
    ppgI2cHealth: (raw.ppgI2cHealth as boolean) ?? true,
    imuFifoHealth: (raw.imuFifoHealth as boolean) ?? true,
    lastSyncTimestamp: (raw.lastSyncTimestamp as string) ?? new Date().toISOString(),
  };
}

// ── Patient from API → frontend type ─────────────────────────────────────────
function mapApiPatient(raw: Record<string, unknown>): PatientInfo {
  return {
    name: (raw.name as string) ?? 'Unknown',
    age: (raw.age as number) ?? 0,
    gender: (raw.gender as 'Male' | 'Female' | 'Other') ?? 'Male',
    id: (raw.mrn as string) ?? PATIENT_MRN,
    bed: (raw.bed as string) ?? '—',
    admitDate: (raw.admit_date as string) ?? '—',
    attendingPhysician: (raw.attending_physician as string) ?? '—',
    bloodType: (raw.blood_type as string) ?? '—',
    allergies: (raw.allergies as string[]) ?? [],
    medicalHistory: (raw.medical_history as string[]) ?? [],
  };
}

// ── Main App ──────────────────────────────────────────────────────────────────
export default function Home() {
  const [activeTab, setActiveTab] = useState<'workstation' | 'diagnostics' | 'settings'>('workstation');
  const [bleConnected, setBleConnected] = useState(false);
  const [backendOnline, setBackendOnline] = useState(false);

  const [telemetry, setTelemetry] = useState<ClinicalTelemetryPacket>(DEFAULT_TELEMETRY);
  const [patient, setPatient] = useState<PatientInfo>(DEFAULT_PATIENT);
  const [diagnostics, setDiagnostics] = useState<TelemetryDiagnostics>(DEFAULT_DIAGNOSTICS);
  const [settings, setSettings] = useState<SystemSettings>(DEFAULT_SETTINGS);

  // ── Fetch patient, settings, diagnostics on mount ──────────────────────────
  useEffect(() => {
    const fetchAll = async () => {
      try {
        // Patient
        const pRes = await fetch(`${API_BASE}/api/patients/${PATIENT_MRN}`);
        if (pRes.ok) {
          const pData = await pRes.json();
          setPatient(mapApiPatient(pData));
        }

        // Settings
        const sRes = await fetch(`${API_BASE}/api/settings`);
        if (sRes.ok) {
          const sData = await sRes.json();
          if (!sData.message) setSettings(sData as SystemSettings);
        }

        // Diagnostics (initial snapshot)
        const dRes = await fetch(`${API_BASE}/api/diagnostics/latest`);
        if (dRes.ok) {
          const dData = await dRes.json();
          if (!dData.message) {
            const mapped = mapApiDiagnostics(dData);
            setDiagnostics(mapped);
            setBleConnected(mapped.bleConnected);
          }
        }

        // Latest telemetry (seed canvas before WS connects)
        const tRes = await fetch(`${API_BASE}/api/telemetry/latest`);
        if (tRes.ok) {
          const tData = await tRes.json();
          if (!tData.message) setTelemetry(mapApiTelemetry(tData));
        }

        setBackendOnline(true);
      } catch {
        console.warn('[Tarang] Backend offline — running in offline mode.');
        setBackendOnline(false);
      }
    };

    fetchAll();

    // Poll diagnostics every 5 seconds
    const diagInterval = setInterval(async () => {
      try {
        const dRes = await fetch(`${API_BASE}/api/diagnostics/latest`);
        if (dRes.ok) {
          const dData = await dRes.json();
          if (!dData.message) {
            const mapped = mapApiDiagnostics(dData);
            setDiagnostics(mapped);
            setBleConnected(mapped.bleConnected);
          }
        }
      } catch {/* ignore */}
    }, 5000);

    return () => clearInterval(diagInterval);
  }, []);

  // ── WebSocket: live telemetry stream ──────────────────────────────────────
  useEffect(() => {
    if (!backendOnline) return;

    let ws: WebSocket | null = null;
    let reconnectTimer: ReturnType<typeof setTimeout>;

    const connect = () => {
      ws = new WebSocket(WS_URL);

      ws.onopen = () => {
        console.log('[Tarang WS] Connected');
      };

      ws.onmessage = (event) => {
        try {
          const raw = JSON.parse(event.data) as Record<string, unknown>;
          setTelemetry(mapApiTelemetry(raw));
          setBleConnected(true);
        } catch {
          console.warn('[Tarang WS] Invalid JSON received');
        }
      };

      ws.onerror = () => {
        console.warn('[Tarang WS] Error — will reconnect...');
      };

      ws.onclose = () => {
        console.warn('[Tarang WS] Disconnected. Reconnecting in 3s...');
        reconnectTimer = setTimeout(connect, 3000);
      };
    };

    connect();

    return () => {
      clearTimeout(reconnectTimer);
      ws?.close();
    };
  }, [backendOnline]);

  // ── Save settings to backend ──────────────────────────────────────────────
  const handleSaveSettings = useCallback(async (newSettings: SystemSettings) => {
    setSettings(newSettings);
    try {
      await fetch(`${API_BASE}/api/settings`, {
        method: 'PUT',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(newSettings),
      });
    } catch {
      console.warn('[Tarang] Could not persist settings to backend.');
    }
  }, []);

  return (
    <div className="min-h-screen bg-[var(--color-surface)]">
      {/* Fixed Navigation Sidebar */}
      <Sidebar activeTab={activeTab} setActiveTab={setActiveTab} bleConnected={bleConnected} />

      {/* Backend status badge (dev helper) */}
      {!backendOnline && (
        <div
          style={{ position: 'fixed', top: 12, right: 12, zIndex: 9999 }}
          className="text-[10px] px-2 py-1 rounded-full font-mono font-bold bg-amber-100 text-amber-800 border border-amber-300"
        >
          ⚡ Offline Mode — Start backend on :8000
        </div>
      )}

      {/* Main Content Area */}
      <main
        style={{
          paddingLeft: '272px',
          paddingRight: activeTab === 'workstation' ? '336px' : '16px',
          paddingTop: '20px',
          paddingBottom: '32px',
        }}
        className="transition-all duration-200"
      >
        {activeTab === 'workstation' && (
          <WorkstationView telemetry={telemetry} patient={patient} />
        )}

        {activeTab === 'diagnostics' && (
          <DiagnosticsView diagnostics={diagnostics} />
        )}

        {activeTab === 'settings' && (
          <SettingsView settings={settings} onSaveSettings={handleSaveSettings} />
        )}
      </main>

      {/* Right Sidebar (Patient Summary — Workstation View Only) */}
      {activeTab === 'workstation' && (
        <PatientSummarySidebar patient={patient} telemetry={telemetry} />
      )}
    </div>
  );
}
