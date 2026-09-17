'use client';

import React from 'react';
import {
  AlertTriangle,
  Bell,
  BellOff,
  ChevronLeft,
  ChevronRight,
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
  audioAlertsEnabled?: boolean;
  onToggleAudioAlerts?: () => void;
}

export const TopBar: React.FC<TopBarProps> = ({
  patient,
  bleConnected,
  backendOnline,
  pageBusy,
  onEmergency,
  onOpenWorkstation,
  onOpenSettings,
  sidebarCollapsed,
  patientRailCollapsed,
  onToggleSidebar,
  onTogglePatientRail,
  audioAlertsEnabled = false,
  onToggleAudioAlerts,
}) => (
  <header className="app-topbar flex items-center justify-between bg-white border-b border-[var(--line)] shadow-xs px-2.5 sm:px-4">
    {/* Left: Brand + Bed + MRN in a single clean line */}
    <div className="flex items-center gap-2 sm:gap-3 whitespace-nowrap shrink-0">
      <img
        src="/logo_mark.svg"
        alt="Tarang"
        className="h-6 w-6 sm:h-7 sm:w-7 shrink-0 object-contain"
        style={{ width: '26px', height: '26px' }}
        onError={(e) => {
          const target = e.currentTarget as HTMLImageElement;
          target.onerror = null;
          target.src = '/images/tarang-logo.png';
        }}
      />
      <div className="flex items-center gap-1.5 sm:gap-2 whitespace-nowrap">
        <span className="text-xs sm:text-sm font-bold tracking-tight text-[var(--ink)]">Tarang</span>
        <span className="text-[10px] sm:text-[11px] font-semibold text-[var(--ink-soft)] border-l border-[var(--line)] pl-1.5 sm:pl-2">
          Bed {patient.bed}
        </span>
        <span className="hidden md:inline text-xs font-mono text-[var(--muted)]">
          MRN {patient.id}
        </span>
      </div>
    </div>

    {/* Center: Patient Name + BLE Connection Badge */}
    <div className="flex items-center gap-1.5 sm:gap-2.5 whitespace-nowrap min-w-0">
      <button
        onClick={onOpenWorkstation}
        className="truncate max-w-[100px] sm:max-w-[170px] px-2 sm:px-3 py-0.5 sm:py-1 rounded bg-[var(--paper-2)] border border-[var(--line)] text-[11px] sm:text-xs font-bold uppercase tracking-wider text-[var(--ink)] hover:border-[var(--accent)] transition-colors"
      >
        {patient.name}
      </button>
      <span className="font-mono text-xs" title="Device and BLE link state">
        <span className={`inline-flex items-center gap-1 sm:gap-1.5 px-2 sm:px-2.5 py-0.5 sm:py-1 text-[10px] sm:text-[11px] font-bold uppercase tracking-wider rounded-full ${backendOnline && bleConnected ? 'text-[var(--clinical-teal)] bg-[#00837818]' : 'text-[var(--amber-alert)] bg-[#d9770618]'}`}>
          <span className={`h-1.5 w-1.5 rounded-full ${backendOnline && bleConnected ? 'bg-[var(--clinical-teal)] animate-pulse' : 'bg-[var(--amber-alert)]'}`} />
          <span className="hidden sm:inline">{backendOnline && bleConnected ? 'BLE Bonded' : 'Link offline'}</span>
          <span className="sm:hidden">{backendOnline && bleConnected ? 'BLE' : 'Off'}</span>
        </span>
      </span>
    </div>

    {/* Right: Emergency Button + Audio Bell + Toggle Patient Rail + Settings */}
    <div className="flex items-center gap-1.5 sm:gap-2 whitespace-nowrap shrink-0">
      {onToggleAudioAlerts && (
        <button
          className={`icon-button !w-8 !h-8 sm:!w-9 sm:!h-9 !border ${audioAlertsEnabled ? 'border-emerald-300 bg-emerald-50 text-emerald-700' : 'border-slate-300 bg-slate-100 text-slate-500'}`}
          onClick={onToggleAudioAlerts}
          title={audioAlertsEnabled ? "Audio Alarm: ACTIVE (Click to Silence)" : "Audio Alarm: SILENCED (Click to Enable)"}
          aria-label="Toggle alarm audio"
        >
          {audioAlertsEnabled ? <Bell size={15} /> : <BellOff size={15} />}
        </button>
      )}

      <button
        className="emergency-button !py-1 sm:!py-1.5 !px-2.5 sm:!px-3.5 !text-xs !min-h-[32px] sm:!min-h-[34px]"
        onClick={onEmergency}
        disabled={pageBusy}
        title="Trigger clinical emergency page"
      >
        <AlertTriangle size={13} />
        <span className="hidden sm:inline">{pageBusy ? 'Paging...' : 'Emergency'}</span>
      </button>

      {onTogglePatientRail && (
        <button
          className="icon-button !w-8 !h-8 sm:!w-9 sm:!h-9 !border !border-[var(--line)]"
          onClick={onTogglePatientRail}
          title={patientRailCollapsed ? "Expand Right Summary Sidebar" : "Collapse Right Summary (Focus Central)"}
          aria-label="Toggle patient summary rail"
        >
          {patientRailCollapsed ? <ChevronLeft size={16} /> : <ChevronRight size={16} />}
        </button>
      )}

      <button
        className="icon-button !w-8 !h-8 sm:!w-9 sm:!h-9"
        onClick={onOpenSettings}
        aria-label="Workstation settings"
        title="Settings"
      >
        <CircleUserRound size={18} />
      </button>
    </div>
  </header>
);
