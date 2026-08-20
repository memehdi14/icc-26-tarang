'use client';

import React, { useEffect, useState } from 'react';
import {
  AlertTriangle,
  Bell,
  BellRing,
  Check,
  CheckCircle2,
  CircleUserRound,
  Eye,
  HeartPulse,
  LoaderCircle,
  Monitor,
  Radio,
  Save,
  Sliders,
  Volume2,
  VolumeX,
  Zap,
} from 'lucide-react';
import { SystemSettings } from '../types/telemetry';

interface SettingsViewProps {
  settings: SystemSettings;
  onSaveSettings: (newSettings: SystemSettings) => Promise<void>;
}

type SettingsSection = 'thresholds' | 'audio' | 'display' | 'clinician';

// Play authentic ISO 60601-1-8 Medical Alarm Sound using Web Audio API
function playMedicalChime(volume: number = 0.6) {
  try {
    const AudioContextClass = window.AudioContext || (window as unknown as { webkitAudioContext: typeof AudioContext }).webkitAudioContext;
    if (!AudioContextClass) return;
    const ctx = new AudioContextClass();

    const notes = [523.25, 659.25, 783.99]; // C5, E5, G5 (Standard Medical Tri-Tone Chime)
    const startTime = ctx.currentTime + 0.05;

    notes.forEach((freq, index) => {
      const osc = ctx.createOscillator();
      const gain = ctx.createGain();

      osc.type = 'sine';
      osc.frequency.setValueAtTime(freq, startTime + index * 0.14);

      gain.gain.setValueAtTime(0, startTime + index * 0.14);
      gain.gain.linearRampToValueAtTime(volume * 0.4, startTime + index * 0.14 + 0.02);
      gain.gain.exponentialRampToValueAtTime(0.001, startTime + index * 0.14 + 0.35);

      osc.connect(gain);
      gain.connect(ctx.destination);

      osc.start(startTime + index * 0.14);
      osc.stop(startTime + index * 0.14 + 0.36);
    });
  } catch {
    // AudioContext blocked by browser autoplay policy until user gesture
  }
}

