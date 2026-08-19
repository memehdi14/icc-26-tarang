'use client';

import React from 'react';
import { Activity, Cable, ListRestart, Radio, Settings, UsersRound } from 'lucide-react';

interface SidebarProps {
  activeTab: 'workstation' | 'diagnostics' | 'settings';
  setActiveTab: (tab: 'workstation' | 'diagnostics' | 'settings') => void;
  bleConnected: boolean;
  patientName: string;
  attendingDoctor: string;
  onChangePatient: () => void;
}

export const Sidebar: React.FC<SidebarProps> = ({
  activeTab,
  setActiveTab,
  bleConnected,
  patientName,
  attendingDoctor,
  onChangePatient,
}) => {
  const initials = attendingDoctor
    .split(/\s+/)
    .filter(Boolean)
    .map((part) => part[0])
    .join('')
    .slice(0, 2)
    .toUpperCase() || 'CL';

  return (
    <aside className="app-sidebar" aria-label="Clinical workstation navigation">
      <div className="sidebar-clinician">
        <div className="sidebar-avatar">{initials}</div>
        <div className="min-w-0">
          <p className="truncate text-sm font-bold text-[var(--color-primary)]">{attendingDoctor}</p>
          <p className="truncate text-xs text-[var(--color-on-surface-variant)]">Monitoring {patientName}</p>
        </div>
      </div>

      <nav className="sidebar-nav">
        <button className={activeTab === 'workstation' ? 'is-active' : ''} onClick={() => setActiveTab('workstation')}>
          <Activity size={20} strokeWidth={1.8} />
          <span>Dashboard</span>
        </button>
        <button onClick={onChangePatient}>
          <UsersRound size={20} strokeWidth={1.8} />
          <span>Patient worklist</span>
        </button>
        <button className={activeTab === 'diagnostics' ? 'is-active' : ''} onClick={() => setActiveTab('diagnostics')}>
          <Cable size={20} strokeWidth={1.8} />
          <span>Device info</span>
        </button>
        <button className={activeTab === 'settings' ? 'is-active' : ''} onClick={() => setActiveTab('settings')}>
          <Settings size={20} strokeWidth={1.8} />
          <span>Settings</span>
        </button>
      </nav>

      <div className="sidebar-status">
        <div className="flex items-center justify-between gap-3">
          <div className="flex min-w-0 items-center gap-2">
            <Radio size={16} className={bleConnected ? 'text-[var(--color-success)]' : 'text-[var(--color-error)]'} />
            <div className="min-w-0">
              <p className="truncate text-xs font-bold">{bleConnected ? 'Tarang connected' : 'Device disconnected'}</p>
              <p className="truncate font-mono text-[10px] text-[var(--color-on-surface-variant)]">
                {bleConnected ? 'Protected BLE channel' : 'Awaiting EFR32 link'}
              </p>
            </div>
          </div>
          <span className={`status-dot ${bleConnected ? 'pulse-dot text-[var(--color-success)]' : 'text-[var(--color-error)]'}`} />
        </div>
      </div>

      <div className="sidebar-footer">
        <button className="button-quiet w-full justify-start" onClick={onChangePatient}>
          <ListRestart size={17} /> Change patient
        </button>
      </div>
    </aside>
  );
};
