'use client';

import React from 'react';
import {
  Activity,
  Cable,
  ChevronLeft,
  ChevronRight,
  ListRestart,
  Radio,
  Settings,
  UsersRound,
} from 'lucide-react';

interface SidebarProps {
  activeTab: 'workstation' | 'diagnostics' | 'settings';
  setActiveTab: (tab: 'workstation' | 'diagnostics' | 'settings') => void;
  bleConnected: boolean;
  patientName: string;
  attendingDoctor: string;
  onChangePatient: () => void;
  collapsed?: boolean;
  onToggleCollapse?: () => void;
}

export const Sidebar: React.FC<SidebarProps> = ({
  activeTab,
  setActiveTab,
  bleConnected,
  patientName,
  attendingDoctor,
  onChangePatient,
  collapsed = false,
  onToggleCollapse,
}) => {
  const initials = attendingDoctor
    .split(/\s+/)
    .filter(Boolean)
    .map((part) => part[0])
    .join('')
    .slice(0, 2)
    .toUpperCase() || 'DR';

  return (
    <aside className={`app-sidebar ${collapsed ? 'app-sidebar--collapsed' : ''}`} aria-label="Clinical workstation navigation">
      <div className="sidebar-clinician">
        <div className="sidebar-avatar" title={`Attending: ${attendingDoctor}`}>{initials}</div>
        {!collapsed && (
          <div className="min-w-0">
            <p className="truncate text-xs font-bold text-[var(--ink)]">{attendingDoctor}</p>
            <p className="truncate text-[11px] text-[var(--muted)]">Attending Physician</p>
          </div>
        )}
      </div>

      <nav className="sidebar-nav">
        <button
          className={activeTab === 'workstation' ? 'is-active' : ''}
          onClick={() => setActiveTab('workstation')}
          title="Dashboard"
        >
          <Activity size={18} strokeWidth={1.8} className={activeTab === 'workstation' ? 'text-[var(--accent)]' : ''} />
          <span>Dashboard</span>
        </button>
        <button onClick={onChangePatient} title="Patient Worklist">
          <UsersRound size={18} strokeWidth={1.8} />
          <span>Patient Worklist</span>
        </button>
        <button
          className={activeTab === 'diagnostics' ? 'is-active' : ''}
          onClick={() => setActiveTab('diagnostics')}
          title="Diagnostics"
        >
          <Cable size={18} strokeWidth={1.8} className={activeTab === 'diagnostics' ? 'text-[var(--accent)]' : ''} />
          <span>Diagnostics</span>
        </button>
        <button
          className={activeTab === 'settings' ? 'is-active' : ''}
          onClick={() => setActiveTab('settings')}
          title="Settings"
        >
          <Settings size={18} strokeWidth={1.8} className={activeTab === 'settings' ? 'text-[var(--accent)]' : ''} />
          <span>Settings</span>
        </button>
      </nav>

      {!collapsed && (
        <div className="sidebar-status">
          <div className="flex items-center justify-between gap-3">
            <div className="flex min-w-0 items-center gap-2">
              <Radio size={15} className={bleConnected ? 'text-[var(--clinical-teal)]' : 'text-[var(--amber-alert)]'} />
              <div className="min-w-0">
                <p className="truncate text-xs font-bold text-[var(--ink)]">{bleConnected ? 'EFR32MG26 Linked' : 'Bluetooth Scanning'}</p>
                <p className="truncate font-mono text-[9px] text-[var(--muted)]">
                  {bleConnected ? 'AES-128 Encrypted' : 'Searching for pod'}
                </p>
              </div>
            </div>
            <span className={`h-2 w-2 rounded-full ${bleConnected ? 'bg-[var(--clinical-teal)] animate-ping' : 'bg-[var(--amber-alert)]'}`} />
          </div>
        </div>
      )}

      <div className="sidebar-footer">
        <button
          className="button-quiet w-full justify-start !text-[11px]"
          onClick={onChangePatient}
          title="Switch Patient"
        >
          <ListRestart size={15} />
          <span>Switch Patient</span>
        </button>

        {onToggleCollapse && (
          <button
            className="button-quiet mt-1 w-full justify-start !text-[11px] hover:bg-[var(--paper)]"
            onClick={onToggleCollapse}
            title={collapsed ? 'Expand sidebar' : 'Retract sidebar'}
          >
            {collapsed ? <ChevronRight size={15} /> : <ChevronLeft size={15} />}
            <span>{collapsed ? 'Expand' : 'Retract sidebar'}</span>
          </button>
        )}

        {!collapsed && (
          <div className="mt-2.5 flex items-center justify-between border-t border-[var(--line-soft)] pt-2.5 px-1 opacity-80">
            <img src="/images/ocelleon-logo.png" alt="Ocelleon" className="h-4 w-auto object-contain" />
            <span className="font-mono text-[9px] text-[var(--muted)]">v2.4.0 • EFR32</span>
          </div>
        )}
      </div>
    </aside>
  );
};
