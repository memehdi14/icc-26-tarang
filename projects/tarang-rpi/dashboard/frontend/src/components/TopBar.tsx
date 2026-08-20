'use client';

import React from 'react';
import {
  AlertTriangle,
  CircleUserRound,
} from 'lucide-react';
import { PatientInfo } from '../types/telemetry';

interface TopBarProps {
  patient: PatientInfo;
  bleConnected: boolean;
  backendOnline: boolean;
  pageBusy: boolean;
  onEmergency: () => void;
  onOpenWorkstation: () => void;
  onOpenSettings: () => void;
  sidebarCollapsed?: boolean;
  patientRailCollapsed?: boolean;
  onToggleSidebar?: () => void;
  onTogglePatientRail?: () => void;
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
  <header className="app-topbar !h-[54px] !px-4 flex items-center justify-between whitespace-nowrap bg-white border-b border-[var(--line)] shadow-xs">
    {/* Left: Brand + Bed + MRN in a single clean line */}
    <div className="flex items-center gap-3 whitespace-nowrap shrink-0">
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
      <div className="flex items-center gap-2 whitespace-nowrap">
        <span className="text-sm font-bold tracking-tight text-[var(--ink)]">Tarang</span>
        <span className="text-[11px] font-semibold text-[var(--ink-soft)] border-l border-[var(--line)] pl-2">
          Bed {patient.bed}
        </span>
        <span className="text-xs font-mono text-[var(--muted)]">
          MRN {patient.id}
        </span>
      </div>
    </div>

    {/* Center: Patient Name + BLE Connection Badge */}
    <div className="flex items-center gap-2.5 whitespace-nowrap">
      <button
        onClick={onOpenWorkstation}
        className="px-3 py-1 rounded bg-[var(--paper-2)] border border-[var(--line)] text-xs font-bold uppercase tracking-wider text-[var(--ink)] hover:border-[var(--accent)] transition-colors"
      >
        {patient.name}
      </button>
      <span className="font-mono text-xs" title="Device and BLE link state">
        <span className={`inline-flex items-center gap-1.5 px-2.5 py-1 text-[11px] font-bold uppercase tracking-wider rounded-full ${backendOnline && bleConnected ? 'text-[var(--clinical-teal)] bg-[#00837818]' : 'text-[var(--amber-alert)] bg-[#d9770618]'}`}>
          <span className={`h-1.5 w-1.5 rounded-full ${backendOnline && bleConnected ? 'bg-[var(--clinical-teal)] animate-pulse' : 'bg-[var(--amber-alert)]'}`} />
          {backendOnline && bleConnected ? 'BLE Bonded' : 'Link offline'}
        </span>
      </span>
    </div>

    {/* Right: Emergency Button + Settings */}
    <div className="flex items-center gap-2 whitespace-nowrap shrink-0">
      <button
        className="emergency-button !py-1.5 !px-3.5 !text-xs"
        onClick={onEmergency}
        disabled={pageBusy}
        title="Trigger clinical emergency page"
      >
        <AlertTriangle size={13} />
        <span>{pageBusy ? 'Paging...' : 'Emergency'}</span>
      </button>

      <button
        className="icon-button !w-8 !h-8"
        onClick={onOpenSettings}
        aria-label="Workstation settings"
        title="Settings"
      >
        <CircleUserRound size={18} />
      </button>
    </div>
  </header>
);
