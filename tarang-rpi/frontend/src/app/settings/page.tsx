export default function Settings() {
  return (
    <div className="flex flex-col h-full font-mono text-sm gap-4">
       <div className="border border-border bg-card p-6 flex flex-col min-h-0 h-full">
          <div className="mb-8 border-b border-border pb-6 flex justify-between items-center">
             <div className="text-xl font-bold tracking-widest uppercase">System Settings</div>
             <button className="border border-border bg-foreground text-background font-bold px-6 py-2 text-xs">Save Configuration</button>
          </div>
          
          <div className="max-w-2xl space-y-10">
             
             <div className="space-y-4">
                <h3 className="text-foreground border-b border-border pb-2 uppercase tracking-widest text-xs">BLE Gateway Options</h3>
                <div className="grid grid-cols-2 gap-6">
                   <div className="space-y-2">
                      <label className="text-muted text-xs">Scan Timeout (s)</label>
                      <input type="text" defaultValue="10" className="w-full bg-background border border-border p-3 text-foreground focus:outline-none focus:border-[#555]" />
                   </div>
                   <div className="space-y-2">
                      <label className="text-muted text-xs">Auto-Reconnect</label>
                      <select className="w-full bg-background border border-border p-3 text-foreground focus:outline-none focus:border-[#555]">
                         <option>Enabled</option>
                         <option>Disabled</option>
                      </select>
                   </div>
                </div>
             </div>

             <div className="space-y-4">
                <h3 className="text-foreground border-b border-border pb-2 uppercase tracking-widest text-xs">Alert Rules</h3>
                <div className="space-y-4">
                   <div className="flex items-center justify-between">
                      <span className="text-muted">High Heart Rate Threshold (bpm)</span>
                      <input type="text" defaultValue="120" className="w-24 bg-background border border-border p-2 text-foreground focus:outline-none focus:border-[#555] text-center" />
                   </div>
                   <div className="flex items-center justify-between">
                      <span className="text-muted">Low SpO2 Threshold (%)</span>
                      <input type="text" defaultValue="92" className="w-24 bg-background border border-border p-2 text-foreground focus:outline-none focus:border-[#555] text-center" />
                   </div>
                </div>
             </div>

          </div>
       </div>
    </div>
  )
}
