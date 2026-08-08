export default function History() {
  return (
    <div className="flex flex-col h-full font-mono text-sm gap-4">
       <div className="border border-border bg-card p-6 flex flex-col min-h-0 h-full">
          <div className="flex justify-between items-center mb-8 border-b border-border pb-6">
             <div className="text-xl font-bold tracking-widest uppercase">Session History</div>
             <div className="flex gap-4">
                <button className="border border-border px-4 py-2 hover:bg-[#111] transition-colors text-xs text-muted hover:text-foreground">Filter</button>
                <button className="border border-border bg-foreground text-background font-bold px-4 py-2 text-xs">Export CSV</button>
             </div>
          </div>
          
          <div className="flex-1 flex flex-col items-center justify-center text-muted border border-dashed border-[#333]">
             <span className="text-4xl mb-4">⏱</span>
             <p className="tracking-widest uppercase text-xs">Select a session to view historical waveforms</p>
          </div>
       </div>
    </div>
  )
}