export const SettingsView: React.FC<SettingsViewProps> = ({ settings, onSaveSettings }) => {
  const [form, setForm] = useState<SystemSettings>(settings);
  const [activeSection, setActiveSection] = useState<SettingsSection>('thresholds');
  const [saved, setSaved] = useState(false);
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState<string | null>(null);

  // Live Display Preview Settings
  const [gain, setGain] = useState<'0.5x' | '1.0x' | '2.0x' | 'auto'>('auto');
  const [sweepSpeed, setSweepSpeed] = useState<'12.5' | '25' | '50'>('25');
  const [alertVolume, setAlertVolume] = useState<number>(75);
  const [soundTested, setSoundTested] = useState(false);

  useEffect(() => setForm(settings), [settings]);

  const handleTestChime = () => {
    playMedicalChime(alertVolume / 100);
    setSoundTested(true);
    window.setTimeout(() => setSoundTested(false), 2000);
  };

  const handlePresetApply = (preset: 'adult' | 'pediatric' | 'critical') => {
    if (preset === 'adult') {
      setForm((prev) => ({ ...prev, hrLowThreshold: 50, hrHighThreshold: 120, spo2LowThreshold: 92, rrLowThreshold: 10, rrHighThreshold: 22 }));
    } else if (preset === 'pediatric') {
      setForm((prev) => ({ ...prev, hrLowThreshold: 70, hrHighThreshold: 150, spo2LowThreshold: 94, rrLowThreshold: 18, rrHighThreshold: 35 }));
    } else if (preset === 'critical') {
      setForm((prev) => ({ ...prev, hrLowThreshold: 55, hrHighThreshold: 110, spo2LowThreshold: 95, rrLowThreshold: 12, rrHighThreshold: 20 }));
    }
  };

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

  const sections: Array<{ id: SettingsSection; label: string; icon: typeof HeartPulse; desc: string }> = [
    { id: 'thresholds', label: 'Alert thresholds', icon: HeartPulse, desc: 'Vitals trigger limits' },
    { id: 'audio', label: 'Alarms & audio', icon: BellRing, desc: 'Chime volume & sound test' },
    { id: 'display', label: 'Waveform & sweep', icon: Monitor, desc: 'ECG gain & sweep speed' },
    { id: 'clinician', label: 'Clinician context', icon: CircleUserRound, desc: 'Attending physician ID' },
  ];

  return (
    <form onSubmit={handleSubmit} className="view-frame view-enter">
      <header className="view-header !pb-3">
        <div>
          <span className="text-xs font-semibold text-[var(--ink)] flex items-center gap-1">
            <span className="text-[var(--accent)] text-[10px]">✦</span> Workstation configuration
          </span>
          <h1 className="text-2xl font-bold text-[var(--ink)]">System settings</h1>
          <p className="text-xs text-[var(--ink-soft)] mt-0.5">Live clinical alert limits, audio alarm calibration, and ECG display preferences.</p>
        </div>
        <div className="text-right max-sm:text-left">
          <span className="font-mono text-xs text-[var(--muted)] border border-[var(--line)] bg-white px-2.5 py-1 rounded">
            STATION WS-ICU-CARDIO-04
          </span>
        </div>
      </header>

      {saved && (
        <div className="mb-4 flex items-center gap-2 rounded-lg border border-emerald-300 bg-emerald-50 px-4 py-2.5 text-xs font-bold text-emerald-900 shadow-xs" role="status">
          <Check size={16} className="text-emerald-700" /> Configuration saved and applied to workstation.
        </div>
      )}
      {error && (
        <div className="mb-4 rounded-lg border border-red-300 bg-red-50 px-4 py-2.5 text-xs font-bold text-red-900" role="alert">
          {error}
        </div>
      )}

      <div className="grid grid-cols-[240px_minmax(0,1fr)] gap-6 max-lg:grid-cols-1">
        {/* Left Navigation */}
        <nav className="space-y-1.5" aria-label="Settings sections">
          {sections.map((section) => {
            const Icon = section.icon;
            const selected = activeSection === section.id;
            return (
              <button
                key={section.id}
                type="button"
                onClick={() => setActiveSection(section.id)}
                className={`relative flex min-h-[50px] w-full items-center gap-3 rounded-lg px-3.5 text-left text-xs transition-all ${
                  selected
                    ? 'bg-white font-bold text-[var(--ink)] shadow-xs border border-[var(--line)]'
                    : 'text-[var(--muted)] hover:bg-[var(--paper-2)] hover:text-[var(--ink)]'
                }`}
              >
                <Icon size={17} className={selected ? 'text-[var(--accent)]' : 'text-[var(--muted)]'} />
                <div className="min-w-0">
                  <p className="truncate font-semibold">{section.label}</p>
                  <p className="text-[10px] text-[var(--muted)] font-normal truncate">{section.desc}</p>
                </div>
                {selected && <span className="absolute left-0 top-2 bottom-2 w-1 rounded-r bg-[var(--accent)]" />}
              </button>
            );
          })}
        </nav>

        {/* Section Panels */}
        <div className="space-y-4">
          {/* 1. Alert Thresholds */}
          {activeSection === 'thresholds' && (
            <section className="rounded-lg border border-[var(--line)] bg-white p-5 shadow-xs space-y-5">
              <div className="flex flex-wrap items-center justify-between gap-3 border-b border-[var(--line)] pb-3">
                <div>
                  <h2 className="text-sm font-bold text-[var(--ink)] uppercase tracking-wider">Clinical alert limits</h2>
                  <p className="text-xs text-[var(--muted)] mt-0.5">Triggers visual alerts when measured vitals cross boundaries.</p>
                </div>
                {/* Fast Presets */}
                <div className="flex items-center gap-1.5">
                  <span className="text-[10px] font-semibold text-[var(--muted)] uppercase mr-1">Presets:</span>
                  <button type="button" onClick={() => handlePresetApply('adult')} className="discovery-pill-secondary !py-0.5 !px-2.5 !text-[10px]">Adult</button>
                  <button type="button" onClick={() => handlePresetApply('pediatric')} className="discovery-pill-secondary !py-0.5 !px-2.5 !text-[10px]">Pediatric</button>
                  <button type="button" onClick={() => handlePresetApply('critical')} className="discovery-pill-secondary !py-0.5 !px-2.5 !text-[10px]">ICU Critical</button>
                </div>
              </div>

              {/* Heart Rate Thresholds */}
              <div className="space-y-2">
                <div className="flex items-center justify-between">
                  <label className="text-xs font-bold text-[var(--ink)] flex items-center gap-1.5">
                    <HeartPulse size={14} className="text-[var(--cardiac-rose)]" /> Heart rate trigger range (BPM)
                  </label>
                  <span className="font-mono text-xs font-bold text-[var(--ink)]">
                    {form.hrLowThreshold} - {form.hrHighThreshold} bpm
                  </span>
                </div>
                <div className="grid grid-cols-2 gap-3">
                  <div className="p-3 rounded border border-[var(--line-soft)] bg-[var(--paper-2)]">
                    <span className="text-[10px] uppercase font-bold text-[var(--muted)]">Bradycardia Low Limit</span>
                    <input
                      type="number"
                      min={30}
                      max={100}
                      value={form.hrLowThreshold}
                      onChange={(e) => setForm({ ...form, hrLowThreshold: Number(e.target.value) })}
                      className="form-field !mt-1 font-mono font-bold text-sm !bg-white"
                    />
                  </div>
                  <div className="p-3 rounded border border-[var(--line-soft)] bg-[var(--paper-2)]">
                    <span className="text-[10px] uppercase font-bold text-[var(--muted)]">Tachycardia High Limit</span>
                    <input
                      type="number"
                      min={100}
                      max={220}
                      value={form.hrHighThreshold}
                      onChange={(e) => setForm({ ...form, hrHighThreshold: Number(e.target.value) })}
                      className="form-field !mt-1 font-mono font-bold text-sm !bg-white"
                    />
                  </div>
                </div>
              </div>

              {/* SpO2 Low Threshold */}
              <div className="space-y-2 border-t border-[var(--line-soft)] pt-4">
                <div className="flex items-center justify-between">
                  <label className="text-xs font-bold text-[var(--ink)] flex items-center gap-1.5">
                    <Zap size={14} className="text-[var(--deep-ocean)]" /> Blood oxygen (SpO₂) critical floor
                  </label>
                  <span className="font-mono text-xs font-bold text-[var(--cardiac-rose)]">
                    &lt; {form.spo2LowThreshold}% Alert
                  </span>
                </div>
                <div className="flex items-center gap-4">
                  <input
                    type="range"
                    min={80}
                    max={98}
                    step={1}
                    value={form.spo2LowThreshold}
                    onChange={(e) => setForm({ ...form, spo2LowThreshold: Number(e.target.value) })}
                    className="w-full accent-[var(--cardiac-rose)] cursor-pointer"
                  />
                  <output className="min-w-[70px] rounded border border-[var(--line)] bg-[var(--paper-2)] px-2.5 py-1 text-center font-mono text-xs font-bold">
                    {form.spo2LowThreshold}%
                  </output>
                </div>
              </div>

              {/* Respiratory Rate */}
              <div className="space-y-2 border-t border-[var(--line-soft)] pt-4">
                <div className="flex items-center justify-between">
                  <label className="text-xs font-bold text-[var(--ink)] flex items-center gap-1.5">
                    <Activity size={14} className="text-[var(--clinical-teal)]" /> Respiratory rate range (BrPM)
                  </label>
                  <span className="font-mono text-xs font-bold text-[var(--ink)]">
                    {form.rrLowThreshold} - {form.rrHighThreshold} brpm
                  </span>
                </div>
                <div className="grid grid-cols-2 gap-3">
                  <input
                    type="number"
                    min={6}
                    max={20}
                    value={form.rrLowThreshold}
                    onChange={(e) => setForm({ ...form, rrLowThreshold: Number(e.target.value) })}
                    className="form-field font-mono text-xs"
                    placeholder="Min brpm"
                  />
                  <input
                    type="number"
                    min={18}
                    max={45}
                    value={form.rrHighThreshold}
                    onChange={(e) => setForm({ ...form, rrHighThreshold: Number(e.target.value) })}
                    className="form-field font-mono text-xs"
                    placeholder="Max brpm"
                  />
                </div>
              </div>
            </section>
          )}

          {/* 2. Alarms & Audio */}
          {activeSection === 'audio' && (
            <section className="rounded-lg border border-[var(--line)] bg-white p-5 shadow-xs space-y-5">
              <div className="border-b border-[var(--line)] pb-3">
                <h2 className="text-sm font-bold text-[var(--ink)] uppercase tracking-wider">Audio alarms & chime test</h2>
                <p className="text-xs text-[var(--muted)] mt-0.5">Configure audible chime for critical arrhythmia events.</p>
              </div>

              <div className="flex items-center justify-between gap-4 p-3 rounded-lg border border-[var(--line-soft)] bg-[var(--paper-2)]">
                <div>
                  <p className="text-xs font-bold text-[var(--ink)]">Audible clinical alarm chime</p>
                  <p className="text-[11px] text-[var(--muted)] mt-0.5">Plays standard ISO 60601-1-8 medical chime upon arrhythmia detection.</p>
                </div>
                <button
                  type="button"
                  role="switch"
                  aria-checked={form.audioAlertsEnabled}
                  onClick={() => setForm({ ...form, audioAlertsEnabled: !form.audioAlertsEnabled })}
                  className={`relative h-6 w-11 rounded-full transition-colors ${
                    form.audioAlertsEnabled ? 'bg-[var(--clinical-teal)]' : 'bg-zinc-300'
                  }`}
                >
                  <span
                    className={`absolute top-0.5 left-0.5 h-5 w-5 rounded-full bg-white shadow transition-transform ${
                      form.audioAlertsEnabled ? 'translate-x-5' : 'translate-x-0'
                    }`}
                  />
                </button>
              </div>

              {/* Volume Slider & Test Button */}
              <div className="space-y-3 border-t border-[var(--line-soft)] pt-4">
                <div className="flex items-center justify-between">
                  <label className="text-xs font-bold text-[var(--ink)] flex items-center gap-1.5">
                    {alertVolume === 0 ? <VolumeX size={15} /> : <Volume2 size={15} />} Alarm volume
                  </label>
                  <span className="font-mono text-xs font-bold text-[var(--ink)]">{alertVolume}%</span>
                </div>
                <input
                  type="range"
                  min={0}
                  max={100}
                  value={alertVolume}
                  onChange={(e) => setAlertVolume(Number(e.target.value))}
                  className="w-full accent-[var(--clinical-teal)] cursor-pointer"
                />

                <div className="pt-2">
                  <button
                    type="button"
                    onClick={handleTestChime}
                    className="discovery-pill-secondary !py-2 !px-4 !text-xs flex items-center gap-2 border-[var(--clinical-teal)] text-[var(--clinical-teal)]"
                  >
                    <Bell size={13} />
                    <span>{soundTested ? 'Playing medical chime...' : 'Test alert chime (ISO 60601)'}</span>
                  </button>
                </div>
              </div>
            </section>
          )}

          {/* 3. Waveform Display & Sweep Speed */}
          {activeSection === 'display' && (
            <section className="rounded-lg border border-[var(--line)] bg-white p-5 shadow-xs space-y-5">
              <div className="border-b border-[var(--line)] pb-3">
                <h2 className="text-sm font-bold text-[var(--ink)] uppercase tracking-wider">ECG waveform calibration</h2>
                <p className="text-xs text-[var(--muted)] mt-0.5">Control gain scale, paper sweep speed, and canvas display density.</p>
              </div>

              {/* Sweep Speed Selection */}
              <div>
                <label className="text-xs font-bold text-[var(--ink)] block mb-2">Paper sweep speed (standard telemetry)</label>
                <div className="grid grid-cols-3 gap-2.5">
                  {(['12.5', '25', '50'] as const).map((spd) => (
                    <button
                      key={spd}
                      type="button"
                      onClick={() => setSweepSpeed(spd)}
                      className={`p-3 rounded-lg border text-left transition-all ${
                        sweepSpeed === spd
                          ? 'border-[var(--deep-ocean)] bg-blue-50 text-[var(--deep-ocean)] font-bold shadow-xs'
                          : 'border-[var(--line)] bg-white text-[var(--ink)] hover:bg-[var(--paper-2)]'
                      }`}
                    >
                      <p className="text-sm font-mono font-bold">{spd} mm/s</p>
                      <p className="text-[10px] text-[var(--muted)] mt-0.5">
                        {spd === '12.5' ? 'Compressed view' : spd === '25' ? 'Standard hospital speed' : 'Expanded high-res'}
                      </p>
                    </button>
                  ))}
                </div>
              </div>

              {/* Gain Calibration */}
              <div className="border-t border-[var(--line-soft)] pt-4">
                <label className="text-xs font-bold text-[var(--ink)] block mb-2">ECG lead gain / amplitude scaling</label>
                <div className="grid grid-cols-4 gap-2">
                  {(['auto', '0.5x', '1.0x', '2.0x'] as const).map((g) => (
                    <button
                      key={g}
                      type="button"
                      onClick={() => setGain(g)}
                      className={`py-2 px-3 rounded border text-center text-xs font-mono font-bold transition-all ${
                        gain === g
                          ? 'border-[var(--clinical-teal)] bg-emerald-50 text-[var(--clinical-teal)]'
                          : 'border-[var(--line)] bg-white text-[var(--muted)] hover:text-[var(--ink)]'
                      }`}
                    >
                      {g === 'auto' ? 'Auto-scale' : `${g} gain`}
                    </button>
                  ))}
                </div>
              </div>

              {/* Display Density */}
              <div className="border-t border-[var(--line-soft)] pt-4">
                <label className="text-xs font-bold text-[var(--ink)] block mb-2">Workstation layout density</label>
                <div className="grid grid-cols-3 gap-2">
                  {(['dense', 'standard', 'relaxed'] as const).map((d) => (
                    <button
                      key={d}
                      type="button"
                      onClick={() => setForm({ ...form, gridDensity: d })}
                      className={`p-2.5 rounded border text-left text-xs transition-all ${
                        form.gridDensity === d
                          ? 'border-[var(--accent)] bg-[#8e5db012] text-[var(--ink)] font-bold'
                          : 'border-[var(--line)] bg-white text-[var(--muted)] hover:bg-[var(--paper-2)]'
                      }`}
                    >
                      <span className="capitalize font-semibold block">{d}</span>
                      <span className="text-[10px] text-[var(--muted)] block mt-0.5">
                        {d === 'dense' ? 'Compact vitals' : d === 'standard' ? 'Balanced' : 'Spacious'}
                      </span>
                    </button>
                  ))}
                </div>
              </div>
            </section>
          )}

          {/* 4. Clinician Context */}
          {activeSection === 'clinician' && (
            <section className="rounded-lg border border-[var(--line)] bg-white p-5 shadow-xs space-y-5">
              <div className="border-b border-[var(--line)] pb-3">
                <h2 className="text-sm font-bold text-[var(--ink)] uppercase tracking-wider">Clinician & station identity</h2>
                <p className="text-xs text-[var(--muted)] mt-0.5">Assigned duty physician for ECG PDF export signing and clinical audit log.</p>
              </div>

              <div className="grid grid-cols-2 gap-4 max-sm:grid-cols-1">
                <div>
                  <label className="text-xs font-bold text-[var(--ink)] block mb-1">Attending duty physician</label>
                  <input
                    value={form.attendingDoctor}
                    onChange={(e) => setForm({ ...form, attendingDoctor: e.target.value })}
                    className="form-field !mt-0 font-medium text-xs !bg-white"
                    placeholder="e.g. Dr. Sandeep Mehta"
                  />
                </div>
                <div>
                  <label className="text-xs font-bold text-[var(--muted)] block mb-1">Assigned workstation ID</label>
                  <input
                    disabled
                    value="WS-ICU-CARDIO-04"
                    className="form-field !mt-0 font-mono text-xs bg-[var(--paper-2)] text-[var(--muted)]"
                  />
                </div>
              </div>

              <div className="rounded-lg border border-[var(--line-soft)] bg-[var(--paper-2)] p-3.5 text-xs text-[var(--muted)] leading-relaxed">
                <p className="font-semibold text-[var(--ink)] flex items-center gap-1.5 mb-1">
                  <CheckCircle2 size={14} className="text-[var(--clinical-teal)]" /> Audit trail attribution
                </p>
                Changing the attending physician immediately signs all exported event ECG PDFs and attaches this identity to ongoing monitoring sessions.
              </div>
            </section>
          )}

          {/* Submit / Reset Actions */}
          <div className="flex items-center justify-end gap-3 border-t border-[var(--line)] pt-4">
            <button
              type="button"
              className="discovery-pill-secondary !py-2 !px-4 !text-xs"
              onClick={() => {
                setForm(settings);
                setSaved(false);
                setError(null);
              }}
            >
              Reset to defaults
            </button>
            <button
              type="submit"
              disabled={saving}
              className="discovery-pill-primary !py-2 !px-5 !text-xs min-w-[140px]"
            >
              {saving ? <LoaderCircle size={14} className="animate-spin" /> : <Save size={14} />}
              <span>{saving ? 'Saving...' : 'Save configuration'}</span>
            </button>
          </div>
        </div>
      </div>
    </form>
  );
};
