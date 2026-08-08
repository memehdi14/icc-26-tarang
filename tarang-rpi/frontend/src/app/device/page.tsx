import { MonitorSmartphone, Activity } from "lucide-react";

export default function Device() {
  return (
    <div className="flex flex-col h-full font-mono text-sm gap-4">
       <div className="border border-border bg-card p-6 flex flex-col min-h-0 h-full">
          <div className="mb-8 border-b border-border pb-6">
             <div className="text-xl font-bold tracking-widest uppercase">Device Info</div>
             <div className="text-xs text-muted mt-2">Hardware and telemetry status</div>
          </div>
          
          <div className="grid grid-cols-2 gap-8">
             <div className="space-y-6">
                <div>
                   <h3 className="text-muted text-xs uppercase mb-2">Connected Wearable</h3>
                   <div className="flex items-center text-foreground font-bold text-lg">
                      <MonitorSmartphone className="w-5 h-5 mr-3" /> EFR32MG26 Node
                   </div>
                </div>
                <div>
                   <h3 className="text-muted text-xs uppercase mb-2">MAC Address</h3>
                   <div className="text-foreground font-mono">00:1A:7D:DA:71:13</div>
                </div>
                <div>
                   <h3 className="text-muted text-xs uppercase mb-2">Firmware Version</h3>
                   <div className="text-foreground font-mono">v1.2.4 (Latest)</div>
                </div>
             </div>

             <div className="space-y-6">
                <div>
                   <h3 className="text-muted text-xs uppercase mb-2">Sensor Status</h3>
                   <div className="space-y-3">
                      <div className="flex justify-between items-center border-b border-border pb-2">
                         <span className="flex items-center"><Activity className="w-4 h-4 mr-2" /> ECG (MAX30001)</span>
                         <span className="text-foreground bg-[#222] px-2 py-1 text-xs">Active (250Hz)</span>
                      </div>
                      <div className="flex justify-between items-center border-b border-border pb-2">
                         <span className="flex items-center"><Activity className="w-4 h-4 mr-2" /> PPG (MAX30102)</span>
                         <span className="text-foreground bg-[#222] px-2 py-1 text-xs">Active (100Hz)</span>
                      </div>
                   </div>
                </div>
             </div>
          </div>
       </div>
    </div>
  )
}
