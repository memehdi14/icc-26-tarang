'use client';

import React, { useState, useEffect, useCallback } from 'react';
import { Sidebar } from '../src/components/Sidebar';
import { WorkstationView } from '../src/components/WorkstationView';
import { PatientSummarySidebar } from '../src/components/PatientSummarySidebar';
import { DiagnosticsView } from '../src/components/DiagnosticsView';
import { SettingsView } from '../src/components/SettingsView';
import { DeviceInitialization } from '../src/components/DeviceInitialization';
import {
  ClinicalTelemetryPacket,
  DeviceHealthTelemetry,
  PatientInfo,
  TelemetryDiagnostics,
  SystemSettings,
} from '../src/types/telemetry';

// ── API Configuration ─────────────────────────────────────────────────────────
function getApiBase(): string {
  if (typeof window !== 'undefined') {
    const host = window.location.hostname;
    const envUrl = process.env.NEXT_PUBLIC_API_URL;
    if (envUrl && !envUrl.includes('localhost')) {
      return envUrl;
    }
    return `${window.location.protocol}//${host}:8000`;
  }
  return process.env.NEXT_PUBLIC_API_URL ?? 'http://localhost:8000';
}

function getWsUrl(): string {
  if (typeof window !== 'undefined') {
    const host = window.location.hostname;
    const envWs = process.env.NEXT_PUBLIC_WS_URL;
    if (envWs && !envWs.includes('localhost')) {
      return envWs;
    }
    const wsProto = window.location.protocol === 'https:' ? 'wss:' : 'ws:';
    return `${wsProto}//${host}:8000/ws/telemetry`;
  }
  return process.env.NEXT_PUBLIC_WS_URL ?? 'ws://localhost:8000/ws/telemetry';
}

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

const DEFAULT_DEVICE_HEALTH: DeviceHealthTelemetry = {
  uptimeS: 0,
  ecgLeadOff: false,
  ecgSqi: 255,
  ppgFingerPresent: false,
  imuOk: false,
  i2cFailureCount: 0,
  dspOverflowCount: 0,
  ecgOverrunCount: 0,
  bleRssi: null,
  batteryPct: null,
  fwVersion: '1.0.0',
  sessionId: null,
};

