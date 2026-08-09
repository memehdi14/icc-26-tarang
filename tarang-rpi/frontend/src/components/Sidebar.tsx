"use client";

import Link from "next/link";
import { usePathname } from "next/navigation";
import { LayoutDashboard, History, MonitorSmartphone, Settings, UserCheck } from "lucide-react";

export function Sidebar() {
  const pathname = usePathname();

  const links = [
    { href: "/", label: "Dashboard", icon: LayoutDashboard },
    { href: "/history", label: "Session History", icon: History },
    { href: "/device", label: "Device Info", icon: MonitorSmartphone },
    { href: "/settings", label: "Settings", icon: Settings },
  ];

  return (
    <aside className="w-56 border-r border-slate-200 h-full flex flex-col shrink-0 font-sans text-xs bg-white text-slate-700 z-20">
      {/* Clinician Profile */}
      <div className="p-3.5 flex items-center border-b border-slate-200 bg-slate-50/50">
        <div className="w-8 h-8 rounded-full border border-slate-200 flex items-center justify-center mr-3 bg-white text-cyan-600 font-bold shrink-0 shadow-sm">
          <UserCheck className="w-4 h-4" />
        </div>
        <div className="flex flex-col min-w-0">
          <span className="text-slate-900 font-bold truncate text-xs">Dr. Sarah Connor</span>
          <span className="text-slate-500 text-[10px] truncate">Attending Physician</span>
        </div>
      </div>
      
      {/* Navigation Links */}
      <nav className="flex-1 py-4 space-y-1.5 px-3">
        {links.map((link) => {
          const Icon = link.icon;
          const isActive = pathname === link.href || (pathname === "/patients" && link.href === "/history"); 
          
          return (
            <Link
              key={link.href}
              href={link.href}
              className={`flex items-center px-3.5 py-2.5 rounded-xl transition-all text-xs font-semibold ${
                isActive 
                  ? "bg-cyan-600 text-white shadow-md shadow-cyan-600/20 font-bold" 
                  : "text-slate-600 hover:text-slate-900 hover:bg-slate-100"
              }`}
            >
              <Icon className={`w-4 h-4 mr-3 shrink-0 ${isActive ? "text-white" : "text-slate-500"}`} />
              <span className="truncate">{link.label}</span>
            </Link>
          );
        })}
      </nav>

      {/* Bottom Telemetry Footer */}
      <div className="p-3.5 border-t border-slate-200 space-y-2 text-[11px] text-slate-500 bg-slate-50/50">
        <div className="flex items-center justify-between text-[10px] text-slate-400 uppercase tracking-widest font-bold">
          <span>System Status</span>
          <span className="text-emerald-600 font-extrabold">ONLINE</span>
        </div>
        <div className="flex items-center text-slate-700 font-mono text-[10px]">
          <span className="w-1.5 h-1.5 rounded-full bg-emerald-500 mr-2 animate-pulse"></span>
          BLE Sensor Connected
        </div>
      </div>
    </aside>
  );
}

