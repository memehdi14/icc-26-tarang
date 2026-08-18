'use client';

import React, { useState, useEffect, useCallback } from 'react';
import { Sidebar } from '../src/components/Sidebar';
import { WorkstationView } from '../src/components/WorkstationView';
import { PatientSummarySidebar } from '../src/components/PatientSummarySidebar';
import { DiagnosticsView } from '../src/components/DiagnosticsView';
import { SettingsView } from '../src/components/SettingsView';
import { DeviceInitialization } from '../src/components/DeviceInitialization';
import {
  VitalsSample,
  Analytics5Min,
  ClinicalEvent,
  EcgSnippet,
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

const DEFAULT_PATIENT: PatientInfo = {
  name: 'John Doe',
  age: 58,
  gender: 'Male',
  id: PATIENT_MRN,
  bed: 'ICU-04',
  admitDate: '2026-08-09',
  attendingPhysician: 'Dr. Aris',
  bloodType: 'O+',
  allergies: ['Penicillin', 'Latex Adhesives'],
  medicalHistory: [
    'Hypertension (Diagnosed 2018)',
    'Coronary Artery Stent - LAD (2021)',
    'Type 2 Diabetes Mellitus',
  ],
};

const DEFAULT_DIAGNOSTICS: TelemetryDiagnostics = {
  bleConnected: true,
  deviceName: 'EFR32MG26 (Tarang SoC)',
  deviceMac: '70:B3:D5:70:9A:C4',
  firmwareVersion: 'v1.0.0-ModeA',
  rssiDbm: -58,
  packetsReceived: 0,
  packetsDropped: 0,
  latencyMs: 0,
  batteryPct: 94,
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
  bleSyncIntervalMs: 2000,
  gridDensity: 'standard',
  audioAlertsEnabled: true,
  attendingDoctor: 'Dr. Aris',
};

export default function Page() {
  const [activeTab, setActiveTab] = useState<'workstation' | 'diagnostics' | 'settings'>('workstation');
  const [isDeviceReady, setIsDeviceReady] = useState<boolean>(true);
  const [bleConnected, setBleConnected] = useState<boolean>(true);
  const [backendOnline, setBackendOnline] = useState<boolean>(true);

  // ── Mode A State ────────────────────────────────────────────────────────────
  const [vitals, setVitals] = useState<VitalsSample>({
    heartRateBpm: 75,
    spo2Pct: 98,
    deviceId: 'tarang-efr32-demo',
    ts: new Date().toISOString(),
  });

  const [analytics, setAnalytics] = useState<Analytics5Min>({
    pvcBurdenPct: 0.4,
    pacBurdenPct: 1.2,
    sdnn: 44,
    rmssd: 38,
    prr50: 8.5,
    aiDutyCyclePct: 1.5,
    em2SleepPct: 92.0,
    deviceId: 'tarang-efr32-demo',
    ts: new Date().toISOString(),
  });

  const [latestEvent, setLatestEvent] = useState<ClinicalEvent | null>(null);
  const [activeSnippet, setActiveSnippet] = useState<EcgSnippet | null>(null);
  const [glitchTicker, setGlitchTicker] = useState<ClinicalEvent[]>([]);

  const [patient, setPatient] = useState<PatientInfo>(DEFAULT_PATIENT);
  const [diagnostics, setDiagnostics] = useState<TelemetryDiagnostics>(DEFAULT_DIAGNOSTICS);
  const [deviceHealth, setDeviceHealth] = useState<DeviceHealthTelemetry | undefined>(undefined);
  const [settings, setSettings] = useState<SystemSettings>(DEFAULT_SETTINGS);

  // Initial Data Fetching
  useEffect(() => {
    const apiBase = getApiBase();

    async function loadData() {
      try {
        const [vitalsRes, analyticsRes, eventsRes, patientRes, diagRes] = await Promise.allSettled([
          fetch(`${apiBase}/api/vitals/latest`),
          fetch(`${apiBase}/api/analytics/latest`),
          fetch(`${apiBase}/api/events/latest?limit=15`),
          fetch(`${apiBase}/api/patients/${PATIENT_MRN}`),
          fetch(`${apiBase}/api/diagnostics/latest`),
        ]);

        if (vitalsRes.status === 'fulfilled' && vitalsRes.value.ok) {
          const v = await vitalsRes.value.json();
          if (v && v.heartRateBpm) setVitals(v);
        }

        if (analyticsRes.status === 'fulfilled' && analyticsRes.value.ok) {
          const a = await analyticsRes.value.json();
          if (a) setAnalytics(a);
        }

        if (eventsRes.status === 'fulfilled' && eventsRes.value.ok) {
          const evts = await eventsRes.value.json();
          if (Array.isArray(evts) && evts.length > 0) {
            setGlitchTicker(evts);
            setLatestEvent(evts[0]);
          }
        }

        if (patientRes.status === 'fulfilled' && patientRes.value.ok) {
          const p = await patientRes.value.json();
          if (p && p.name) setPatient(p);
        }

        if (diagRes.status === 'fulfilled' && diagRes.value.ok) {
          const d = await diagRes.value.json();
          if (d) setDiagnostics(d);
        }

        setBackendOnline(true);
      } catch (err) {
        console.warn('Initial data load exception:', err);
      }
    }

    loadData();
  }, []);

  // WebSocket Live Updates
  useEffect(() => {
    const wsUrl = getWsUrl();
    let ws: WebSocket | null = null;
    let reconnectTimer: NodeJS.Timeout;

    const connect = () => {
      ws = new WebSocket(wsUrl);

      ws.onopen = () => {
        setBackendOnline(true);
        setBleConnected(true);
      };

      ws.onmessage = (event) => {
        try {
          const raw = JSON.parse(event.data);

          if (raw.type === 'vitals_sample' && raw.data) {
            setVitals(raw.data);
            setBleConnected(true);
          } else if (raw.type === 'analytics_5min' && raw.data) {
            setAnalytics(raw.data);
          } else if (raw.type === 'clinical_event' && raw.event) {
            const newEvt: ClinicalEvent = raw.event;
            setLatestEvent(newEvt);
            setGlitchTicker((prev) => [newEvt, ...prev.slice(0, 29)]);
            if (raw.snippet) {
              setActiveSnippet(raw.snippet);
            }
          } else if (raw.type === 'diagnostics' && raw.data) {
            setDiagnostics(raw.data);
            setBleConnected(raw.data.bleConnected);
          } else if (raw.type === 'device_health' && raw.data) {
            setDeviceHealth(raw.data);
          } else if (raw.current_hr !== undefined) {
            // Legacy packet fallback
            setVitals({
              heartRateBpm: raw.current_hr,
              spo2Pct: raw.spo2_pct ?? 98,
              deviceId: 'tarang-efr32-demo',
              ts: new Date().toISOString(),
            });
            setBleConnected(true);
          }
          setBackendOnline(true);
        } catch {
          console.warn('[Tarang WS] Error parsing message');
        }
      };

      ws.onerror = () => {
        setBackendOnline(false);
      };

      ws.onclose = () => {
        setBleConnected(false);
        reconnectTimer = setTimeout(connect, 3000);
      };
    };

    connect();

    return () => {
      clearTimeout(reconnectTimer);
      ws?.close();
    };
  }, []);

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
      console.warn('[Tarang] Could not persist settings');
    }
  }, []);

  const legacyTelemetry: ClinicalTelemetryPacket = {
    timestamp_ms: Date.now(),
    beat_class: 0,
    confidence: 250,
    rr_interval_ms: vitals.heartRateBpm ? Math.round(60000 / vitals.heartRateBpm) : 800,
    rhythm_flags: latestEvent?.rhythmStatus ?? 0,
    pac_burden_pct: analytics.pacBurdenPct,
    pvc_burden_pct: analytics.pvcBurdenPct,
    current_hr: vitals.heartRateBpm ?? 75,
    sdnn_ms: Math.round(analytics.sdnn),
    rmssd_ms: Math.round(analytics.rmssd),
    spo2_pct: vitals.spo2Pct ?? 98,
  };

  return (
    <div className="min-h-screen bg-[var(--color-surface)]">
      <Sidebar activeTab={activeTab} setActiveTab={setActiveTab} bleConnected={bleConnected} />

      {!backendOnline && (
        <div
          style={{ position: 'fixed', top: 12, right: 12, zIndex: 9999 }}
          className="text-[10px] px-2 py-1 rounded-full font-mono font-bold bg-amber-100 text-amber-800 border border-amber-300"
        >
          ⚡ Offline Mode — Start backend on :8000
        </div>
      )}

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
            telemetry={legacyTelemetry}
            deviceHealth={deviceHealth}
            onComplete={() => setIsDeviceReady(true)}
            onRetry={() => {
              window.location.reload();
            }}
          />
        )}

        {activeTab === 'workstation' && isDeviceReady && (
          <WorkstationView
            vitals={vitals}
            analytics={analytics}
            latestEvent={latestEvent}
            activeSnippet={activeSnippet}
            glitchTicker={glitchTicker}
            patient={patient}
            onClearSnapshot={() => setActiveSnippet(null)}
          />
        )}

        {activeTab === 'diagnostics' && (
          <DiagnosticsView diagnostics={diagnostics} deviceHealth={deviceHealth} />
        )}

        {activeTab === 'settings' && (
          <SettingsView settings={settings} onSaveSettings={handleSaveSettings} />
        )}
      </main>

      {activeTab === 'workstation' && isDeviceReady && (
        <PatientSummarySidebar patient={patient} telemetry={legacyTelemetry} />
      )}
    </div>
  );
}
