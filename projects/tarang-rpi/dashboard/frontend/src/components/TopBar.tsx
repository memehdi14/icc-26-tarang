'use client';

import React from 'react';
import {
  AlertTriangle,
  CircleUserRound,
  PanelLeft,
  PanelLeftClose,
  PanelRight,
  PanelRightClose,
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
  sidebarCollapsed = false,
  patientRailCollapsed = false,
  onToggleSidebar,
  onTogglePatientRail,
}) => (
  <header className="app-topbar">
    <div className="topbar-brand flex items-center gap-3">
      {onToggleSidebar && (
        <button
          onClick={onToggleSidebar}
          className={`icon-button !w-8 !h-8 ${sidebarCollapsed ? 'text-[var(--accent)] bg-[var(--paper-2)]' : 'text-[var(--ink-soft)] hover:text-[var(--ink)]'}`}
          title={sidebarCollapsed ? 'Expand navigation sidebar' : 'Retract navigation sidebar'}
          aria-label="Toggle navigation sidebar"
        >
          {sidebarCollapsed ? <PanelLeft size={18} /> : <PanelLeftClose size={18} />}
        </button>
      )}

      {/* Larger Tarang Logo */}
      <img
        src="/logo_mark.svg"
        alt="Tarang"
        className="h-8 w-8 shrink-0 object-contain"
        onError={(e) => {
          (e.currentTarget as HTMLImageElement).src = '/tarang_logo.png';
        }}
      />
      <div className="flex flex-col">
        <span className="text-sm font-bold tracking-tight text-[var(--ink)] leading-none">Tarang</span>
        <span className="text-[10px] font-medium text-[var(--muted)] mt-0.5">Clinical Telemetry</span>
      </div>

      {/* Larger Ocelleon Logo */}
      <div className="hidden sm:flex items-center pl-2 border-l border-[var(--line)]">
        <img
          src="/images/ocelleon-logo.png"
          alt="Ocelleon"
          className="h-4.5 w-auto object-contain opacity-80"
          onError={(e) => {
            (e.currentTarget as HTMLElement).style.display = 'none';
          }}
        />
      </div>

      {/* Patient Location & MRN Tags */}
      <div className="ml-1 hidden items-center gap-2 border-l border-[var(--line)] pl-3 lg:flex">
        <span className="text-xs font-semibold text-[var(--ink)] flex items-center gap-1">
          <span className="text-[var(--accent)] text-[10px]">✦</span> Bed {patient.bed}
        </span>
        <span className="text-[10px] text-[var(--muted)]">•</span>
        <span className="text-xs font-mono text-[var(--muted)]">MRN {patient.id}</span>
      </div>
    </div>

    <div className="topbar-context flex items-center gap-2" aria-label="Clinical telemetry state">
      <button className="topbar-context-item is-active !py-1 !px-3" onClick={onOpenWorkstation}>
        <span className="font-bold text-xs text-[var(--ink)] uppercase tracking-wide">{patient.name}</span>
      </button>
      <span className="topbar-context-item font-mono" title="Device and BLE link state">
        <span className={`inline-flex items-center gap-1.5 px-2.5 py-0.5 text-[11px] font-bold uppercase tracking-wider rounded-full ${backendOnline && bleConnected ? 'text-[var(--clinical-teal)] bg-[#00837818]' : 'text-[var(--amber-alert)] bg-[#d9770618]'}`}>
          <span className={`h-1.5 w-1.5 rounded-full ${backendOnline && bleConnected ? 'bg-[var(--clinical-teal)] animate-pulse' : 'bg-[var(--amber-alert)]'}`} />
          {backendOnline && bleConnected ? 'BLE Bonded' : 'Link offline'}
        </span>
      </span>
    </div>

    <div className="topbar-actions flex items-center gap-2">
      <button
        className="emergency-button"
        onClick={onEmergency}
        disabled={pageBusy}
        title="Trigger clinical emergency page"
      >
        <AlertTriangle size={14} />
        <span className="max-sm:hidden">{pageBusy ? 'Paging...' : 'Emergency'}</span>
      </button>

      {onTogglePatientRail && (
        <button
          className={`icon-button !w-8 !h-8 ${patientRailCollapsed ? 'text-[var(--muted)] hover:text-[var(--ink)]' : 'text-[var(--accent)] bg-[var(--paper-2)] border border-[var(--line)]'}`}
          onClick={onTogglePatientRail}
          aria-label="Toggle patient summary rail"
          title={patientRailCollapsed ? 'Expand patient summary rail' : 'Retract patient summary rail'}
        >
          {patientRailCollapsed ? <PanelRight size={18} /> : <PanelRightClose size={18} />}
        </button>
      )}

      <button
        className="icon-button"
        onClick={onOpenSettings}
        aria-label="Workstation settings"
        title="Settings"
      >
        <CircleUserRound size={18} />
      </button>
    </div>
  </header>
);
