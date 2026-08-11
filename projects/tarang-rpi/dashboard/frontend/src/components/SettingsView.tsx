'use client';

import React, { useState } from 'react';
import { SystemSettings } from '../types/telemetry';
import { Settings, User, Bell, Sliders, Save, CheckCircle, Radio, Monitor } from 'lucide-react';

interface SettingsViewProps {
  settings: SystemSettings;
  onSaveSettings: (newSettings: SystemSettings) => void;
}

export const SettingsView: React.FC<SettingsViewProps> = ({ settings, onSaveSettings }) => {
  const [form, setForm] = useState<SystemSettings>(settings);
  const [saved, setSaved] = useState(false);

  const handleSubmit = (e: React.FormEvent) => {
    e.preventDefault();
    onSaveSettings(form);
    setSaved(true);
    setTimeout(() => setSaved(false), 3000);
  };

  return (
    <form onSubmit={handleSubmit} className="space-y-6">
      {/* Header Banner */}
      <div className="flex items-center justify-between bg-white p-4 rounded-xl border border-[var(--color-outline-variant)] shadow-sm">
        <div>
          <h1 className="text-2xl font-extrabold text-[var(--color-on-surface)] flex items-center gap-2">
            <Settings className="w-7 h-7 text-[var(--color-primary)]" />
            System Settings & Clinical Thresholds
          </h1>
          <p className="text-xs text-[var(--color-on-surface-variant)] mt-1">
            Configure vitals alarm trigger ranges, BLE telemetry sync rates & clinician workstation preferences.
          </p>
        </div>

        <button type="submit" className="py-2.5 px-5 rounded-lg bg-[var(--color-primary)] text-white text-xs font-bold flex items-center gap-2 hover:bg-[var(--color-primary-container)] transition-colors shadow-sm">
          <Save className="w-4 h-4" />
          <span>Save Settings</span>
        </button>
      </div>

      {saved && (
        <div className="p-3 rounded-lg bg-emerald-100 border border-emerald-300 text-emerald-900 text-xs font-bold flex items-center gap-2">
          <CheckCircle className="w-4 h-4 text-emerald-700" />
          <span>System configuration successfully updated and synced with telemetry engine!</span>
        </div>
      )}

      {/* Main Settings Form Grid */}
      <div className="grid grid-cols-2 gap-6">
        {/* Card 1: Clinical Alarm Thresholds */}
        <div className="card-clinical p-5 space-y-4">
          <div className="flex items-center gap-2 border-b border-[var(--color-outline-variant)] pb-3">
            <Bell className="w-5 h-5 text-[var(--color-primary)]" />
            <h2 className="text-sm font-bold text-[var(--color-on-surface)] uppercase tracking-wider">
              Clinical Vitals Alarm Limits
            </h2>
          </div>

          <div className="space-y-4">
            {/* Heart Rate Limits */}
            <div>
              <label className="text-xs font-bold text-[var(--color-on-surface)] block mb-1">
                Heart Rate Alarm Range (BPM)
              </label>
              <div className="grid grid-cols-2 gap-3">
                <div>
                  <span className="text-[11px] text-[var(--color-on-surface-variant)] block font-mono">Bradycardia &lt;</span>
                  <input
                    type="number"
                    value={form.hrLowThreshold}
                    onChange={e => setForm({ ...form, hrLowThreshold: Number(e.target.value) })}
                    className="w-full mt-1 p-2 rounded-md border border-[var(--color-outline-variant)] bg-[var(--color-surface-container-low)] font-mono text-sm text-[var(--color-on-surface)]"
                  />
                </div>
                <div>
                  <span className="text-[11px] text-[var(--color-on-surface-variant)] block font-mono">Tachycardia &gt;</span>
                  <input
                    type="number"
                    value={form.hrHighThreshold}
                    onChange={e => setForm({ ...form, hrHighThreshold: Number(e.target.value) })}
                    className="w-full mt-1 p-2 rounded-md border border-[var(--color-outline-variant)] bg-[var(--color-surface-container-low)] font-mono text-sm text-[var(--color-on-surface)]"
                  />
                </div>
              </div>
            </div>

            {/* SpO2 Threshold */}
            <div>
              <label className="text-xs font-bold text-[var(--color-on-surface)] block mb-1">
                SpO2 Hypoxia Alert Trigger (%)
              </label>
              <input
                type="number"
                value={form.spo2LowThreshold}
                onChange={e => setForm({ ...form, spo2LowThreshold: Number(e.target.value) })}
                className="w-full p-2 rounded-md border border-[var(--color-outline-variant)] bg-[var(--color-surface-container-low)] font-mono text-sm text-[var(--color-on-surface)]"
              />
              <p className="text-[11px] text-[var(--color-on-surface-variant)] mt-1">Triggers high-priority audio alert when oxygen saturation drops below value.</p>
            </div>
          </div>
        </div>

        {/* Card 2: Telemetry & Connectivity Config */}
        <div className="card-clinical p-5 space-y-4">
          <div className="flex items-center gap-2 border-b border-[var(--color-outline-variant)] pb-3">
            <Radio className="w-5 h-5 text-[var(--color-primary)]" />
            <h2 className="text-sm font-bold text-[var(--color-on-surface)] uppercase tracking-wider">
              BLE Telemetry & Sync Rules
            </h2>
          </div>

          <div className="space-y-4">
            <div>
              <label className="text-xs font-bold text-[var(--color-on-surface)] block mb-1">
                BLE Notification Sync Frequency
              </label>
              <select
                value={form.bleSyncIntervalMs}
                onChange={e => setForm({ ...form, bleSyncIntervalMs: Number(e.target.value) })}
                className="w-full p-2 rounded-md border border-[var(--color-outline-variant)] bg-[var(--color-surface-container-low)] font-mono text-sm text-[var(--color-on-surface)]"
              >
                <option value={1000}>1000 ms (1 Hz Standard Fallback)</option>
                <option value={500}>500 ms (2 Hz High-Rate Telemetry)</option>
                <option value={2000}>2000 ms (Low-Power Monitoring)</option>
              </select>
            </div>

            <div className="flex items-center justify-between p-3 rounded-lg bg-[var(--color-surface-container-low)] border border-[var(--color-outline-variant)]">
              <div>
                <p className="text-xs font-bold text-[var(--color-on-surface)]">Audible Alert Chime</p>
                <p className="text-[11px] text-[var(--color-on-surface-variant)]">Sound alarm speakers on arrhythmia events</p>
              </div>
              <input
                type="checkbox"
                checked={form.audioAlertsEnabled}
                onChange={e => setForm({ ...form, audioAlertsEnabled: e.target.checked })}
                className="w-5 h-5 accent-[var(--color-primary)]"
              />
            </div>
          </div>
        </div>

        {/* Card 3: Doctor Credentials */}
        <div className="card-clinical p-5 space-y-4 col-span-2">
          <div className="flex items-center gap-2 border-b border-[var(--color-outline-variant)] pb-3">
            <User className="w-5 h-5 text-[var(--color-primary)]" />
            <h2 className="text-sm font-bold text-[var(--color-on-surface)] uppercase tracking-wider">
              Attending Physician & Workstation Info
            </h2>
          </div>

          <div className="grid grid-cols-2 gap-4">
            <div>
              <label className="text-xs font-bold text-[var(--color-on-surface)] block mb-1">
                Lead Physician Name
              </label>
              <input
                type="text"
                value={form.attendingDoctor}
                onChange={e => setForm({ ...form, attendingDoctor: e.target.value })}
                className="w-full p-2 rounded-md border border-[var(--color-outline-variant)] bg-[var(--color-surface-container-low)] text-sm text-[var(--color-on-surface)]"
              />
            </div>

            <div>
              <label className="text-xs font-bold text-[var(--color-on-surface)] block mb-1">
                Workstation Station ID
              </label>
              <input
                type="text"
                disabled
                value="WS-ICU-CARDIO-04"
                className="w-full p-2 rounded-md border border-[var(--color-outline-variant)] bg-gray-100 font-mono text-sm text-[var(--color-on-surface-variant)]"
              />
            </div>
          </div>
        </div>
      </div>
    </form>
  );
};