// ── Telemetry packet from API (snake_case) → frontend type (camelCase) ────────
function mapApiTelemetry(raw: Record<string, unknown>): ClinicalTelemetryPacket {
  return {
    timestamp_ms: (raw.timestamp_ms as number) ?? Date.now(),
    beat_class: (raw.beat_class as 0 | 1 | 2 | 3) ?? 0,
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

function mapApiDeviceHealth(raw: Record<string, unknown>): DeviceHealthTelemetry {
  return {
    uptimeS: (raw.uptimeS as number) ?? 0,
    ecgLeadOff: (raw.ecgLeadOff as boolean) ?? false,
    ecgSqi: (raw.ecgSqi as number) ?? 255,
    ppgFingerPresent: (raw.ppgFingerPresent as boolean) ?? false,
    imuOk: (raw.imuOk as boolean) ?? false,
    i2cFailureCount: (raw.i2cFailureCount as number) ?? 0,
    dspOverflowCount: (raw.dspOverflowCount as number) ?? 0,
    ecgOverrunCount: (raw.ecgOverrunCount as number) ?? 0,
    bleRssi: (raw.bleRssi as number | null) ?? null,
    batteryPct: (raw.batteryPct as number | null) ?? null,
    fwVersion: (raw.fwVersion as string) ?? '1.0.0',
    sessionId: (raw.sessionId as string | null) ?? null,
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
  const [isDeviceReady, setIsDeviceReady] = useState(false);

  const [telemetry, setTelemetry] = useState<ClinicalTelemetryPacket>(DEFAULT_TELEMETRY);
  const [eventLog, setEventLog] = useState<ClinicalTelemetryPacket[]>([]);
  const [patient, setPatient] = useState<PatientInfo>(DEFAULT_PATIENT);
  const [diagnostics, setDiagnostics] = useState<TelemetryDiagnostics>(DEFAULT_DIAGNOSTICS);
  const [deviceHealth, setDeviceHealth] = useState<DeviceHealthTelemetry>(DEFAULT_DEVICE_HEALTH);
  const [settings, setSettings] = useState<SystemSettings>(DEFAULT_SETTINGS);

  // ── Fetch patient, settings, diagnostics on mount ──────────────────────────
  useEffect(() => {
    let pollInterval: ReturnType<typeof setInterval>;

    const fetchAll = async () => {
      const apiBase = getApiBase();
      try {
        // Patient
        const pRes = await fetch(`${apiBase}/api/patients/${PATIENT_MRN}`);
        if (pRes.ok) {
          const pData = await pRes.json();
          setPatient(mapApiPatient(pData));
        }

        // Settings
        const sRes = await fetch(`${apiBase}/api/settings`);
        if (sRes.ok) {
          const sData = await sRes.json();
          if (!sData.message) setSettings(sData as SystemSettings);
        }

        // Diagnostics (initial snapshot)
        const dRes = await fetch(`${apiBase}/api/diagnostics/latest`);
        if (dRes.ok) {
          const dData = await dRes.json();
          if (!dData.message) {
            const mapped = mapApiDiagnostics(dData);
            setDiagnostics(mapped);
            setBleConnected(mapped.bleConnected);
          }
        }

        // Latest telemetry (seed canvas before WS connects)
        const tRes = await fetch(`${apiBase}/api/telemetry/latest`);
        if (tRes.ok) {
          const tData = await tRes.json();
          if (!tData.message) setTelemetry(mapApiTelemetry(tData));
        }

        const healthRes = await fetch(`${apiBase}/api/health/device`);
        if (healthRes.ok) {
          setDeviceHealth(mapApiDeviceHealth(await healthRes.json()));
        }

        // History events
        const hRes = await fetch(`${apiBase}/api/telemetry/history?minutes=5`);
        if (hRes.ok) {
          const hData = await hRes.json();
          if (Array.isArray(hData)) {
            setEventLog(hData.map((e: Record<string, unknown>) => mapApiTelemetry(e)));
          }
        }

        setBackendOnline(true);
      } catch {
        console.warn('[Tarang] Backend offline — running in offline mode.');
        setBackendOnline(false);
      }
    };

    fetchAll();

    // Poll diagnostics and check backend status every 3 seconds
    pollInterval = setInterval(async () => {
      const apiBase = getApiBase();
      try {
        const dRes = await fetch(`${apiBase}/api/diagnostics/latest`);
        if (dRes.ok) {
          const dData = await dRes.json();
          if (!dData.message) {
            const mapped = mapApiDiagnostics(dData);
            setDiagnostics(mapped);
            setBleConnected(mapped.bleConnected);
          }
          setBackendOnline(true);
        }
      } catch {
        setBackendOnline(false);
      }
    }, 3000);

    return () => clearInterval(pollInterval);
  }, []);

  // ── WebSocket: live telemetry stream ──────────────────────────────────────
  useEffect(() => {
    let ws: WebSocket | null = null;
    let reconnectTimer: ReturnType<typeof setTimeout>;

    const connect = () => {
      const wsUrl = getWsUrl();
      ws = new WebSocket(wsUrl);

      ws.onopen = () => {
        console.log('[Tarang WS] Connected to:', wsUrl);
        setBackendOnline(true);
      };

      ws.onmessage = (event) => {
        try {
          const raw = JSON.parse(event.data) as Record<string, unknown>;
          if (raw.type === 'diagnostics' && raw.data) {
            const mappedDiag = mapApiDiagnostics(raw.data as Record<string, unknown>);
            setDiagnostics(mappedDiag);
            setBleConnected(mappedDiag.bleConnected);
          } else if (raw.type === 'device_health' && raw.data) {
            setDeviceHealth(mapApiDeviceHealth(raw.data as Record<string, unknown>));
          } else {
            const rawPacket = (raw.data && raw.type === 'telemetry') ? (raw.data as Record<string, unknown>) : raw;
            const mappedPacket = mapApiTelemetry(rawPacket);
            setTelemetry(mappedPacket);
            setEventLog(prev => [mappedPacket, ...prev.slice(0, 49)]);
            setBleConnected(true);
          }
          setBackendOnline(true);
        } catch {
          console.warn('[Tarang WS] Invalid JSON received');
        }
      };

      ws.onerror = () => {
        console.warn('[Tarang WS] Error connecting to:', wsUrl);
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
  }, []);

  // ── Save settings to backend ──────────────────────────────────────────────
  const handleSaveSettings = useCallback(async (newSettings: SystemSettings) => {
    setSettings(newSettings);
    const apiBase = getApiBase();
    try {
      await fetch(`${apiBase}/api/settings`, {
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
          paddingRight: activeTab === 'workstation' && isDeviceReady ? '336px' : '16px',
          paddingTop: '20px',
          paddingBottom: '32px',
        }}
        className="transition-all duration-200"
      >
        {activeTab === 'workstation' && !isDeviceReady && (
          <DeviceInitialization
            bleConnected={bleConnected}
            telemetry={telemetry}
            deviceHealth={deviceHealth}
            onComplete={() => setIsDeviceReady(true)}
            onRetry={() => {
              window.location.reload();
            }}
          />
        )}

        {activeTab === 'workstation' && isDeviceReady && (
          <WorkstationView telemetry={telemetry} patient={patient} eventLog={eventLog} />
        )}

        {activeTab === 'diagnostics' && (
          <DiagnosticsView diagnostics={diagnostics} deviceHealth={deviceHealth} />
        )}

        {activeTab === 'settings' && (
          <SettingsView settings={settings} onSaveSettings={handleSaveSettings} />
        )}
      </main>

      {/* Right Sidebar (Patient Summary — Workstation View Only when Ready) */}
      {activeTab === 'workstation' && isDeviceReady && (
        <PatientSummarySidebar patient={patient} telemetry={telemetry} />
      )}
    </div>
  );
}
