import { Activity, Battery, Clock, Settings, Zap } from "lucide-react";

export function TopBar() {
  return (
    <header className="h-20 border-b border-border flex items-center px-4 shrink-0 text-xs text-muted font-mono tracking-wide z-10 bg-background">
      {/* Logo Area */}
      <div className="flex items-center shrink-0 pr-6">
        <img src="/logo.png" alt="Tarang Logo" className="h-16 w-auto object-contain brightness-0 invert" />
      </div>
      
      {/* Divider */}
      <div className="h-12 w-px bg-border mx-2"></div>
      
      {/* Patient Info */}
      <div className="flex flex-1 items-center space-x-6 pl-4">
        <div className="flex items-center text-foreground">
          <span className="mr-2 border rounded-full p-0.5 border-border">👤</span>
          John Doe
        </div>
        <div>ID: 4502931</div>
        <div>DOB: 11/24/1985</div>
        <div>Room: ICU-04</div>
        <div className="flex items-center text-foreground">
          <div className="w-2 h-2 rounded-full bg-white mr-2"></div>
          Active
        </div>
        <div className="flex items-center">
          <Clock className="w-3.5 h-3.5 mr-2" />
          02:45:11
        </div>
        <div>Sess: #8821</div>
      </div>
      
      {/* Icons Right */}
      <div className="flex items-center space-x-6 text-muted">
        <Activity className="w-4 h-4" />
        <Zap className="w-4 h-4" />
        <Settings className="w-4 h-4" />
        <div className="flex items-center">
          <Battery className="w-4 h-4 mr-1 text-foreground" />
          <span className="text-foreground">84%</span>
        </div>
        <Clock className="w-4 h-4" />
      </div>
    </header>
  );
}
