import React, { useState, useEffect } from 'react';
import { Sidebar } from './components/Sidebar';
import { WorkstationView } from './components/WorkstationView';
import { PatientSummarySidebar } from './components/PatientSummarySidebar';
import { DiagnosticsView } from './components/DiagnosticsView';
import { SettingsView } from './components/SettingsView';
import {
  VitalsSample,
  Analytics5Min,
  ClinicalEvent,
  EcgSnippet,
  PatientInfo,
  TelemetryDiagnostics,
  SystemSettings,
  ClinicalTelemetryPacket,
} from './types/telemetry';

const BACKEND_URL = process.env.NEXT_PUBLIC_API_URL || 'http://localhost:8000';
const WS_URL = process.env.NEXT_PUBLIC_WS_URL || 'ws://localhost:8000/ws/telemetry';

export const App: React.FC = () => {
  const [activeTab, setActiveTab] = useState<'workstation' | 'diagnostics' | 'settings'>('workstation');
  const [bleConnected, setBleConnected] = useState<boolean>(true);

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

  // Patient Record Summary
  const [patient] = useState<PatientInfo>({
    name: 'John Doe',
    age: 58,
    gender: 'Male',
    id: '884219',
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
  });

  // Diagnostics
  const [diagnostics, setDiagnostics] = useState<TelemetryDiagnostics>({
    bleConnected: true,
    deviceName: 'EFR32MG26 (Tarang SoC)',
    deviceMac: '70:B3:D5:70:9A:C4',
    firmwareVersion: 'v1.0.0-ModeA',
    rssiDbm: -58,
    packetsReceived: 48921,
    packetsDropped: 0,
    latencyMs: 1.4,
    batteryPct: 94,
    ecgDmaHealth: true,
    ppgI2cHealth: true,
    imuFifoHealth: true,
    lastSyncTimestamp: new Date().toLocaleTimeString(),
  });

  const [settings, setSettings] = useState<SystemSettings>({
    hrLowThreshold: 60,
    hrHighThreshold: 100,
    spo2LowThreshold: 92,
    rrLowThreshold: 10,
    rrHighThreshold: 24,
    bleSyncIntervalMs: 2000,
    gridDensity: 'standard',
    audioAlertsEnabled: true,
    attendingDoctor: 'Dr. Aris',
  });

  // Fetch initial Mode A data
  useEffect(() => {
    async function loadInitialData() {
      try {
        const [vitalsRes, analyticsRes, eventsRes] = await Promise.allSettled([
          fetch(`${BACKEND_URL}/api/vitals/latest`),
          fetch(`${BACKEND_URL}/api/analytics/latest`),
          fetch(`${BACKEND_URL}/api/events/latest?limit=10`),
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
      } catch (err) {
        console.warn('Initial data load error:', err);
      }
    }

    loadInitialData();
  }, []);

  // Live WebSocket Connection for Real-Time Mode A Pushes
  useEffect(() => {
    let ws: WebSocket | null = null;
    let reconnectTimer: NodeJS.Timeout;

    function connectWs() {
      try {
        ws = new WebSocket(WS_URL);

        ws.onopen = () => {
          setBleConnected(true);
        };

        ws.onmessage = (event) => {
          try {
            const data = JSON.parse(event.data);

            if (data.type === 'vitals_sample' && data.data) {
              setVitals(data.data);
            } else if (data.type === 'analytics_5min' && data.data) {
              setAnalytics(data.data);
            } else if (data.type === 'clinical_event' && data.event) {
              const newEvt: ClinicalEvent = data.event;
              setLatestEvent(newEvt);
              setGlitchTicker((prev) => [newEvt, ...prev.slice(0, 20)]);
              if (data.snippet) {
                setActiveSnippet(data.snippet);
              }
            } else if (data.current_hr !== undefined) {
              // Legacy packet
              setVitals({
                heartRateBpm: data.current_hr,
                spo2Pct: data.spo2_pct ?? 98,
                deviceId: 'tarang-efr32-demo',
                ts: new Date().toISOString(),
              });
            }
          } catch (e) {
            console.error('WS message parse error:', e);
          }
        };

        ws.onclose = () => {
          setBleConnected(false);
          reconnectTimer = setTimeout(connectWs, 3000);
        };

        ws.onerror = () => {
          ws?.close();
        };
      } catch (err) {
        reconnectTimer = setTimeout(connectWs, 3000);
      }
    }

    connectWs();

    return () => {
      clearTimeout(reconnectTimer);
      ws?.close();
    };
  }, []);

  // Adapt for PatientSummarySidebar
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
      {/* Fixed Navigation Sidebar */}
      <Sidebar activeTab={activeTab} setActiveTab={setActiveTab} bleConnected={bleConnected} />

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

        {activeTab === 'diagnostics' && <DiagnosticsView diagnostics={diagnostics} />}

        {activeTab === 'settings' && <SettingsView settings={settings} onSaveSettings={setSettings} />}
      </main>

      {/* Right Sidebar (Patient Summary - Workstation View Only) */}
      {activeTab === 'workstation' && (
        <PatientSummarySidebar patient={patient} telemetry={legacyTelemetry} />
      )}
    </div>
  );
};
