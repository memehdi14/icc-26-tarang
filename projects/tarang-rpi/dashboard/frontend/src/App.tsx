import React, { useState, useEffect } from 'react';
import { Sidebar } from './components/Sidebar';
import { WorkstationView } from './components/WorkstationView';
import { PatientSummarySidebar } from './components/PatientSummarySidebar';
import { DiagnosticsView } from './components/DiagnosticsView';
import { SettingsView } from './components/SettingsView';
import { ClinicalTelemetryPacket, PatientInfo, TelemetryDiagnostics, SystemSettings } from './types/telemetry';

export const App: React.FC = () => {
  const [activeTab, setActiveTab] = useState<'workstation' | 'diagnostics' | 'settings'>('workstation');
  const [bleConnected, setBleConnected] = useState<boolean>(true);

  // Live Clinical Telemetry State
  const [telemetry, setTelemetry] = useState<ClinicalTelemetryPacket>({
    timestamp_ms: Date.now(),
    beat_class: 0,
    confidence: 251,
    rr_interval_ms: 810,
    rhythm_flags: 0x01,
    pac_burden_pct: 1.2,
    pvc_burden_pct: 0.4,
    current_hr: 74,
    sdnn_ms: 44,
    rmssd_ms: 38,
    spo2_pct: 98,
    resp_rate: 16,
    bp_systolic: 120,
    bp_diastolic: 80
  });

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
      'Type 2 Diabetes Mellitus'
    ]
  });

  // Telemetry Diagnostics Metrics
  const [diagnostics] = useState<TelemetryDiagnostics>({
    bleConnected: true,
    deviceName: 'EFR32MG26 (Tarang SoC)',
    deviceMac: '70:B3:D5:70:9A:C4',
    firmwareVersion: 'v1.0.0-EFR32MG26',
    rssiDbm: -58,
    packetsReceived: 48921,
    packetsDropped: 0,
    latencyMs: 12.4,
    batteryPct: 94,
    ecgDmaHealth: true,
    ppgI2cHealth: true,
    imuFifoHealth: true,
    lastSyncTimestamp: new Date().toLocaleTimeString()
  });

  // System Settings State
  const [settings, setSettings] = useState<SystemSettings>({
    hrLowThreshold: 60,
    hrHighThreshold: 100,
    spo2LowThreshold: 92,
    rrLowThreshold: 10,
    rrHighThreshold: 24,
    bleSyncIntervalMs: 1000,
    gridDensity: 'standard',
    audioAlertsEnabled: true,
    attendingDoctor: 'Dr. Aris'
  });

  // Live heart rate telemetry tick simulation
  useEffect(() => {
    const interval = setInterval(() => {
      setTelemetry(prev => {
        const delta = Math.floor(Math.random() * 3) - 1;
        const newHr = Math.min(85, Math.max(65, prev.current_hr + delta));
        return {
          ...prev,
          timestamp_ms: Date.now(),
          current_hr: newHr,
          rr_interval_ms: Math.round(60000 / newHr),
          sdnn_ms: 42 + Math.floor(Math.random() * 4),
          rmssd_ms: 36 + Math.floor(Math.random() * 4)
        };
      });
    }, settings.bleSyncIntervalMs);

    return () => clearInterval(interval);
  }, [settings.bleSyncIntervalMs]);

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
          paddingBottom: '32px'
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
          <SettingsView settings={settings} onSaveSettings={setSettings} />
        )}
      </main>

      {/* Right Sidebar (Patient Summary - Workstation View Only) */}
      {activeTab === 'workstation' && (
        <PatientSummarySidebar patient={patient} telemetry={telemetry} />
      )}
    </div>
  );
};
