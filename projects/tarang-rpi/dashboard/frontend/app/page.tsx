'use client';

import React, { useCallback, useEffect, useMemo, useState } from 'react';
import { Sidebar } from '../src/components/Sidebar';
import { WorkstationView } from '../src/components/WorkstationView';
import { PatientSummarySidebar } from '../src/components/PatientSummarySidebar';
import { DiagnosticsView } from '../src/components/DiagnosticsView';
import { SettingsView } from '../src/components/SettingsView';
import { DeviceInitialization } from '../src/components/DeviceInitialization';
import { PatientOnboarding } from '../src/components/PatientOnboarding';
import { TopBar } from '../src/components/TopBar';
import {
  Analytics5Min,
  ClinicalEvent,
  ClinicalTelemetryPacket,
  DeviceHealthTelemetry,
  DeviceRecord,
  EcgSnippet,
  MonitoringSession,
  PatientCreateInput,
  PatientInfo,
  SystemSettings,
  TelemetryDiagnostics,
  VitalsSample,
} from '../src/types/telemetry';

type AppPhase = 'worklist' | 'initializing' | 'dashboard';
type ActiveTab = 'workstation' | 'diagnostics' | 'settings';

function getApiBase(): string {
  if (typeof window !== 'undefined') {
    const envUrl = process.env.NEXT_PUBLIC_API_URL;
    if (envUrl && !envUrl.includes('localhost')) return envUrl;
    // If accessed via Cloudflare Tunnel (HTTPS) or Next.js proxy on port 3000, use relative paths
    if (window.location.protocol === 'https:' || window.location.port === '' || window.location.port === '443' || window.location.port === '3000') {
      return '';
    }
    return `${window.location.protocol}//${window.location.hostname}:8000`;
  }
  return process.env.NEXT_PUBLIC_API_URL ?? 'http://localhost:8000';
}

function getWsUrl(): string {
  if (typeof window !== 'undefined') {
    const envUrl = process.env.NEXT_PUBLIC_WS_URL;
    if (envUrl && !envUrl.includes('localhost')) return envUrl;
    const protocol = window.location.protocol === 'https:' ? 'wss:' : 'ws:';
    // If accessed via Cloudflare Tunnel (HTTPS) on standard 443 port
    if (window.location.protocol === 'https:' || window.location.port === '' || window.location.port === '443') {
      return `${protocol}//${window.location.host}/ws/telemetry`;
    }
    return `${protocol}//${window.location.hostname}:8000/ws/telemetry`;
  }
  return process.env.NEXT_PUBLIC_WS_URL ?? 'ws://localhost:8000/ws/telemetry';
}

async function requestJson<T>(path: string, init?: RequestInit): Promise<T> {
  const response = await fetch(`${getApiBase()}${path}`, init);
  if (!response.ok) {
    let message = `${response.status} ${response.statusText}`;
    try {
      const body = await response.json();
      message = typeof body.detail === 'string' ? body.detail : message;
    } catch {
      // Preserve the HTTP status when the response is not JSON.
    }
    throw new Error(message);
  }
  return response.json() as Promise<T>;
}

function normalizePatient(raw: Record<string, unknown>): PatientInfo {
  const gender = raw.gender === 'Male' || raw.gender === 'Female' ? raw.gender : 'Other';
  return {
    dbId: typeof raw.id === 'number' ? raw.id : undefined,
    name: String(raw.name ?? 'Unnamed patient'),
    age: Number(raw.age ?? 0),
    gender,
    id: String(raw.mrn ?? raw.id ?? ''),
    bed: String(raw.bed ?? 'Unassigned'),
    admitDate: String(raw.admit_date ?? 'Not recorded'),
    attendingPhysician: String(raw.attending_physician ?? 'Unassigned'),
    bloodType: String(raw.blood_type ?? 'Unknown'),
    allergies: Array.isArray(raw.allergies) ? raw.allergies.map(String) : [],
    medicalHistory: Array.isArray(raw.medical_history) ? raw.medical_history.map(String) : [],
  };
}

