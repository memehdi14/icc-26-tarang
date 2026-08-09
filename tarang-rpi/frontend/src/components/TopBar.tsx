"use client";

import { Activity, Battery, Clock, Settings, Zap, Bell, ShieldAlert, Wifi } from "lucide-react";
import { useEffect, useState } from "react";

export function TopBar() {
  const [time, setTime] = useState<string>("");

  useEffect(() => {
    setTime(new Date().toLocaleTimeString('en-US', { hour12: false, hour: '2-digit', minute: '2-digit', second: '2-digit' }));
    const timer = setInterval(() => {
      setTime(new Date().toLocaleTimeString('en-US', { hour12: false, hour: '2-digit', minute: '2-digit', second: '2-digit' }));
    }, 1000);
    return () => clearInterval(timer);
  }, []);

  return (
    <header className="h-14 border-b border-slate-200 flex items-center px-4 shrink-0 text-xs font-mono tracking-wide z-30 bg-white text-slate-800 shadow-sm">
      {/* Brand & Logo Area */}
      <div className="flex items-center shrink-0 pr-4 space-x-3">
        <div className="w-8 h-8 rounded-lg bg-gradient-to-br from-cyan-600 to-blue-700 flex items-center justify-center shadow-md shadow-cyan-600/20">
          <Activity className="w-5 h-5 text-white" />
        </div>
        <div className="flex flex-col">
          <span className="font-extrabold tracking-wider text-slate-900 text-sm font-sans">TARANG</span>
          <span className="text-[9px] text-cyan-600 font-bold tracking-widest uppercase">Edge AI Telemetry</span>
        </div>
      </div>
      
      {/* Divider */}
      <div className="h-6 w-px bg-slate-200 mx-3"></div>
      
      {/* Active Device & Telemetry Node Info */}
      <div className="flex flex-1 items-center space-x-5 pl-2">
        <div className="flex items-center space-x-2 bg-slate-50 border border-slate-200 px-2.5 py-1 rounded-md text-slate-700">
          <span className="relative flex h-2 w-2">
            <span className="animate-ping absolute inline-flex h-full w-full rounded-full bg-emerald-400 opacity-75"></span>
            <span className="relative inline-flex rounded-full h-2 w-2 bg-emerald-500"></span>
          </span>
          <span className="font-semibold text-xs text-slate-800 font-sans">EFR32MG26 BLE</span>
        </div>
      </div>
      
      {/* Right Controls & Telemetry Status */}
      <div className="flex items-center space-x-3 text-slate-600 font-sans">
        <div className="flex items-center space-x-1.5 bg-emerald-50 border border-emerald-200 px-2.5 py-1 rounded-md text-emerald-800 font-semibold text-xs">
          <Zap className="w-3.5 h-3.5 text-emerald-600" />
          <span>AI Monitoring Active</span>
        </div>

        <div className="flex items-center space-x-1 text-slate-800 bg-slate-100 border border-slate-200 px-2.5 py-1 rounded-md">
          <Battery className="w-4 h-4 text-emerald-600" />
          <span className="font-bold tabular-nums">98%</span>
        </div>

        <div className="flex items-center space-x-1.5 text-slate-900 font-bold bg-slate-100 border border-slate-200 px-3 py-1 rounded-md tabular-nums text-xs">
          <Clock className="w-3.5 h-3.5 text-cyan-600" />
          <span>{time || "00:00:00"}</span>
        </div>

        <button title="Notifications" className="p-1.5 rounded-md hover:bg-slate-100 text-slate-500 hover:text-slate-900 transition-colors border border-slate-200">
          <Bell className="w-4 h-4" />
        </button>
      </div>
    </header>
  );
}

