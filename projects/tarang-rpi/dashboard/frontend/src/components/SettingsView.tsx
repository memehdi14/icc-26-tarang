'use client';

import React, { useEffect, useState } from 'react';
import {
  Activity,
  BellRing,
  Check,
  CircleUserRound,
  LoaderCircle,
  MonitorCog,
  Radio,
  Save,
  SlidersHorizontal,
} from 'lucide-react';
import { SystemSettings } from '../types/telemetry';

interface SettingsViewProps {
  settings: SystemSettings;
  onSaveSettings: (newSettings: SystemSettings) => Promise<void>;
}

type SettingsSection = 'thresholds' | 'telemetry' | 'display' | 'clinician';

export const SettingsView: React.FC<SettingsViewProps> = ({ settings, onSaveSettings }) => {
  const [form, setForm] = useState<SystemSettings>(settings);
  const [activeSection, setActiveSection] = useState<SettingsSection>('thresholds');
  const [saved, setSaved] = useState(false);
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => setForm(settings), [settings]);

  const handleSubmit = async (event: React.FormEvent) => {
    event.preventDefault();
    setSaving(true);
    setSaved(false);
    setError(null);
    try {
      await onSaveSettings(form);
      setSaved(true);
      window.setTimeout(() => setSaved(false), 3000);
    } catch (saveError) {
      setError(saveError instanceof Error ? saveError.message : 'Unable to save settings');
    } finally {
      setSaving(false);
    }
  };

  const sections: Array<{ id: SettingsSection; label: string; icon: typeof Activity }> = [
    { id: 'thresholds', label: 'Alert thresholds', icon: BellRing },
    { id: 'telemetry', label: 'Telemetry defaults', icon: Radio },
    { id: 'display', label: 'Waveform display', icon: MonitorCog },
    { id: 'clinician', label: 'Clinician context', icon: CircleUserRound },
  ];

  return (
    <form onSubmit={handleSubmit} className="view-frame view-enter">
      <header className="view-header">
        <div><p className="eyebrow mb-2 text-[var(--color-primary)]">Workstation configuration</p><h1>System settings</h1><p>Manage clinical alert limits, telemetry cadence, and workstation preferences.</p></div>
        <span className="eyebrow">Station WS-ICU-CARDIO-04</span>
      </header>

      {saved && <div className="mb-5 flex items-center gap-2 rounded-md border border-emerald-300 bg-emerald-50 px-4 py-3 text-xs font-bold text-emerald-900" role="status"><Check size={16} /> Configuration saved and synchronized.</div>}
      {error && <div className="mb-5 rounded-md border border-red-300 bg-red-50 px-4 py-3 text-xs font-bold text-red-900" role="alert">{error}</div>}

      <div className="grid grid-cols-[260px_minmax(0,1fr)] gap-7 max-lg:grid-cols-1">
        <nav className="space-y-1" aria-label="Settings sections">
          {sections.map((section) => {
            const Icon = section.icon;
            const selected = activeSection === section.id;
            return (
              <button key={section.id} type="button" onClick={() => setActiveSection(section.id)} className={`relative flex min-h-[52px] w-full items-center gap-3 rounded-md px-4 text-left text-sm transition-colors ${selected ? 'bg-[var(--color-surface-container-high)] font-bold text-[var(--color-primary)]' : 'text-[var(--color-on-surface-variant)] hover:bg-[var(--color-surface-container-low)]'}`}>
                <Icon size={19} /> {section.label}
                {selected && <span className="absolute bottom-0 right-0 top-0 w-1 bg-[var(--color-primary)]" />}
              </button>
            );
          })}
        </nav>

        <div className="space-y-5">
          {activeSection === 'thresholds' && (
            <section className="clinical-panel bg-[var(--color-surface)] p-6">
              <div className="border-b border-[var(--color-outline-variant)] pb-4"><h2 className="text-lg font-bold">Clinical alert thresholds</h2><p className="mt-1 text-sm text-[var(--color-on-surface-variant)]">Alerts are evaluated by the workstation against incoming vitals.</p></div>
              <div className="mt-5 space-y-6">
                <fieldset><legend className="text-sm font-bold">Heart rate</legend><p className="mt-1 text-xs text-[var(--color-on-surface-variant)]">Trigger bradycardia or tachycardia alerts outside this range.</p><div className="mt-3 grid grid-cols-2 gap-4"><label className="text-xs font-bold">Low threshold<input type="number" min={20} max={220} value={form.hrLowThreshold} onChange={(e) => setForm({ ...form, hrLowThreshold: Number(e.target.value) })} className="form-field font-mono" /></label><label className="text-xs font-bold">High threshold<input type="number" min={30} max={250} value={form.hrHighThreshold} onChange={(e) => setForm({ ...form, hrHighThreshold: Number(e.target.value) })} className="form-field font-mono" /></label></div></fieldset>
                <fieldset><legend className="text-sm font-bold">Respiratory rate</legend><p className="mt-1 text-xs text-[var(--color-on-surface-variant)]">Allowed breaths per minute before escalation.</p><div className="mt-3 grid grid-cols-2 gap-4"><label className="text-xs font-bold">Low threshold<input type="number" min={4} max={40} value={form.rrLowThreshold} onChange={(e) => setForm({ ...form, rrLowThreshold: Number(e.target.value) })} className="form-field font-mono" /></label><label className="text-xs font-bold">High threshold<input type="number" min={5} max={60} value={form.rrHighThreshold} onChange={(e) => setForm({ ...form, rrHighThreshold: Number(e.target.value) })} className="form-field font-mono" /></label></div></fieldset>
                <label className="block text-sm font-bold">SpO2 low threshold<p className="mt-1 text-xs font-normal text-[var(--color-on-surface-variant)]">High-priority alert when oxygen saturation falls below this value.</p><div className="mt-3 flex items-center gap-3"><input type="range" min={70} max={100} value={form.spo2LowThreshold} onChange={(e) => setForm({ ...form, spo2LowThreshold: Number(e.target.value) })} className="w-full accent-[var(--color-primary-container)]" /><output className="min-w-[64px] rounded border border-[var(--color-outline-variant)] bg-white px-2 py-1 text-center font-mono text-sm">{form.spo2LowThreshold}%</output></div></label>
              </div>
            </section>
          )}

          {activeSection === 'telemetry' && (
            <section className="clinical-panel bg-[var(--color-surface)] p-6">
              <div className="border-b border-[var(--color-outline-variant)] pb-4"><h2 className="text-lg font-bold">Telemetry defaults</h2><p className="mt-1 text-sm text-[var(--color-on-surface-variant)]">Configure workstation synchronization and alert behavior.</p></div>
              <div className="mt-6 space-y-7">
                <label className="block text-sm font-bold">BLE notification interval<p className="mt-1 text-xs font-normal text-[var(--color-on-surface-variant)]">Cadence used for the periodic telemetry service.</p><div className="mt-4 flex items-center gap-4"><input type="range" min={500} max={2000} step={500} value={form.bleSyncIntervalMs} onChange={(e) => setForm({ ...form, bleSyncIntervalMs: Number(e.target.value) })} className="w-full accent-[var(--color-primary-container)]" /><output className="min-w-[82px] font-mono text-sm font-bold text-[var(--color-primary)]">{form.bleSyncIntervalMs} ms</output></div><div className="mt-1 flex justify-between font-mono text-[10px] text-[var(--color-on-surface-variant)]"><span>500 ms</span><span>2000 ms</span></div></label>
                <div className="flex items-center justify-between gap-5 border-y border-[var(--color-outline-variant)] py-5"><div><p className="text-sm font-bold">Audible clinical alerts</p><p className="mt-1 text-xs text-[var(--color-on-surface-variant)]">Play the workstation chime for new rhythm events.</p></div><button type="button" role="switch" aria-checked={form.audioAlertsEnabled} onClick={() => setForm({ ...form, audioAlertsEnabled: !form.audioAlertsEnabled })} className={`relative h-7 w-12 rounded-full border transition-colors ${form.audioAlertsEnabled ? 'border-[var(--color-primary-container)] bg-[var(--color-primary-container)]' : 'border-[var(--color-outline)] bg-white'}`}><span className={`absolute left-1 top-1 h-5 w-5 rounded-full bg-white shadow transition-transform ${form.audioAlertsEnabled ? 'translate-x-5' : 'translate-x-0'}`} /></button></div>
                <div className="rounded-md border border-[var(--color-primary-fixed-dim)] bg-[#eefaf7] p-4"><div className="flex items-center gap-2 text-sm font-bold text-[var(--color-primary)]"><SlidersHorizontal size={17} /> Gateway-managed link policy</div><p className="mt-2 text-xs leading-5 text-[var(--color-on-surface-variant)]">Pairing, encryption, and reconnection policy remain controlled by the Raspberry Pi gateway and EFR32 firmware.</p></div>
              </div>
            </section>
          )}

          {activeSection === 'display' && (
            <section className="clinical-panel bg-[var(--color-surface)] p-6">
              <div className="border-b border-[var(--color-outline-variant)] pb-4"><h2 className="text-lg font-bold">Waveform display</h2><p className="mt-1 text-sm text-[var(--color-on-surface-variant)]">Choose the information density used across clinical views.</p></div>
              <fieldset className="mt-6"><legend className="text-sm font-bold">Display density</legend><div className="mt-4 grid grid-cols-3 overflow-hidden rounded-md border border-[var(--color-outline-variant)] max-sm:grid-cols-1">{(['dense', 'standard', 'relaxed'] as const).map((density) => <button key={density} type="button" onClick={() => setForm({ ...form, gridDensity: density })} className={`min-h-[74px] border-r border-[var(--color-outline-variant)] px-4 text-left last:border-r-0 max-sm:border-b max-sm:border-r-0 ${form.gridDensity === density ? 'bg-[var(--color-surface-container-high)] text-[var(--color-primary)]' : 'bg-white'}`}><span className="block text-sm font-bold capitalize">{density}</span><span className="mt-1 block text-[11px] text-[var(--color-on-surface-variant)]">{density === 'dense' ? 'Maximum telemetry at once' : density === 'standard' ? 'Balanced for routine use' : 'Larger spacing and controls'}</span></button>)}</div></fieldset>
              <div className="waveform-grid mt-7 h-36 overflow-hidden rounded-md border border-[var(--color-outline-variant)] bg-white"><svg viewBox="0 0 800 140" className="h-full w-full" aria-hidden="true"><path d="M0 72h95l13-8 11 15 14-59 12 101 12-49h116l12-8 10 15 14-59 12 101 13-49h117l13-8 10 15 14-59 12 101 13-49h116" fill="none" stroke="#2859c5" strokeWidth="2" /></svg></div>
            </section>
          )}

          {activeSection === 'clinician' && (
            <section className="clinical-panel bg-[var(--color-surface)] p-6">
              <div className="border-b border-[var(--color-outline-variant)] pb-4"><h2 className="text-lg font-bold">Clinician context</h2><p className="mt-1 text-sm text-[var(--color-on-surface-variant)]">Used for audit records and clinical action attribution.</p></div>
              <div className="mt-6 grid grid-cols-2 gap-5 max-sm:grid-cols-1"><label className="text-xs font-bold">Lead clinician<input value={form.attendingDoctor} onChange={(e) => setForm({ ...form, attendingDoctor: e.target.value })} className="form-field" /></label><label className="text-xs font-bold">Workstation ID<input disabled value="WS-ICU-CARDIO-04" className="form-field bg-[var(--color-surface-container-low)] font-mono" /></label></div>
              <div className="mt-7 border-t border-[var(--color-outline-variant)] pt-5"><p className="text-sm font-bold">Audit attribution</p><p className="mt-2 max-w-2xl text-xs leading-5 text-[var(--color-on-surface-variant)]">ECG exports, physician pages, and settings changes are associated with the active clinician identity and monitoring session.</p></div>
            </section>
          )}

          <div className="flex items-center justify-end gap-3 border-t border-[var(--color-outline-variant)] pt-5">
            <button type="button" className="button-secondary" onClick={() => { setForm(settings); setSaved(false); setError(null); }}>Discard changes</button>
            <button type="submit" disabled={saving} className="button-primary min-w-[160px]">{saving ? <LoaderCircle size={16} className="animate-spin" /> : <Save size={16} />} {saving ? 'Saving...' : 'Save configuration'}</button>
          </div>
        </div>
      </div>
    </form>
  );
};
