'use client';

import React from 'react';
import { AlertTriangle, Bell, CircleUserRound, Radio } from 'lucide-react';
import { PatientInfo } from '../types/telemetry';

interface TopBarProps {
  patient: PatientInfo;
  bleConnected: boolean;
  backendOnline: boolean;
  pageBusy: boolean;
  onEmergency: () => void;
  onOpenWorkstation: () => void;
  onOpenSettings: () => void;
}

export const TopBar: React.FC<TopBarProps> = ({
  patient,
  bleConnected,
  backendOnline,
  pageBusy,
  onEmergency,
  onOpenWorkstation,
  onOpenSettings,
}) => (
  <header className="app-topbar">
    <div className="topbar-brand">
      <img src="/images/tarang-logo.png" alt="Tarang" className="h-7 w-auto object-contain" />
      <div className="flex flex-col">
        <span className="text-sm font-bold tracking-tight text-[var(--ink)]">Tarang</span>
        <span className="text-[9px] font-semibold tracking-widest text-[var(--muted)] uppercase -mt-0.5">Clinical Telemetry</span>
      </div>
      <div className="ml-2 hidden items-center gap-2 border-l border-[var(--line)] pl-3 lg:flex">
        <img src="/images/ocelleon-logo.png" alt="Ocelleon" className="h-4 w-auto opacity-75 hover:opacity-100 transition-opacity" title="Team Ocelleon" />
        <img src="/images/silabs-logo.jpg" alt="Silicon Labs" className="h-3.5 w-auto rounded opacity-60 hover:opacity-100 transition-opacity" title="Silicon Labs EFR32MG26" />
      </div>
    </div>

    <div className="topbar-context" aria-label="Current clinical context">
      <button className="topbar-context-item is-active" onClick={onOpenWorkstation}>
        <span className="discovery-eyebrow !text-[10px] !text-[var(--ink)]">Bed {patient.bed}</span>
      </button>
      <span className="topbar-context-item hidden md:flex text-[var(--muted)]">MRN {patient.id}</span>
      <span className="topbar-context-item font-mono" title="Backend and device link status">
        <span className={`inline-flex items-center gap-1.5 rounded-full px-2.5 py-0.5 text-[10px] font-bold ${backendOnline && bleConnected ? 'bg-[#00837815] text-[var(--clinical-teal)] border border-[#00837830]' : 'bg-[#d9770615] text-[var(--amber-alert)] border border-[#d9770630]'}`}>
          <span className={`h-1.5 w-1.5 rounded-full ${backendOnline && bleConnected ? 'bg-[var(--clinical-teal)] animate-ping' : 'bg-[var(--amber-alert)]'}`} />
          {backendOnline && bleConnected ? 'BLE Bonded' : 'Link Pending'}
        </span>
      </span>
    </div>

    <div className="topbar-actions">
      <button
        className="emergency-button"
        onClick={onEmergency}
        disabled={pageBusy}
        title="Page duty physician"
      >
        <AlertTriangle size={15} />
        <span className="max-sm:hidden">{pageBusy ? 'Paging...' : 'Emergency'}</span>
      </button>
      <button className="icon-button" onClick={onOpenWorkstation} title="Open clinical events" aria-label="Open clinical events">
        <Bell size={18} />
      </button>
      <button className="icon-button profile-button" onClick={onOpenSettings} title="Clinician settings" aria-label="Clinician settings">
        <CircleUserRound size={19} />
      </button>
    </div>
  </header>
);

