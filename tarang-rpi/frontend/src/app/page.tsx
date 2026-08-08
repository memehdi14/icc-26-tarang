"use client";

import { useEffect, useState } from "react";
import { EChart } from "@/components/EChart";
import { Heart, Droplet, GitBranch, Maximize2, Minimize2 } from "lucide-react";

// Mock data generator for grid
const generateWaveData = (length: number, type: 'ecg_raw' | 'ecg_filt' | 'ppg') => {
  const data = [];
  for (let i = 0; i < length; i++) {
    if (type === 'ppg') {
      data.push(Math.sin(i / 10) * 20 + 50 + Math.random() * 2);
    } else {
      // simulate QRS complex periodically
      if (i % 80 > 75) {
         data.push(100);
      } else if (i % 80 > 73) {
         data.push(-20);
      } else {
         data.push(Math.sin(i / 5) * 5 + (type === 'ecg_raw' ? Math.random() * 8 : Math.random() * 2));
      }
    }
  }
  return data;
};

export default function Dashboard() {
  const [ecgRaw, setEcgRaw] = useState<number[]>([]);
  const [ecgFilt, setEcgFilt] = useState<number[]>([]);
  const [ppg, setPpg] = useState<number[]>([]);
  
  const [fullscreenGraph, setFullscreenGraph] = useState<string | null>(null);

  useEffect(() => {
    setEcgRaw(generateWaveData(200, 'ecg_raw'));
    setEcgFilt(generateWaveData(200, 'ecg_filt'));
    setPpg(generateWaveData(200, 'ppg'));
    
    const interval = setInterval(() => {
      setEcgRaw(prev => [...prev.slice(2), ...generateWaveData(2, 'ecg_raw')]);
      setEcgFilt(prev => [...prev.slice(2), ...generateWaveData(2, 'ecg_filt')]);
      setPpg(prev => [...prev.slice(2), ...generateWaveData(2, 'ppg')]);
    }, 100);
    return () => clearInterval(interval);
  }, []);

  const commonChartOptions = {
    animation: false,
    grid: { left: 0, right: 0, top: 0, bottom: 0 },
    xAxis: { type: "category", show: false, boundaryGap: false },
    yAxis: { type: "value", show: false, min: -30, max: 120 },
    tooltip: { show: false }
  };

  const getGridOptions = (data: number[]) => ({
    ...commonChartOptions,
    grid: { left: 0, right: 0, top: 0, bottom: 0 },
    xAxis: {
      type: "category",
      show: true,
      data: data.map((_, i) => i),
      axisLine: { show: false },
      axisTick: { show: false },
      axisLabel: { show: false },
      splitLine: { show: true, lineStyle: { color: '#222', type: 'solid', width: 1 } },
      boundaryGap: false
    },
    yAxis: {
      type: "value",
      show: true,
      min: -40,
      max: 120,
      axisLine: { show: false },
      axisTick: { show: false },
      axisLabel: { show: false },
      splitLine: { show: true, lineStyle: { color: '#222', type: 'solid', width: 1 } },
      splitNumber: 10
    },
    series: [{
      type: "line",
      data,
      showSymbol: false,
      lineStyle: { color: "#ffffff", width: fullscreenGraph ? 2.5 : 1.5 }
    }]
  });

  const ppgOptions = {
    ...commonChartOptions,
    yAxis: { type: "value", show: false, min: 20, max: 80 },
    series: [{
      type: "line",
      data: ppg,
      showSymbol: false,
      smooth: true,
      lineStyle: { color: "#ffffff", width: fullscreenGraph ? 3 : 2 }
    }]
  };

  const FullscreenOverlay = () => {
    if (!fullscreenGraph) return null;

    return (
      <div className="fixed inset-0 z-50 bg-background flex flex-col p-6">
        <div className="flex justify-between items-center mb-6 border-b border-border pb-4 shrink-0">
          <div className="text-foreground font-bold tracking-widest uppercase">Telemetry Waveforms (Fullscreen)</div>
          <button 
             onClick={() => setFullscreenGraph(null)}
             className="flex items-center text-muted hover:text-foreground transition-colors border border-border px-4 py-2 bg-card"
          >
             <Minimize2 className="w-5 h-5 mr-2" />
             Close Fullscreen
          </button>
        </div>
        <div className="flex-1 flex flex-col gap-6 min-h-0">
          <div className="flex-1 relative border border-border bg-card overflow-hidden">
             <div className="absolute top-0 left-0 right-0 px-4 py-3 text-xs text-muted z-10 font-bold bg-gradient-to-b from-card to-transparent pointer-events-none flex justify-between">
               <span>Lead I (Raw)</span>
               <span>10mm/mV 25mm/s</span>
             </div>
             <div className="w-full h-full">
               <EChart option={getGridOptions(ecgRaw)} />
             </div>
          </div>
          <div className="flex-1 relative border border-border bg-card overflow-hidden">
             <div className="absolute top-0 left-0 right-0 px-4 py-3 text-xs text-muted z-10 font-bold bg-gradient-to-b from-card to-transparent pointer-events-none flex justify-between">
               <span>Lead I (Filtered)</span>
               <span>10mm/mV 25mm/s</span>
             </div>
             <div className="w-full h-full">
               <EChart option={getGridOptions(ecgFilt)} />
             </div>
          </div>
          <div className="flex-1 relative border border-border bg-card overflow-hidden">
             <div className="absolute top-0 left-0 right-0 px-4 py-3 text-xs text-muted z-10 font-bold pointer-events-none flex justify-between">
               <span>PPG Waveform</span>
               <span>Auto Gain 25mm/s</span>
             </div>
             <div className="w-full h-full pt-4">
               <EChart option={ppgOptions} />
             </div>
          </div>
        </div>
      </div>
    );
  };

  return (
    <div className="flex flex-col h-full font-mono text-sm gap-4">
      <FullscreenOverlay />
      
      {/* Main Grid: Waveforms + Metrics */}
      <div className="flex-1 flex gap-4 min-h-0">
        
        {/* Waveforms Column */}
        <div className="flex-1 flex flex-col gap-4 min-w-0">
          
          {/* Lead I Raw */}
          <div className="flex-1 border border-border bg-card flex flex-col relative overflow-hidden group">
            <div className="absolute top-0 left-0 right-0 flex justify-between items-center px-4 py-3 text-xs text-muted z-10 font-bold bg-gradient-to-b from-card to-transparent pointer-events-none">
              <span>Lead I (Raw)</span>
              <div className="flex items-center pointer-events-auto">
                 <span className="mr-4">10mm/mV  25mm/s</span>
                 <button onClick={() => setFullscreenGraph("ecg_raw")} className="opacity-0 group-hover:opacity-100 transition-opacity p-1 bg-background border border-border hover:text-foreground">
                    <Maximize2 className="w-3.5 h-3.5" />
                 </button>
              </div>
            </div>
            <div className="flex-1 relative w-full h-full pointer-events-none">
               <EChart option={getGridOptions(ecgRaw)} />
            </div>
          </div>

          {/* Lead I Filtered */}
          <div className="flex-1 border border-border bg-card flex flex-col relative overflow-hidden group">
            <div className="absolute top-0 left-0 right-0 flex justify-between items-center px-4 py-3 text-xs text-muted z-10 font-bold bg-gradient-to-b from-card to-transparent pointer-events-none">
              <span>Lead I (Filtered)</span>
              <div className="flex items-center pointer-events-auto">
                 <span className="mr-4">10mm/mV  25mm/s</span>
                 <button onClick={() => setFullscreenGraph("ecg_filt")} className="opacity-0 group-hover:opacity-100 transition-opacity p-1 bg-background border border-border hover:text-foreground">
                    <Maximize2 className="w-3.5 h-3.5" />
                 </button>
              </div>
            </div>
            <div className="flex-1 relative w-full h-full pointer-events-none">
               <EChart option={getGridOptions(ecgFilt)} />
            </div>
          </div>

          {/* PPG */}
          <div className="flex-1 border border-border bg-card flex flex-col relative overflow-hidden group">
            <div className="absolute top-0 left-0 right-0 flex justify-between items-center px-4 py-3 text-xs text-muted z-10 font-bold pointer-events-none">
              <span>PPG Waveform</span>
              <div className="flex items-center pointer-events-auto">
                 <span className="mr-4">Auto Gain  25mm/s</span>
                 <button onClick={() => setFullscreenGraph("ppg")} className="opacity-0 group-hover:opacity-100 transition-opacity p-1 bg-background border border-border hover:text-foreground">
                    <Maximize2 className="w-3.5 h-3.5" />
                 </button>
              </div>
            </div>
            <div className="flex-1 relative w-full h-full mt-4 pointer-events-none">
               <EChart option={ppgOptions} />
            </div>
          </div>

        </div>

        {/* Metrics Column */}
        <div className="w-[320px] flex flex-col gap-4 shrink-0">
          
          {/* HR */}
          <div className="h-56 border border-border bg-card p-6 flex flex-col justify-between">
            <div className="flex justify-between items-center text-muted text-xs">
              <span>Heart Rate</span>
              <Heart className="w-4 h-4" />
            </div>
            <div className="flex items-baseline mt-4">
              <span className="text-7xl font-bold tracking-tighter text-foreground leading-none">72</span>
              <span className="text-muted ml-3 text-xs">bpm</span>
            </div>
            <div className="w-full bg-[#222] h-1.5 mt-auto">
               <div className="bg-foreground h-1.5 w-[60%]"></div>
            </div>
          </div>

          {/* SpO2 */}
          <div className="h-56 border border-border bg-card p-6 flex flex-col justify-between">
            <div className="flex justify-between items-center text-muted text-xs">
              <span>SpO2</span>
              <Droplet className="w-4 h-4" />
            </div>
            <div className="flex items-baseline mt-4">
              <span className="text-7xl font-bold tracking-tighter text-foreground leading-none">98</span>
              <span className="text-muted ml-3 text-xs">%</span>
            </div>
            <div className="w-full bg-[#222] h-1.5 mt-auto">
               <div className="bg-foreground h-1.5 w-[98%]"></div>
            </div>
          </div>

          {/* Clinical */}
          <div className="flex-1 border border-border bg-card p-6 flex flex-col">
            <div className="flex justify-between items-start mb-8">
              <span className="text-muted text-xs w-16 leading-tight">Clinical<br/>Alerts</span>
              <div className="flex gap-2 text-[10px] font-bold tracking-widest">
                <span className="border border-border px-2.5 py-1 text-muted">AFIB</span>
                <span className="border border-border bg-foreground text-background px-2.5 py-1">PVC</span>
                <span className="border border-border px-2.5 py-1 text-muted">BIGEM</span>
              </div>
            </div>

            <div className="mt-auto mb-8">
              <span className="text-muted text-xs block mb-2">Current Rhythm</span>
              <span className="text-2xl font-bold text-foreground">Normal Sinus</span>
            </div>

            <div className="mt-auto">
              <div className="flex justify-between text-xs text-muted mb-3 font-bold">
                <span>AI Confidence</span>
                <span className="text-foreground">99.6%</span>
              </div>
              <div className="w-full bg-[#222] h-1.5">
                 <div className="bg-foreground h-1.5 w-[99.6%]"></div>
              </div>
            </div>
          </div>

        </div>
      </div>

      {/* Timeline Bottom Bar */}
      <div className="h-[72px] border border-border bg-card shrink-0 flex items-center px-6 relative">
        <GitBranch className="w-4 h-4 text-muted shrink-0" />
        <div className="flex-1 ml-12 flex flex-col justify-center h-full">
           <div className="w-full h-px bg-[#333] relative">
             <div className="absolute top-1/2 -translate-y-1/2 left-[20%] w-2.5 h-2.5 rounded-full bg-foreground"></div>
             <div className="absolute top-1/2 -translate-y-1/2 left-[60%] w-2.5 h-2.5 rounded-full bg-[#555]"></div>
             <div className="absolute top-1/2 -translate-y-1/2 left-[85%] w-2.5 h-2.5 rounded-full bg-foreground shadow-[0_0_8px_rgba(255,255,255,0.8)]"></div>
           </div>
           <div className="flex justify-between w-full text-[11px] text-muted mt-3 font-bold">
             <span>10:00</span>
             <span>10:30</span>
             <span>11:00 (Now)</span>
           </div>
        </div>
      </div>
    </div>
  );
}