const EMPTY_VITALS: VitalsSample = {
  heartRateBpm: null,
  spo2Pct: null,
  correlationFactor: 0.0,
  motionMg: 0,
  deviceId: 'tarang-efr32-demo',
  ts: null,
};

const EMPTY_ANALYTICS: Analytics5Min = {
  pvcBurdenPct: 0,
  pacBurdenPct: 0,
  sdnn: 0,
  rmssd: 0,
  prr50: 0,
  aiDutyCyclePct: 0,
  em2SleepPct: 0,
  deviceId: 'tarang-efr32-demo',
  ts: null,
};

const DEFAULT_DIAGNOSTICS: TelemetryDiagnostics = {
  bleConnected: false,
  deviceName: 'EFR32MG26 Tarang Wearable',
  deviceMac: 'Not discovered',
  firmwareVersion: 'Unknown',
  rssiDbm: -100,
  packetsReceived: 0,
  packetsDropped: 0,
  latencyMs: 0,
  batteryPct: 0,
  ecgDmaHealth: false,
  ppgI2cHealth: false,
  imuFifoHealth: false,
  lastSyncTimestamp: 'Never',
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
  attendingDoctor: 'Unassigned',
};

export default function Page() {
  const [phase, setPhase] = useState<AppPhase>('dashboard');
  const [activeTab, setActiveTab] = useState<ActiveTab>('workstation');
  const [bootstrapLoading, setBootstrapLoading] = useState(true);
  const [bootstrapError, setBootstrapError] = useState<string | null>(null);
  const [backendOnline, setBackendOnline] = useState(false);
  const [bleConnected, setBleConnected] = useState(false);

  const [patients, setPatients] = useState<PatientInfo[]>([]);
  const [devices, setDevices] = useState<DeviceRecord[]>([]);
  const [sessions, setSessions] = useState<MonitoringSession[]>([]);
  const [patient, setPatient] = useState<PatientInfo | null>(null);
  const [activeSession, setActiveSession] = useState<MonitoringSession | null>(null);
  const [activeDeviceId, setActiveDeviceId] = useState<string | null>(null);

  const [vitals, setVitals] = useState<VitalsSample>(EMPTY_VITALS);
  const [analytics, setAnalytics] = useState<Analytics5Min>(EMPTY_ANALYTICS);
  const [latestEvent, setLatestEvent] = useState<ClinicalEvent | null>(null);
  const [activeSnippet, setActiveSnippet] = useState<EcgSnippet | null>(null);
  const [glitchTicker, setGlitchTicker] = useState<ClinicalEvent[]>([]);
  const [diagnostics, setDiagnostics] = useState<TelemetryDiagnostics>(DEFAULT_DIAGNOSTICS);
  const [deviceHealth, setDeviceHealth] = useState<DeviceHealthTelemetry | undefined>();
  const [settings, setSettings] = useState<SystemSettings>(DEFAULT_SETTINGS);

  const [loadingEventId, setLoadingEventId] = useState<number | null>(null);
  const [exportBusy, setExportBusy] = useState(false);
  const [pageBusy, setPageBusy] = useState(false);
  const [actionMessage, setActionMessage] = useState<string | null>(null);
  const [sidebarCollapsed, setSidebarCollapsed] = useState(true);
  const [patientRailCollapsed, setPatientRailCollapsed] = useState(true);

  const loadMonitoringData = useCallback(async (session: MonitoringSession) => {
    const query = new URLSearchParams();
    if (session.session_id) query.set('session_id', session.session_id);
    if (session.device_id) query.set('device_id', session.device_id);
    const suffix = query.toString() ? `?${query.toString()}` : '';
    const [latestVitals, latestAnalytics, events, currentDiagnostics] = await Promise.all([
      requestJson<VitalsSample>(`/api/vitals/latest${suffix}`),
      requestJson<Analytics5Min>(`/api/analytics/latest${suffix}`),
      requestJson<ClinicalEvent[]>(`/api/events/latest${suffix}${suffix ? '&' : '?'}limit=30`),
      requestJson<TelemetryDiagnostics>('/api/diagnostics/latest'),
    ]);
    setVitals(latestVitals.id ? latestVitals : EMPTY_VITALS);
    setAnalytics(latestAnalytics.id ? latestAnalytics : EMPTY_ANALYTICS);
    setGlitchTicker(events);
    setLatestEvent(events[0] ?? null);
    setActiveSnippet(null);
    setDiagnostics(currentDiagnostics);
    setBleConnected(currentDiagnostics.bleConnected);

    const firstEvent = events[0];
    if (firstEvent?.id) {
      try {
        setActiveSnippet(await requestJson<EcgSnippet>(`/api/events/${firstEvent.id}/snippet`));
      } catch {
        setActiveSnippet(null);
      }
    }
  }, []);

  const loadBootstrap = useCallback(async () => {
    setBootstrapLoading(true);
    setBootstrapError(null);
    try {
      const [health, patientRows, deviceRows, sessionRows, savedSettings, currentDiagnostics] = await Promise.all([
        requestJson<{ status: string; database: string }>('/api/health'),
        requestJson<Record<string, unknown>[]>('/api/patients'),
        requestJson<DeviceRecord[]>('/api/devices'),
        requestJson<MonitoringSession[]>('/api/sessions'),
        requestJson<SystemSettings>('/api/settings'),
        requestJson<TelemetryDiagnostics>('/api/diagnostics/latest'),
      ]);
      if (health.status !== 'ok' || health.database !== 'ok') throw new Error('Clinical database is not ready');
      const normalizedPatients = patientRows.map(normalizePatient);
      setPatients(normalizedPatients);
      setDevices(deviceRows);
      setSessions(sessionRows);
      setSettings(savedSettings);
      setDiagnostics(currentDiagnostics);
      setBleConnected(currentDiagnostics.bleConnected);
      setBackendOnline(true);

      // Auto-bind active patient & session so kiosk opens straight to the live dashboard
      const active = sessionRows.find((s) => s.status === 'active') ?? sessionRows[0];
      if (active) {
        setActiveSession(active);
        setActiveDeviceId(active.device_id ?? null);
        const matchedPatient = normalizedPatients.find((p) => p.dbId === active.patient_id) ?? normalizedPatients[0];
        if (matchedPatient) {
          setPatient(matchedPatient);
          await loadMonitoringData(active);
          setPhase('dashboard');
        }
      } else if (normalizedPatients.length > 0) {
        setPatient(normalizedPatients[0]);
        setPhase('dashboard');
      }
    } catch (error) {
      setBackendOnline(false);
      setBleConnected(false);
      setBootstrapError(error instanceof Error ? error.message : 'Unable to load clinical services');
      // Auto-retry after 1.5s if backend is still starting up
      setTimeout(() => {
        loadBootstrap();
      }, 1500);
    } finally {
      setBootstrapLoading(false);
    }
  }, [loadMonitoringData]);

  useEffect(() => {
    loadBootstrap();
  }, [loadBootstrap]);

  useEffect(() => {
    const wsUrl = getWsUrl();
    let socket: WebSocket | null = null;
    let reconnectTimer: ReturnType<typeof setTimeout>;
    let disposed = false;

    const connect = () => {
      if (disposed) return;
      socket = new WebSocket(wsUrl);
      socket.onopen = () => setBackendOnline(true);
      socket.onmessage = (message) => {
        try {
          const raw = JSON.parse(message.data);
          const currentSessionId = activeSession?.session_id;
          const packetSessionId = raw.data?.sessionId ?? raw.event?.sessionId ?? raw.session_id;
          if (currentSessionId && packetSessionId && packetSessionId !== currentSessionId) return;

          if (raw.type === 'vitals_sample' && raw.data) {
            setVitals(raw.data);
          } else if (raw.type === 'analytics_5min' && raw.data) {
            setAnalytics(raw.data);
          } else if (raw.type === 'clinical_event' && raw.event) {
            setLatestEvent(raw.event);
            setGlitchTicker((current) => [raw.event, ...current.filter((item) => item.id !== raw.event.id)].slice(0, 30));
            if (raw.snippet) setActiveSnippet(raw.snippet);
          } else if (raw.type === 'events_cleared') {
            setLatestEvent(null);
            setActiveSnippet(null);
            setGlitchTicker([]);
          } else if (raw.type === 'diagnostics' && raw.data) {
            setDiagnostics(raw.data);
            setBleConnected(Boolean(raw.data.bleConnected));
          } else if (raw.type === 'device_health' && raw.data) {
            setDeviceHealth(raw.data);
          } else if (raw.current_hr !== undefined) {
            setVitals({
              heartRateBpm: raw.current_hr,
              spo2Pct: raw.spo2_pct ?? null,
              deviceId: activeDeviceId ?? 'tarang-efr32-demo',
              ts: new Date().toISOString(),
            });
          }
          setBackendOnline(true);
        } catch {
          console.warn('[Tarang] Ignored malformed WebSocket message');
        }
      };
      socket.onerror = () => setBackendOnline(false);
      socket.onclose = () => {
        setBackendOnline(false);
        setBleConnected(false);
        if (!disposed) reconnectTimer = setTimeout(connect, 3000);
      };
    };

    connect();
    return () => {
      disposed = true;
      clearTimeout(reconnectTimer);
      socket?.close();
    };
  }, [activeDeviceId, activeSession?.session_id]);

  const createPatient = useCallback(async (input: PatientCreateInput) => {
    const created = await requestJson<Record<string, unknown>>('/api/patients', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(input),
    });
    const normalized = normalizePatient(created);
    setPatients((current) => [...current, normalized].sort((a, b) => a.name.localeCompare(b.name)));
  }, []);

  const startMonitoring = useCallback(async (selectedPatient: PatientInfo, deviceId?: string) => {
    let session = sessions.find(
      (candidate) => candidate.status === 'active' && candidate.patient_id === selectedPatient.dbId
    );
    if (!session) {
      session = await requestJson<MonitoringSession>('/api/sessions', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ mrn: selectedPatient.id, device_id: deviceId, bed: selectedPatient.bed }),
      });
      setSessions((current) => [session as MonitoringSession, ...current]);
    }
    if (!session) throw new Error('Monitoring session could not be created');
    setPatient(selectedPatient);
    setActiveSession(session);
    setActiveDeviceId(session.device_id ?? deviceId ?? null);
    const boundDeviceId = session.device_id ?? deviceId;
    if (boundDeviceId) {
      setDevices((current) => current.map((device) => device.device_id === boundDeviceId
        ? { ...device, status: 'in_use', assigned_patient_id: selectedPatient.dbId ?? null }
        : device));
    }
    setDeviceHealth(undefined);
    setActionMessage(null);
    setActiveTab('workstation');
    await loadMonitoringData(session);
    setPhase('initializing');
  }, [loadMonitoringData, sessions]);

  const completeInitialization = useCallback(() => setPhase('dashboard'), []);

  const retryInitialization = useCallback(async () => {
    try {
      const [health, currentDiagnostics] = await Promise.all([
        requestJson<DeviceHealthTelemetry>('/api/health/device'),
        requestJson<TelemetryDiagnostics>('/api/diagnostics/latest'),
      ]);
      setBackendOnline(true);
      setDiagnostics(currentDiagnostics);
      setBleConnected(currentDiagnostics.bleConnected);
      if (health.id && currentDiagnostics.bleConnected) setDeviceHealth(health);
    } catch {
      setBackendOnline(false);
      setBleConnected(false);
    }
  }, []);

  const saveSettings = useCallback(async (newSettings: SystemSettings) => {
    const saved = await requestJson<SystemSettings>('/api/settings', {
      method: 'PUT',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(newSettings),
    });
    setSettings(saved);
  }, []);

  const selectEvent = useCallback(async (event: ClinicalEvent) => {
    if (!event.id) return;
    setLoadingEventId(event.id);
    setActionMessage(null);
    try {
      const snippet = await requestJson<EcgSnippet>(`/api/events/${event.id}/snippet`);
      setLatestEvent(event);
      setActiveSnippet(snippet);
      window.scrollTo({ top: 0, behavior: 'smooth' });
    } catch (loadError) {
      setActionMessage(loadError instanceof Error ? loadError.message : 'ECG snippet is unavailable');
    } finally {
      setLoadingEventId(null);
    }
  }, []);

  const exportEcg = useCallback(async () => {
    const eventId = activeSnippet?.eventId;
    if (!eventId) return;
    setExportBusy(true);
    setActionMessage(null);
    try {
      const response = await fetch(`${getApiBase()}/api/events/${eventId}/pdf`);
      if (!response.ok) throw new Error('Unable to generate the ECG PDF');
      const blob = await response.blob();
      const url = URL.createObjectURL(blob);
      const anchor = document.createElement('a');
      anchor.href = url;
      anchor.download = `tarang-${patient?.id ?? 'patient'}-event-${eventId}.pdf`;
      document.body.appendChild(anchor);
      anchor.click();
      anchor.remove();
      URL.revokeObjectURL(url);
      setActionMessage('ECG PDF downloaded');
    } catch (exportError) {
      setActionMessage(exportError instanceof Error ? exportError.message : 'Unable to export ECG PDF');
    } finally {
      setExportBusy(false);
    }
  }, [activeSnippet?.eventId, patient?.id]);

  const pagePhysician = useCallback(async () => {
    if (!patient) return;
    setPageBusy(true);
    setActionMessage(null);
    try {
      const action = await requestJson<{ id: number; status: string }>('/api/clinical-actions/page-physician', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          mrn: patient.id,
          session_id: activeSession?.session_id,
          priority: ((latestEvent?.rhythmStatus ?? 0) & 0x80) !== 0 ? 'critical' : 'urgent',
          reason: latestEvent?.patternType
            ? `${latestEvent.patternType} event requires clinical review`
            : 'Clinical review requested from the telemetry workstation',
          requested_by: settings.attendingDoctor,
        }),
      });
      setActionMessage(`Duty physician page queued, reference #${action.id}`);
    } catch (pageError) {
      setActionMessage(pageError instanceof Error ? pageError.message : 'Unable to page the duty physician');
    } finally {
      setPageBusy(false);
    }
  }, [activeSession?.session_id, latestEvent?.patternType, latestEvent?.rhythmStatus, patient, settings.attendingDoctor]);

  const legacyTelemetry: ClinicalTelemetryPacket = useMemo(() => ({
    timestamp_ms: Date.now(),
    beat_class: 0,
    confidence: latestEvent?.confidence ? Math.round(latestEvent.confidence * 255) : 0,
    rr_interval_ms: vitals.heartRateBpm ? Math.round(60000 / vitals.heartRateBpm) : 0,
    rhythm_flags: latestEvent?.rhythmStatus ?? 0,
    pac_burden_pct: analytics.pacBurdenPct,
    pvc_burden_pct: analytics.pvcBurdenPct,
    current_hr: vitals.heartRateBpm ?? 0,
    sdnn_ms: Math.round(analytics.sdnn),
    rmssd_ms: Math.round(analytics.rmssd),
    spo2_pct: vitals.spo2Pct ?? undefined,
  }), [analytics, latestEvent, vitals]);

  const activeDevice = devices.find((device) => device.device_id === activeDeviceId);

  if (phase === 'worklist') {
    return (
      <PatientOnboarding
        patients={patients}
        devices={devices}
        sessions={sessions}
        loading={bootstrapLoading}
        error={bootstrapError}
        onRetry={loadBootstrap}
        onCreatePatient={createPatient}
        onStartMonitoring={startMonitoring}
      />
    );
  }

  if (phase === 'initializing' && patient) {
    return (
      <DeviceInitialization
        backendOnline={backendOnline}
        bleConnected={bleConnected}
        telemetry={legacyTelemetry}
        telemetryReady={Boolean(vitals.ts)}
        deviceHealth={deviceHealth}
        deviceName={activeDevice?.name ?? diagnostics.deviceName}
        sessionLabel={activeSession?.session_id}
        onComplete={completeInitialization}
        onRetry={retryInitialization}
        onBack={() => setPhase('worklist')}
      />
    );
  }

  const activePatient = patient || patients[0] || {
    name: 'Bedside Monitor',
    age: 0,
    gender: 'Other',
    id: 'TRG-LIVE',
    bed: 'ICU-01',
    admitDate: 'Active',
    attendingPhysician: settings.attendingDoctor || 'Attending Physician',
    bloodType: 'Unknown',
    allergies: [],
    medicalHistory: [],
  };

  return (
    <div className="app-shell">
      <TopBar
        patient={activePatient}
        bleConnected={bleConnected}
        backendOnline={backendOnline}
        pageBusy={pageBusy}
        onEmergency={pagePhysician}
        onOpenWorkstation={() => setActiveTab('workstation')}
        onOpenSettings={() => setActiveTab('settings')}
        sidebarCollapsed={sidebarCollapsed}
        patientRailCollapsed={patientRailCollapsed}
        onToggleSidebar={() => setSidebarCollapsed((v) => !v)}
        onTogglePatientRail={() => setPatientRailCollapsed((v) => !v)}
      />
      <Sidebar
        activeTab={activeTab}
        setActiveTab={setActiveTab}
        bleConnected={bleConnected}
        patientName={activePatient.name}
        attendingDoctor={settings.attendingDoctor}
        onChangePatient={() => setPhase('worklist')}
        collapsed={sidebarCollapsed}
        onToggleCollapse={() => setSidebarCollapsed((v) => !v)}
      />

      {!backendOnline && (
        <div className="fixed left-1/2 top-[72px] z-50 -translate-x-1/2 rounded border border-amber-300 bg-amber-50 px-3 py-1 font-mono text-[10px] font-bold text-amber-900 shadow-sm">
          Backend reconnecting...
        </div>
      )}

      <main className={`app-main ${sidebarCollapsed ? 'app-main--sidebar-collapsed' : ''} ${activeTab === 'workstation' ? (patientRailCollapsed ? 'app-main--rail-collapsed' : 'app-main--with-rail') : ''}`}>
        {activeTab === 'workstation' && (
          <WorkstationView
            vitals={vitals}
            analytics={analytics}
            latestEvent={latestEvent}
            activeSnippet={activeSnippet}
            glitchTicker={glitchTicker}
            patient={activePatient}
            onClearSnapshot={() => setActiveSnippet(null)}
            onSelectEvent={selectEvent}
            loadingEventId={loadingEventId}
          />
        )}
        {activeTab === 'diagnostics' && <DiagnosticsView diagnostics={diagnostics} deviceHealth={deviceHealth} />}
        {activeTab === 'settings' && <SettingsView settings={settings} onSaveSettings={saveSettings} />}
      </main>

      {activeTab === 'workstation' && (
        <PatientSummarySidebar
          patient={activePatient}
          telemetry={legacyTelemetry}
          canExportEcg={Boolean(activeSnippet?.eventId && activeSnippet.waveform?.length)}
          exportBusy={exportBusy}
          pageBusy={pageBusy}
          actionMessage={actionMessage}
          onExportEcg={exportEcg}
          onPagePhysician={pagePhysician}
          collapsed={patientRailCollapsed}
          onToggleCollapse={() => setPatientRailCollapsed((v) => !v)}
        />
      )}
    </div>
  );
}
