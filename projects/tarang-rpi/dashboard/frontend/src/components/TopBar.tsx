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
      <img
        src="/logo_mark.svg"
        alt="Tarang"
        className="h-7 w-7 shrink-0 object-contain"
        onError={(e) => {
          // Fallback to PNG if SVG fails
          (e.currentTarget as HTMLImageElement).src = '/tarang_logo.png';
        }}
      />
      <div className="flex flex-col">
        <span className="text-sm font-bold tracking-tight text-[var(--ink)]">Tarang</span>
        <span className="text-[10px] font-medium text-[var(--muted)]">Clinical telemetry</span>
      </div>
      <div className="ml-2 hidden items-center gap-2.5 border-l border-[var(--line)] pl-3 lg:flex">
        <span className="text-[10px] font-medium text-[var(--muted)]">Bed {patient.bed}</span>
        <span className="text-[10px] text-[var(--muted)]">•</span>
        <span className="text-[10px] font-mono text-[var(--muted)]">MRN {patient.id}</span>
      </div>
    </div>

    <div className="topbar-context" aria-label="Clinical telemetry state">
      <button className="topbar-context-item is-active" onClick={onOpenWorkstation}>
        <span className="font-semibold text-xs text-[var(--ink)]">{patient.name}</span>
      </button>
      <span className="topbar-context-item font-mono" title="Device and BLE link state">
        <span className={`inline-flex items-center gap-1.5 px-2 py-0.5 text-[11px] font-medium rounded ${backendOnline && bleConnected ? 'text-[var(--clinical-teal)] bg-[#00837812]' : 'text-[var(--amber-alert)] bg-[#d9770612]'}`}>
          <span className={`h-1.5 w-1.5 rounded-full ${backendOnline && bleConnected ? 'bg-[var(--clinical-teal)]' : 'bg-[var(--amber-alert)]'}`} />
          {backendOnline && bleConnected ? 'Connected' : 'Link offline'}
        </span>
      </span>
    </div>

    <div className="topbar-actions">
      <button
        className="emergency-button"
        onClick={onEmergency}
        disabled={pageBusy}
        title="Trigger clinical emergency page"
      >
        <AlertTriangle size={14} />
        <span>{pageBusy ? 'Paging...' : 'Emergency'}</span>
      </button>

      <button
        className="icon-button"
        onClick={onOpenSettings}
        aria-label="Workstation settings"
        title="Settings"
      >
        <CircleUserRound size={17} />
      </button>
    </div>
  </header>
);
