'use client';

import React, { useMemo, useState } from 'react';
import {
  Activity,
  AlertCircle,
  ArrowRight,
  Bed,
  Bluetooth,
  CircleDot,
  Database,
  Plus,
  RefreshCw,
  Search,
  ShieldCheck,
  UserRound,
  UsersRound,
  X,
} from 'lucide-react';
import { DeviceRecord, MonitoringSession, PatientCreateInput, PatientInfo } from '../types/telemetry';

interface PatientOnboardingProps {
  patients: PatientInfo[];
  devices: DeviceRecord[];
  sessions: MonitoringSession[];
  loading: boolean;
  error?: string | null;
  onRetry: () => void;
  onCreatePatient: (patient: PatientCreateInput) => Promise<void>;
  onStartMonitoring: (patient: PatientInfo, deviceId?: string) => Promise<void>;
}

const EMPTY_FORM: PatientCreateInput = {
  name: '',
  mrn: '',
  age: 0,
  gender: 'Other',
  bed: '',
  admit_date: new Date().toISOString().slice(0, 10),
  attending_physician: '',
  blood_type: 'Unknown',
  allergies: [],
  medical_history: [],
};

export const PatientOnboarding: React.FC<PatientOnboardingProps> = ({
  patients,
  devices,
  sessions,
  loading,
  error,
  onRetry,
  onCreatePatient,
  onStartMonitoring,
}) => {
  const [query, setQuery] = useState('');
  const [showCreate, setShowCreate] = useState(false);
  const [form, setForm] = useState(EMPTY_FORM);
  const [allergies, setAllergies] = useState('');
  const [history, setHistory] = useState('');
  const [selectedDevices, setSelectedDevices] = useState<Record<string, string>>({});
  const [busyMrn, setBusyMrn] = useState<string | null>(null);
  const [saving, setSaving] = useState(false);
  const [actionError, setActionError] = useState<string | null>(null);

  const filteredPatients = useMemo(() => {
    const needle = query.trim().toLowerCase();
    if (!needle) return patients;
    return patients.filter((patient) =>
      [patient.name, patient.id, patient.bed, patient.attendingPhysician]
        .some((value) => value.toLowerCase().includes(needle))
    );
  }, [patients, query]);

  const availableDevices = devices.filter((device) => device.status !== 'in_use');
  const activeSessionCount = sessions.filter((session) => session.status === 'active').length;

  const startPatient = async (patient: PatientInfo) => {
    const activeSession = sessions.find(
      (session) => session.status === 'active' && session.patient_id === patient.dbId
    );
    const assignedDevice = devices.find((device) => device.assigned_patient_id === patient.dbId);
    const deviceId = activeSession?.device_id
      || selectedDevices[patient.id]
      || assignedDevice?.device_id
      || availableDevices[0]?.device_id;
    setActionError(null);
    setBusyMrn(patient.id);
    try {
      await onStartMonitoring(patient, deviceId || undefined);
    } catch (startError) {
      setActionError(startError instanceof Error ? startError.message : 'Unable to start monitoring');
    } finally {
      setBusyMrn(null);
    }
  };

  const submitPatient = async (event: React.FormEvent) => {
    event.preventDefault();
    setSaving(true);
    setActionError(null);
    try {
      await onCreatePatient({
        ...form,
        allergies: allergies.split(',').map((item) => item.trim()).filter(Boolean),
        medical_history: history.split('\n').map((item) => item.trim()).filter(Boolean),
      });
      setForm(EMPTY_FORM);
      setAllergies('');
      setHistory('');
      setShowCreate(false);
    } catch (createError) {
      setActionError(createError instanceof Error ? createError.message : 'Unable to add patient');
    } finally {
      setSaving(false);
    }
  };

  if (loading) {
    return (
      <main className="min-h-screen bg-white">
        <header className="flex h-[72px] items-center border-b border-[var(--color-outline-variant)] px-7">
          <img src="/tarang_logo.png" alt="" className="mr-3 h-8 w-8 object-contain" />
          <span className="text-xl font-extrabold text-[var(--color-primary)]">Tarang Clinical</span>
        </header>
        <section className="mx-auto grid min-h-[calc(100vh-72px)] max-w-5xl grid-cols-[1fr_320px] items-center gap-16 px-8 max-md:grid-cols-1 max-md:gap-8">
          <div className="view-enter">
            <p className="eyebrow mb-3 text-[var(--color-primary)]">Clinical workstation</p>
            <h1 className="max-w-xl text-4xl font-extrabold leading-tight text-[var(--color-on-surface)] max-md:text-3xl">
              Preparing the patient worklist
            </h1>
            <p className="mt-4 max-w-lg text-sm text-[var(--color-on-surface-variant)]">
              Verifying the clinical database, patient records, and monitoring services.
            </p>
            <div className="waveform-grid relative mt-9 h-28 overflow-hidden rounded-lg border border-[var(--color-outline-variant)]">
              <div className="absolute inset-y-0 left-0 w-24 animate-pulse bg-[var(--color-primary-fixed)]/30" />
              <svg viewBox="0 0 720 112" className="h-full w-full" aria-hidden="true">
                <path d="M0 58H92l12-8 9 18 12-62 10 99 11-47h96l10-8 8 16 13-58 10 94 12-44h101l10-9 9 18 12-62 10 99 11-47h98l11-8 8 16 13-57 10 92 12-43h86" fill="none" stroke="#008378" strokeWidth="2" />
              </svg>
            </div>
          </div>
          <div className="border-l border-[var(--color-outline-variant)] pl-8 max-md:border-l-0 max-md:border-t max-md:pt-8">
            {[
              [Database, 'Clinical database', 'Connecting'],
              [ShieldCheck, 'Security context', 'Verified'],
              [UsersRound, 'Patient index', 'Loading'],
            ].map(([Icon, label, value], index) => {
              const StageIcon = Icon as typeof Database;
              return (
                <div key={label as string} className="flex items-center gap-3 border-b border-[var(--color-surface-container-high)] py-4 last:border-0">
                  <StageIcon size={18} className="text-[var(--color-primary)]" />
                  <div className="flex-1"><p className="text-sm font-semibold">{label as string}</p><p className="eyebrow mt-0.5">{value as string}</p></div>
                  <span className="status-dot pulse-dot text-[var(--color-primary-container)]" style={{ animationDelay: `${index * 180}ms` }} />
                </div>
              );
            })}
          </div>
        </section>
      </main>
    );
  }

  return (
    <main className="min-h-screen bg-white">
      <header className="sticky top-0 z-30 border-b border-[var(--color-outline-variant)] bg-white/95">
        <div className="mx-auto flex h-[72px] max-w-[1440px] items-center justify-between px-7">
          <div className="flex items-center gap-3">
            <img src="/tarang_logo.png" alt="" className="h-8 w-8 object-contain" />
            <div>
              <div className="text-xl font-extrabold text-[var(--color-primary)]">Tarang Clinical</div>
              <div className="eyebrow">Patient operations</div>
            </div>
          </div>
          <button onClick={() => setShowCreate(true)} className="button-primary">
            <Plus size={17} /> <span className="max-sm:hidden">Add patient</span>
          </button>
        </div>
      </header>

      <div className="mx-auto max-w-[1440px] px-7 py-8 max-sm:px-4">
        <div className="view-header view-enter">
          <div>
            <p className="eyebrow mb-2 text-[var(--color-primary)]">Critical care worklist</p>
            <h1>Select a monitoring context</h1>
            <p>Choose a patient and assign an available Tarang device before starting telemetry.</p>
          </div>
          <div className="flex divide-x divide-[var(--color-outline-variant)] border border-[var(--color-outline-variant)] bg-[var(--color-surface)]">
            <div className="px-5 py-3"><p className="eyebrow">Patients</p><p className="font-mono text-xl font-bold">{patients.length}</p></div>
            <div className="px-5 py-3"><p className="eyebrow">Active</p><p className="font-mono text-xl font-bold text-[var(--color-success)]">{activeSessionCount}</p></div>
            <div className="px-5 py-3"><p className="eyebrow">Devices ready</p><p className="font-mono text-xl font-bold">{availableDevices.length}</p></div>
          </div>
        </div>

        {(error || actionError) && (
          <div className="mb-5 flex items-center justify-between gap-4 rounded-md border border-red-300 bg-red-50 px-4 py-3 text-sm text-red-900" role="alert">
            <span className="flex items-center gap-2"><AlertCircle size={17} />{actionError || error}</span>
            {error && <button onClick={onRetry} className="icon-button" title="Retry loading"><RefreshCw size={17} /></button>}
          </div>
        )}

        <section className="clinical-panel view-enter overflow-hidden bg-white" style={{ animationDelay: '70ms' }}>
          <div className="flex items-center justify-between gap-4 border-b border-[var(--color-outline-variant)] px-5 py-4 max-sm:flex-col max-sm:items-stretch">
            <div className="flex items-center gap-2 text-sm font-bold"><UsersRound size={18} className="text-[var(--color-primary)]" /> Current admissions</div>
            <label className="relative w-80 max-sm:w-full">
              <Search size={16} className="pointer-events-none absolute left-3 top-3 text-[var(--color-outline)]" />
              <span className="sr-only">Search patients</span>
              <input value={query} onChange={(event) => setQuery(event.target.value)} placeholder="Search name, MRN, bed, or physician" className="form-field !mt-0 !pl-9" />
            </label>
          </div>

          <div className="overflow-x-auto max-md:hidden">
            <table className="w-full min-w-[980px] border-collapse text-left">
              <thead className="bg-[var(--color-surface-container-low)]">
                <tr className="eyebrow">
                  <th className="px-5 py-3 font-semibold">Patient</th>
                  <th className="px-4 py-3 font-semibold">Location</th>
                  <th className="px-4 py-3 font-semibold">Clinical context</th>
                  <th className="px-4 py-3 font-semibold">Monitoring state</th>
                  <th className="px-4 py-3 font-semibold">Tarang device</th>
                  <th className="px-5 py-3 text-right font-semibold">Action</th>
                </tr>
              </thead>
              <tbody className="divide-y divide-[var(--color-surface-container-high)]">
                {filteredPatients.map((patient) => {
                  const activeSession = sessions.find((session) => session.status === 'active' && session.patient_id === patient.dbId);
                  const assignedDevice = devices.find((device) => device.assigned_patient_id === patient.dbId);
                  const selectedDevice = selectedDevices[patient.id] || activeSession?.device_id || assignedDevice?.device_id || availableDevices[0]?.device_id || '';
                  const initials = patient.name.split(/\s+/).map((part) => part[0]).join('').slice(0, 2).toUpperCase();
                  return (
                    <tr key={patient.id} className="transition-colors hover:bg-[var(--color-surface)]">
                      <td className="px-5 py-4">
                        <div className="flex items-center gap-3">
                          <div className="grid h-10 w-10 shrink-0 place-items-center rounded-md bg-[var(--color-surface-container-high)] text-sm font-bold text-[var(--color-primary)]">{initials}</div>
                          <div><p className="font-bold">{patient.name}</p><p className="eyebrow mt-0.5">MRN {patient.id}</p></div>
                        </div>
                      </td>
                      <td className="px-4 py-4"><p className="flex items-center gap-2 text-sm font-semibold"><Bed size={15} /> Bed {patient.bed}</p><p className="eyebrow mt-1">Admitted {patient.admitDate}</p></td>
                      <td className="px-4 py-4"><p className="text-sm">{patient.age} yr / {patient.gender}</p><p className="eyebrow mt-1">{patient.attendingPhysician}</p></td>
                      <td className="px-4 py-4">
                        <span className={`inline-flex items-center gap-2 text-xs font-bold ${activeSession ? 'text-[var(--color-success)]' : 'text-[var(--color-on-surface-variant)]'}`}>
                          <CircleDot size={14} /> {activeSession ? 'Active telemetry' : 'Not monitored'}
                        </span>
                      </td>
                      <td className="px-4 py-4">
                        <select
                          aria-label={`Tarang device for ${patient.name}`}
                          value={selectedDevice}
                          disabled={!!activeSession}
                          onChange={(event) => setSelectedDevices((current) => ({ ...current, [patient.id]: event.target.value }))}
                          className="form-field !mt-0 max-w-[220px] font-mono text-xs disabled:bg-[var(--color-surface-container-low)]"
                        >
                          {!selectedDevice && <option value="">No device available</option>}
                          {devices.filter((device) => device.status !== 'in_use' || device.device_id === activeSession?.device_id).map((device) => (
                            <option key={device.device_id} value={device.device_id}>{device.name} / {device.device_id}</option>
                          ))}
                        </select>
                      </td>
                      <td className="px-5 py-4 text-right">
                        <button onClick={() => startPatient(patient)} disabled={busyMrn === patient.id || (!selectedDevice && !activeSession)} className="button-primary min-w-[126px]">
                          {busyMrn === patient.id ? <RefreshCw size={16} className="animate-spin" /> : activeSession ? <Activity size={16} /> : <Bluetooth size={16} />}
                          {activeSession ? 'Resume' : 'Start'} <ArrowRight size={15} />
                        </button>
                      </td>
                    </tr>
                  );
                })}
              </tbody>
            </table>
          </div>

          <div className="hidden divide-y divide-[var(--color-surface-container-high)] max-md:block">
            {filteredPatients.map((patient) => {
              const activeSession = sessions.find((session) => session.status === 'active' && session.patient_id === patient.dbId);
              const assignedDevice = devices.find((device) => device.assigned_patient_id === patient.dbId);
              const selectedDevice = selectedDevices[patient.id] || activeSession?.device_id || assignedDevice?.device_id || availableDevices[0]?.device_id || '';
              const initials = patient.name.split(/\s+/).map((part) => part[0]).join('').slice(0, 2).toUpperCase();
              return (
                <article key={patient.id} className="min-w-0 overflow-hidden p-5">
                  <div className="flex items-start justify-between gap-3">
                    <div className="flex min-w-0 items-center gap-3">
                      <div className="grid h-10 w-10 shrink-0 place-items-center rounded-md bg-[var(--color-surface-container-high)] text-sm font-bold text-[var(--color-primary)]">{initials}</div>
                      <div className="min-w-0"><h2 className="truncate font-bold">{patient.name}</h2><p className="eyebrow mt-1">MRN {patient.id}</p></div>
                    </div>
                    <span className="flex shrink-0 items-center gap-1.5 text-xs font-bold"><Bed size={14} /> {patient.bed}</span>
                  </div>
                  <div className="mt-4 grid grid-cols-2 gap-3 border-y border-[var(--color-surface-container-high)] py-3 text-xs">
                    <div><p className="eyebrow">Clinical context</p><p className="mt-1 font-semibold">{patient.age} yr / {patient.gender}</p></div>
                    <div><p className="eyebrow">Monitoring</p><p className={`mt-1 font-semibold ${activeSession ? 'text-[var(--color-success)]' : ''}`}>{activeSession ? 'Active telemetry' : 'Not monitored'}</p></div>
                  </div>
                  <label className="mt-4 block text-xs font-bold">Tarang device
                    <select aria-label={`Tarang device for ${patient.name}`} value={selectedDevice} disabled={!!activeSession} onChange={(event) => setSelectedDevices((current) => ({ ...current, [patient.id]: event.target.value }))} className="form-field font-mono text-xs disabled:bg-[var(--color-surface-container-low)]">
                      {!selectedDevice && <option value="">No device available</option>}
                      {devices.filter((device) => device.status !== 'in_use' || device.device_id === activeSession?.device_id).map((device) => <option key={device.device_id} value={device.device_id}>{device.name} / {device.device_id}</option>)}
                    </select>
                  </label>
                  <button onClick={() => startPatient(patient)} disabled={busyMrn === patient.id || (!selectedDevice && !activeSession)} className="button-primary mt-3 w-full">
                    {busyMrn === patient.id ? <RefreshCw size={16} className="animate-spin" /> : activeSession ? <Activity size={16} /> : <Bluetooth size={16} />}
                    {activeSession ? 'Resume monitoring' : 'Start monitoring'} <ArrowRight size={15} />
                  </button>
                </article>
              );
            })}
          </div>

          {filteredPatients.length === 0 && (
            <div className="py-16 text-center">
              <UserRound size={30} className="mx-auto mb-3 text-[var(--color-outline)]" />
              <p className="font-bold">No matching patients</p>
              <p className="mt-1 text-sm text-[var(--color-on-surface-variant)]">Try a different search or add a new patient.</p>
            </div>
          )}
        </section>
      </div>

      {showCreate && (
        <div className="fixed inset-0 z-50 grid place-items-center bg-[#131b2e]/45 p-5" role="dialog" aria-modal="true" aria-labelledby="add-patient-title">
          <form onSubmit={submitPatient} className="max-h-[92vh] w-full max-w-3xl overflow-y-auto rounded-lg border border-[var(--color-outline-variant)] bg-white shadow-2xl">
            <div className="sticky top-0 z-10 flex items-center justify-between border-b border-[var(--color-outline-variant)] bg-white px-6 py-5">
              <div><p className="eyebrow mb-1 text-[var(--color-primary)]">New admission</p><h2 id="add-patient-title" className="text-xl font-extrabold">Add patient to worklist</h2></div>
              <button type="button" onClick={() => setShowCreate(false)} className="icon-button" title="Close"><X size={20} /></button>
            </div>
            <div className="grid grid-cols-2 gap-x-5 gap-y-4 p-6 max-sm:grid-cols-1">
              <label className="text-xs font-bold">Full name<input required value={form.name} onChange={(e) => setForm({ ...form, name: e.target.value })} className="form-field" /></label>
              <label className="text-xs font-bold">Medical record number<input required value={form.mrn} onChange={(e) => setForm({ ...form, mrn: e.target.value })} className="form-field font-mono" /></label>
              <label className="text-xs font-bold">Age<input required min={0} max={130} type="number" value={form.age} onChange={(e) => setForm({ ...form, age: Number(e.target.value) })} className="form-field" /></label>
              <label className="text-xs font-bold">Gender<select value={form.gender} onChange={(e) => setForm({ ...form, gender: e.target.value as PatientCreateInput['gender'] })} className="form-field"><option>Male</option><option>Female</option><option>Other</option></select></label>
              <label className="text-xs font-bold">Bed<input required value={form.bed} onChange={(e) => setForm({ ...form, bed: e.target.value })} className="form-field" /></label>
              <label className="text-xs font-bold">Admit date<input required type="date" value={form.admit_date} onChange={(e) => setForm({ ...form, admit_date: e.target.value })} className="form-field" /></label>
              <label className="text-xs font-bold">Attending physician<input required value={form.attending_physician} onChange={(e) => setForm({ ...form, attending_physician: e.target.value })} className="form-field" /></label>
              <label className="text-xs font-bold">Blood group<input value={form.blood_type} onChange={(e) => setForm({ ...form, blood_type: e.target.value })} className="form-field" /></label>
              <label className="col-span-2 text-xs font-bold max-sm:col-span-1">Allergies<input value={allergies} onChange={(e) => setAllergies(e.target.value)} placeholder="Comma separated" className="form-field" /></label>
              <label className="col-span-2 text-xs font-bold max-sm:col-span-1">Medical history<textarea value={history} onChange={(e) => setHistory(e.target.value)} rows={4} placeholder="One item per line" className="form-field resize-none" /></label>
            </div>
            <div className="flex justify-end gap-3 border-t border-[var(--color-outline-variant)] bg-[var(--color-surface)] px-6 py-4">
              <button type="button" onClick={() => setShowCreate(false)} className="button-secondary">Cancel</button>
              <button disabled={saving} type="submit" className="button-primary">{saving && <RefreshCw size={16} className="animate-spin" />} Add to worklist</button>
            </div>
          </form>
        </div>
      )}
    </main>
  );
};
