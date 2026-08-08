"use client";

import Link from "next/link";
import { usePathname } from "next/navigation";
import { LayoutDashboard, History, MonitorSmartphone, Settings, Menu, Bluetooth, BatteryCharging, Wifi } from "lucide-react";

export function Sidebar() {
  const pathname = usePathname();

  const links = [
    { href: "/", label: "Dashboard", icon: LayoutDashboard },
    { href: "/history", label: "Session History", icon: History },
    { href: "/device", label: "Device Info", icon: MonitorSmartphone },
    { href: "/settings", label: "Settings", icon: Settings },
  ];

  return (
    <aside className="w-[260px] border-r border-border h-full flex flex-col shrink-0 font-mono text-sm bg-background">
      {/* Top Sidebar section */}
      <div className="p-5 flex items-center border-b border-border">
        <Menu className="w-5 h-5 text-muted mr-4" />
        <div className="flex items-center">
          <div className="w-8 h-8 rounded-full border border-border flex items-center justify-center mr-3 bg-card text-muted">
            👤
          </div>
          <div className="flex flex-col">
            <span className="text-foreground font-bold text-xs">Dr. Sarah Connor</span>
            <span className="text-muted text-[10px]">City General Hospital</span>
          </div>
        </div>
      </div>
      
      {/* Nav Links */}
      <nav className="flex-1 py-4 space-y-1">
        {links.map((link) => {
          const Icon = link.icon;
          const isActive = pathname === link.href || (pathname === "/patients" && link.href === "/history"); 
          
          return (
            <Link
              key={link.href}
              href={link.href}
              className={`flex items-center px-6 py-3 mx-4 transition-colors text-[13px] ${
                isActive 
                  ? "bg-foreground text-background font-bold rounded" 
                  : "text-muted hover:text-foreground"
              }`}
            >
              <Icon className="w-4 h-4 mr-4 shrink-0" />
              <span>{link.label}</span>
            </Link>
          );
        })}
      </nav>

      {/* Bottom Status */}
      <div className="p-6 border-t border-border space-y-4 text-xs text-muted">
        <div className="flex items-center">
          <Bluetooth className="w-3.5 h-3.5 mr-3 text-foreground" />
          BLE Active
        </div>
        <div className="flex items-center">
          <BatteryCharging className="w-3.5 h-3.5 mr-3 text-foreground" />
          98% Battery
        </div>
        <div className="flex items-center">
          <Wifi className="w-3.5 h-3.5 mr-3 text-foreground" />
          Connected
        </div>
      </div>
    </aside>
  );
}
