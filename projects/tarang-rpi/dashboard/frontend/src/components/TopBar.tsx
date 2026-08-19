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
      <img src="/tarang_logo.png" alt="" />
      <span>Tarang Clinical</span>
    </div>

    <div className="topbar-context" aria-label="Current clinical context">
      <button className="topbar-context-item is-active" onClick={onOpenWorkstation}>Patient context</button>
      <span className="topbar-context-item">Room {patient.bed}</span>
      <span className="topbar-context-item">Critical care</span>
      <span className="topbar-context-item font-mono" title="Backend and device link status">
        <Radio size={15} />&nbsp;{backendOnline && bleConnected ? 'Live telemetry' : 'Link pending'}
      </span>
    </div>

    <div className="topbar-actions">
      <button
        className="emergency-button"
        onClick={onEmergency}
        disabled={pageBusy}
        title="Page the duty physician"
      >
        <AlertTriangle size={17} />
        <span>{pageBusy ? 'Paging...' : 'Emergency alert'}</span>
      </button>
      <button className="icon-button" onClick={onOpenWorkstation} title="Open clinical events" aria-label="Open clinical events">
        <Bell size={20} />
      </button>
      <button className="icon-button profile-button" onClick={onOpenSettings} title="Open clinician settings" aria-label="Open clinician settings">
        <CircleUserRound size={22} />
      </button>
    </div>
  </header>
);
