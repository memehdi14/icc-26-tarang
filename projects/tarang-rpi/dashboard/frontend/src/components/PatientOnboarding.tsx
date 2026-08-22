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
      <main className="min-h-screen bg-[var(--paper)]">
        <header className="flex h-[64px] items-center border-b border-[var(--line)] px-7 bg-[var(--paper-card)]">
          <img src="/images/tarang-logo.png" alt="Tarang" className="mr-3 h-7 w-auto object-contain" style={{ height: '28px', width: 'auto' }} />
          <div className="flex items-center gap-3">
            <span className="text-base font-bold text-[var(--ink)]">Tarang Clinical</span>
            <span className="hidden sm:inline-block h-3.5 w-px bg-[var(--line)]" />
            <img src="/images/ocelleon-logo.png" alt="Ocelleon" className="hidden sm:block object-contain opacity-70" style={{ height: '14px', width: 'auto' }} />
          </div>
        </header>
        <section className="mx-auto grid min-h-[calc(100vh-64px)] max-w-5xl grid-cols-[1fr_320px] items-center gap-16 px-8 max-md:grid-cols-1 max-md:gap-8">
          <div className="view-enter">
            <span className="discovery-eyebrow mb-2">ICU Clinical Workstation</span>
            <h1 className="max-w-xl text-3xl font-bold leading-tight text-[var(--ink)] max-md:text-2xl">
              Preparing Patient Telemetry
            </h1>
            <p className="mt-3 max-w-lg text-xs text-[var(--ink-soft)] leading-relaxed">
              Verifying SQLite clinical database, bonded EFR32MG26 GATT records, and edge arrhythmia classification runtime.
            </p>
            <div className="waveform-grid relative mt-7 h-24 overflow-hidden rounded-lg border border-[var(--line)] bg-[var(--paper-card)]">
              <div className="absolute inset-y-0 left-0 w-24 animate-pulse bg-[var(--accent-soft)]" />
              <svg viewBox="0 0 720 112" className="h-full w-full" aria-hidden="true">
                <path d="M0 58H92l12-8 9 18 12-62 10 99 11-47h96l10-8 8 16 13-58 10 94 12-44h101l10-9 9 18 12-62 10 99 11-47h98l11-8 8 16 13-57 10 92 12-43h86" fill="none" stroke="#0071E3" strokeWidth="2" />
              </svg>
            </div>
          </div>
          <div className="border-l border-[var(--line)] pl-8 max-md:border-l-0 max-md:border-t max-md:pt-8">
            {[
              [Database, 'Clinical Database', 'Connected'],
              [ShieldCheck, 'Security Context', 'AES-128 Ready'],
              [UsersRound, 'Patient Worklist', 'Loaded'],
            ].map(([Icon, label, value], index) => {
              const StageIcon = Icon as typeof Database;
              return (
                <div key={label as string} className="flex items-center gap-3 border-b border-[var(--line-soft)] py-3.5 last:border-0">
                  <StageIcon size={16} className="text-[var(--accent)]" />
                  <div className="flex-1">
                    <p className="text-xs font-bold text-[var(--ink)]">{label as string}</p>
                    <p className="font-mono text-[10px] text-[var(--muted)]">{value as string}</p>
                  </div>
                  <span className="h-2 w-2 rounded-full bg-[var(--clinical-teal)]" style={{ animationDelay: `${index * 180}ms` }} />
                </div>
              );
            })}
          </div>
        </section>
      </main>
    );
  }

  return (
    <main className="min-h-screen bg-[var(--paper)]">
      <header className="sticky top-0 z-30 border-b border-[var(--line)] bg-white/95 backdrop-blur-md">
        <div className="mx-auto flex h-[58px] max-w-[1440px] items-center justify-between px-6">
          <div className="flex items-center gap-3">
            <img
              src="/logo_mark.svg"
              alt="Tarang"
              className="h-7 w-7 shrink-0 object-contain"
              style={{ width: '28px', height: '28px' }}
              onError={(e) => {
                const target = e.currentTarget as HTMLImageElement;
                target.onerror = null;
                target.src = '/images/tarang-logo.png';
              }}
            />
            <div>
              <div className="text-sm font-bold text-[var(--ink)] leading-none">Tarang Clinical</div>
              <div className="text-[10px] font-medium text-[var(--muted)] mt-0.5">Patient worklist</div>
            </div>
            <div className="hidden sm:flex items-center pl-2.5 border-l border-[var(--line)]">
              <img
                src="/images/ocelleon-logo.png"
                alt="Ocelleon"
                className="object-contain opacity-80"
                style={{ height: '16px', width: 'auto' }}
                onError={(e) => { (e.currentTarget as HTMLElement).style.display = 'none'; }}
              />
            </div>
          </div>
          <div className="flex items-center gap-3">
            <button onClick={() => setShowCreate(true)} className="discovery-pill-primary !py-1.5 !px-3.5 !text-xs">
              <Plus size={14} /> <span>New patient</span>
            </button>
          </div>
        </div>
      </header>

      <div className="mx-auto max-w-[1440px] px-6 py-6 max-sm:px-4">
        <div className="view-header view-enter !pb-4">
          <div>
            <span className="text-xs font-semibold text-[var(--ink)] flex items-center gap-1">
              <span className="text-[var(--accent)] text-[10px]">✦</span> Telemetry management
            </span>
            <h1 className="text-2xl font-bold text-[var(--ink)]">Patient worklist</h1>
            <p className="text-xs text-[var(--ink-soft)] mt-0.5">Select an admitted patient to begin live BLE telemetry.</p>
          </div>
          <div className="flex divide-x divide-[var(--line)] border border-[var(--line)] rounded-lg bg-white shadow-xs">
            <div className="px-4 py-2"><p className="text-[10px] uppercase tracking-wider text-[var(--muted)] font-medium">Patients</p><p className="font-mono text-base font-bold text-[var(--ink)]">{patients.length}</p></div>
            <div className="px-4 py-2"><p className="text-[10px] uppercase tracking-wider text-[var(--muted)] font-medium">Active</p><p className="font-mono text-base font-bold text-[var(--clinical-teal)]">{activeSessionCount}</p></div>
            <div className="px-4 py-2"><p className="text-[10px] uppercase tracking-wider text-[var(--muted)] font-medium">Devices ready</p><p className="font-mono text-base font-bold text-[var(--ink)]">{availableDevices.length}</p></div>
          </div>
        </div>

        {(error || actionError) && (
          <div className="mb-4 flex items-center justify-between gap-4 rounded-lg border border-red-200 bg-red-50 px-4 py-2.5 text-xs text-red-700" role="alert">
            <span className="flex items-center gap-2 font-medium"><AlertCircle size={15} />{actionError || error}</span>
            {error && <button onClick={onRetry} className="icon-button" title="Retry"><RefreshCw size={14} /></button>}
          </div>
        )}

        <section className="rounded-lg border border-[var(--line)] bg-white overflow-hidden shadow-xs view-enter" style={{ animationDelay: '70ms' }}>
          <div className="flex items-center justify-between gap-4 border-b border-[var(--line)] px-5 py-3 bg-[var(--paper-2)] max-sm:flex-col max-sm:items-stretch">
            <div className="flex items-center gap-2 text-xs font-bold uppercase tracking-wider text-[var(--ink)]">
              <UsersRound size={15} className="text-[var(--clinical-teal)]" /> Admitted patients
            </div>
            <label className="relative w-80 max-sm:w-full">
              <Search size={15} className="pointer-events-none absolute left-3 top-1/2 -translate-y-1/2 text-[var(--muted)]" />
              <span className="sr-only">Search patients</span>
              <input
                value={query}
                onChange={(event) => setQuery(event.target.value)}
                placeholder="Search name, MRN, bed, physician..."
                className="form-field !mt-0 !pr-3 !py-1.5 !text-xs !bg-white"
                style={{ paddingLeft: '34px' }}
              />
            </label>
          </div>

          <div className="overflow-x-auto max-md:hidden">
            <table className="w-full min-w-[980px] border-collapse text-left">
              <thead className="bg-[var(--paper-2)] border-b border-[var(--line)]">
                <tr className="text-[11px] text-[var(--muted)] uppercase tracking-wider">
                  <th className="px-5 py-2.5 font-semibold">Patient</th>
                  <th className="px-4 py-2.5 font-semibold">Location</th>
                  <th className="px-4 py-2.5 font-semibold">Clinical context</th>
                  <th className="px-4 py-2.5 font-semibold">Status</th>
                  <th className="px-4 py-2.5 font-semibold">Tarang device</th>
                  <th className="px-5 py-2.5 text-right font-semibold">Action</th>
                </tr>
              </thead>
              <tbody className="divide-y divide-[var(--line-soft)] text-xs">
                {filteredPatients.map((patient) => {
                  const activeSession = sessions.find((session) => session.status === 'active' && session.patient_id === patient.dbId);
                  const assignedDevice = devices.find((device) => device.assigned_patient_id === patient.dbId);
                  const selectedDevice = selectedDevices[patient.id] || activeSession?.device_id || assignedDevice?.device_id || availableDevices[0]?.device_id || '';
                  const initials = patient.name.split(/\s+/).map((part) => part[0]).join('').slice(0, 2).toUpperCase();
                  return (
                    <tr
                      key={patient.id}
                      onClick={() => startPatient(patient)}
                      className="transition-colors hover:bg-slate-50/80 cursor-pointer active:bg-slate-100"
                    >
                      <td className="px-5 py-3.5">
                        <div className="flex items-center gap-3">
                          <div className="grid h-9 w-9 shrink-0 place-items-center rounded bg-[var(--paper-2)] text-xs font-bold text-[var(--ink)]">{initials}</div>
                          <div className="min-w-0">
                            <p className="font-semibold text-[var(--ink)] text-sm">{patient.name}</p>
                            <p className="text-[11px] text-[var(--muted)] font-mono tracking-tight mt-0.5">MRN {patient.id}</p>
                          </div>
                        </div>
                      </td>
                      <td className="px-4 py-3.5"><p className="flex items-center gap-1.5 font-medium"><Bed size={13} /> Bed {patient.bed}</p><p className="text-[10px] text-[var(--muted)]">Admitted {patient.admitDate}</p></td>
                      <td className="px-4 py-3.5"><p>{patient.age} yr / {patient.gender}</p><p className="text-[10px] text-[var(--muted)]">{patient.attendingPhysician}</p></td>
                      <td className="px-4 py-3.5">
                        <span className={`inline-flex items-center gap-1.5 font-medium ${activeSession ? 'text-[var(--clinical-teal)]' : 'text-[var(--muted)]'}`}>
                          <span className={`h-1.5 w-1.5 rounded-full ${activeSession ? 'bg-[var(--clinical-teal)]' : 'bg-[var(--muted)]'}`} />
                          {activeSession ? 'Active telemetry' : 'Unassigned'}
                        </span>
                      </td>
                      <td className="px-4 py-3.5">
                        <select
                          aria-label={`Tarang device for ${patient.name}`}
                          value={selectedDevice}
                          disabled={!!activeSession}
                          onChange={(event) => setSelectedDevices((current) => ({ ...current, [patient.id]: event.target.value }))}
                          className="form-field !mt-0 max-w-[240px] font-mono text-xs disabled:bg-[var(--paper-2)] disabled:text-[var(--muted)]"
                        >
                          {!selectedDevice && <option value="">No device available</option>}
                          {devices.map((device) => {
                            const isAssignedToOther = device.status === 'in_use' && device.device_id !== activeSession?.device_id;
                            return (
                              <option key={device.device_id} value={device.device_id} disabled={isAssignedToOther}>
                                {device.name || device.device_id} ({device.status === 'in_use' ? 'In Use' : 'Available'})
                              </option>
                            );
                          })}
                        </select>
                      </td>
                      <td className="px-5 py-3.5 text-right">
                        <button onClick={() => startPatient(patient)} disabled={busyMrn === patient.id || (!selectedDevice && !activeSession)} className="discovery-pill-primary !py-1 !px-3 !text-xs min-w-[110px]">
                          {busyMrn === patient.id ? <RefreshCw size={13} className="animate-spin" /> : activeSession ? <Activity size={13} /> : <Bluetooth size={13} />}
                          <span>{activeSession ? 'Resume' : 'Start'}</span> <ArrowRight size={13} />
                        </button>
                      </td>
                    </tr>
                  );
                })}
              </tbody>
            </table>
          </div>

          <div className="hidden divide-y divide-[var(--line-soft)] max-md:block">
            {filteredPatients.map((patient) => {
              const activeSession = sessions.find((session) => session.status === 'active' && session.patient_id === patient.dbId);
              const assignedDevice = devices.find((device) => device.assigned_patient_id === patient.dbId);
              const selectedDevice = selectedDevices[patient.id] || activeSession?.device_id || assignedDevice?.device_id || availableDevices[0]?.device_id || '';
              const initials = patient.name.split(/\s+/).map((part) => part[0]).join('').slice(0, 2).toUpperCase();
              return (
                <article key={patient.id} className="min-w-0 p-4">
                  <div className="flex items-start justify-between gap-3">
                    <div className="flex min-w-0 items-center gap-3">
                      <div className="grid h-10 w-10 shrink-0 place-items-center rounded bg-[var(--paper-2)] text-xs font-bold text-[var(--ink)]">{initials}</div>
                      <div className="min-w-0">
                        <h2 className="truncate font-bold text-sm text-[var(--ink)]">{patient.name}</h2>
                        <p className="text-[11px] text-[var(--muted)] font-mono mt-0.5">MRN {patient.id}</p>
                      </div>
                    </div>
                    <span className="flex shrink-0 items-center gap-1.5 text-xs font-semibold text-[var(--ink)]"><Bed size={13} /> Bed {patient.bed}</span>
                  </div>
                  <div className="mt-3 grid grid-cols-2 gap-2 border-y border-[var(--line-soft)] py-2.5 text-xs">
                    <div><p className="text-[10px] text-[var(--muted)] uppercase">Clinical context</p><p className="mt-0.5 font-medium">{patient.age} yr / {patient.gender}</p></div>
                    <div><p className="text-[10px] text-[var(--muted)] uppercase">Status</p><p className={`mt-0.5 font-medium ${activeSession ? 'text-[var(--clinical-teal)]' : 'text-[var(--muted)]'}`}>{activeSession ? 'Active telemetry' : 'Unassigned'}</p></div>
                  </div>
                  <label className="mt-3 block text-xs font-semibold text-[var(--ink)]">Assigned device
                    <select aria-label={`Tarang device for ${patient.name}`} value={selectedDevice} disabled={!!activeSession} onChange={(event) => setSelectedDevices((current) => ({ ...current, [patient.id]: event.target.value }))} className="form-field font-mono text-xs disabled:bg-[var(--paper-2)] mt-1">
                      {!selectedDevice && <option value="">No device available</option>}
                      {devices.map((device) => <option key={device.device_id} value={device.device_id}>{device.name || device.device_id}</option>)}
                    </select>
                  </label>
                  <button onClick={() => startPatient(patient)} disabled={busyMrn === patient.id || (!selectedDevice && !activeSession)} className="discovery-pill-primary mt-3 w-full !py-2 justify-center !text-xs">
                    {busyMrn === patient.id ? <RefreshCw size={14} className="animate-spin" /> : activeSession ? <Activity size={14} /> : <Bluetooth size={14} />}
                    <span>{activeSession ? 'Resume monitoring' : 'Start monitoring'}</span> <ArrowRight size={14} />
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
