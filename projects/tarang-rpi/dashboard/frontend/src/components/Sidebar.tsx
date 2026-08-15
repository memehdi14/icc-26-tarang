'use client';

import React from 'react';
import { Activity, ShieldCheck, Settings, UserCheck, Wifi, Radio } from 'lucide-react';

interface SidebarProps {
  activeTab: 'workstation' | 'diagnostics' | 'settings';
  setActiveTab: (tab: 'workstation' | 'diagnostics' | 'settings') => void;
  bleConnected: boolean;
}

export const Sidebar: React.FC<SidebarProps> = ({ activeTab, setActiveTab, bleConnected }) => {
  return (
    <aside style={{ width: '256px', backgroundColor: 'var(--color-surface-container-lowest)', borderRight: '1px solid var(--color-outline-variant)' }} className="flex flex-col h-screen fixed left-0 top-0 z-30 select-none">
      {/* Brand Header */}
      <div className="p-4 border-b border-[var(--color-outline-variant)] flex items-center gap-3">
        <img src="/tarang_logo.png" alt="Tarang Clinical Logo" className="w-10 h-10 object-contain" />
        <div>
          <div className="flex items-center gap-1">
            <span className="font-extrabold text-lg text-[var(--color-on-surface)] tracking-tight">TARANG</span>
            <span className="font-semibold text-lg text-[var(--color-primary)]">CLINICAL</span>
          </div>
          <p className="text-[10px] font-mono text-[var(--color-on-surface-variant)] tracking-wider">ICU TELEMETRY WORKSTATION</p>
        </div>
      </div>

      {/* Main Navigation */}
      <nav className="flex-1 p-3 space-y-1">
        <button
          onClick={() => setActiveTab('workstation')}
          style={{
            backgroundColor: activeTab === 'workstation' ? 'var(--color-surface-container-high)' : 'transparent',
            color: activeTab === 'workstation' ? 'var(--color-primary)' : 'var(--color-on-surface-variant)'
          }}
          className="w-full flex items-center gap-3 px-4 py-3 rounded-lg text-sm font-semibold transition-colors hover:bg-[var(--color-surface-container)]"
        >
          <Activity className="w-5 h-5" />
          <span>Workstation</span>
        </button>

        <button
          onClick={() => setActiveTab('diagnostics')}
          style={{
            backgroundColor: activeTab === 'diagnostics' ? 'var(--color-surface-container-high)' : 'transparent',
            color: activeTab === 'diagnostics' ? 'var(--color-primary)' : 'var(--color-on-surface-variant)'
          }}
          className="w-full flex items-center gap-3 px-4 py-3 rounded-lg text-sm font-semibold transition-colors hover:bg-[var(--color-surface-container)]"
        >
          <ShieldCheck className="w-5 h-5" />
          <span>Device Diagnostics</span>
        </button>

        <button
          onClick={() => setActiveTab('settings')}
          style={{
            backgroundColor: activeTab === 'settings' ? 'var(--color-surface-container-high)' : 'transparent',
            color: activeTab === 'settings' ? 'var(--color-primary)' : 'var(--color-on-surface-variant)'
          }}
          className="w-full flex items-center gap-3 px-4 py-3 rounded-lg text-sm font-semibold transition-colors hover:bg-[var(--color-surface-container)]"
        >
          <Settings className="w-5 h-5" />
          <span>System Settings</span>
        </button>
      </nav>

      {/* BLE Connection Status Pill */}
      <div className="p-3 border-t border-[var(--color-outline-variant)]">
        <div style={{ backgroundColor: bleConnected ? '#e6f7f5' : '#fee2e2', borderColor: bleConnected ? '#85d5c9' : '#fca5a5' }} className="p-3 rounded-lg border flex items-center justify-between text-xs">
          <div className="flex items-center gap-2">
            <Radio className={`w-4 h-4 ${bleConnected ? 'text-[var(--color-primary)] animate-pulse' : 'text-[var(--color-error)]'}`} />
            <div>
              <p className="font-bold text-[var(--color-on-surface)]">{bleConnected ? 'EFR32 Connected' : 'BLE Disconnected'}</p>
              <p className="text-[10px] font-mono text-[var(--color-on-surface-variant)]">{bleConnected ? '20ms int / 1Hz sync' : 'Searching for device...'}</p>
            </div>
          </div>
          <span className={`w-2.5 h-2.5 rounded-full ${bleConnected ? 'bg-[var(--color-primary-container)] pulse-dot' : 'bg-[var(--color-error)]'}`}></span>
        </div>
      </div>

      {/* Doctor User Footer */}
      <div className="p-4 border-t border-[var(--color-outline-variant)] bg-[var(--color-surface-container-low)] flex items-center gap-3">
        <div className="w-9 h-9 rounded-full bg-[var(--color-primary)] text-white flex items-center justify-center font-bold text-sm">
          DA
        </div>
        <div className="flex-1 min-w-0">
          <p className="text-sm font-bold text-[var(--color-on-surface)] truncate">Dr. Aris</p>
          <p className="text-[11px] text-[var(--color-on-surface-variant)] truncate">ICU Lead Cardiologist</p>
        </div>
        <UserCheck className="w-4 h-4 text-[var(--color-primary)]" />
      </div>
    </aside>
  );
};
