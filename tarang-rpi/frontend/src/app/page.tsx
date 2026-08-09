"use client";

import React, { useState, useEffect } from 'react';
import { EChart } from "@/components/EChart";
import { 
  Activity, 
  ArrowUp, 
  ArrowDown, 
  Stethoscope, 
  Maximize2, 
  Minimize2, 
  Sparkles,
  Sliders
} from 'lucide-react';

const cn = (...classes: (string | boolean | undefined | null)[]) => classes.filter(Boolean).join(' ');

// Mock real-time waveform generator
const generateWaveData = (length: number, type: 'ecg_raw' | 'ecg_filt' | 'ppg') => {
  const data = [];
  for (let i = 0; i < length; i++) {
    if (type === 'ppg') {
      data.push(Math.sin(i / 8) * 25 + 50 + Math.random() * 3);
    } else {
      // QRS Complex pulse
      if (i % 75 > 71) {
        data.push(110);
      } else if (i % 75 > 69) {
        data.push(-25);
      } else {
        data.push(Math.sin(i / 4) * 6 + (type === 'ecg_raw' ? Math.random() * 10 : Math.random() * 2));
      }
    }
  }
  return data;
};

// Patient Demographics
const PATIENT_DATA = {
  name: "Sarah Jenkins",
  age: "45Y",
  dob: "1978-04-12",
  mrn: "MRN-998-2144",
  sex: "Female",
  weight: "68 kg",
  height: "165 cm",
  attending: "Dr. Sarah Connor"
};

export default function ClinicalDashboard() {
  const [ecgRaw, setEcgRaw] = useState<number[]>([]);
  const [ecgFilt, setEcgFilt] = useState<number[]>([]);
  const [ppg, setPpg] = useState<number[]>([]);
  const [fullscreenGraph, setFullscreenGraph] = useState<string | null>(null);

  // Stream real-time telemetry waveforms
  useEffect(() => {
    setEcgRaw(generateWaveData(250, 'ecg_raw'));
    setEcgFilt(generateWaveData(250, 'ecg_filt'));
    setPpg(generateWaveData(250, 'ppg'));
    
    const interval = setInterval(() => {
      setEcgRaw(prev => [...prev.slice(3), ...generateWaveData(3, 'ecg_raw')]);
      setEcgFilt(prev => [...prev.slice(3), ...generateWaveData(3, 'ecg_filt')]);
      setPpg(prev => [...prev.slice(3), ...generateWaveData(3, 'ppg')]);
    }, 90);
    return () => clearInterval(interval);
  }, []);

  // ECharts waveform options
  const commonChartOptions = {
    animation: false,
    grid: { left: 0, right: 0, top: 0, bottom: 0 },
    xAxis: { type: "category" as const, show: false, boundaryGap: false },
    yAxis: { type: "value" as const, show: false, min: -35, max: 130 },
    tooltip: { show: false }
  };

  const getEcgGridOption = (data: number[], strokeColor = "#38bdf8") => ({
    ...commonChartOptions,
    xAxis: {
      type: "category" as const,
      show: true,
      data: data.map((_, i) => i),
      axisLine: { show: false },
      axisTick: { show: false },
      axisLabel: { show: false },
      splitLine: { show: true, lineStyle: { color: 'rgba(30, 41, 59, 0.4)', type: 'solid' as const, width: 1 } },
      boundaryGap: false
    },
    yAxis: {
      type: "value" as const,
      show: true,
      min: -40,
      max: 130,
      axisLine: { show: false },
      axisTick: { show: false },
      axisLabel: { show: false },
      splitLine: { show: true, lineStyle: { color: 'rgba(30, 41, 59, 0.4)', type: 'solid' as const, width: 1 } },
      splitNumber: 6
    },
    series: [{
      type: "line" as const,
      data,
      showSymbol: false,
      lineStyle: { color: strokeColor, width: fullscreenGraph ? 2.5 : 1.8 }
    }]
  });

  const getPpgOption = (data: number[]) => ({
    ...commonChartOptions,
    yAxis: { type: "value" as const, show: false, min: 15, max: 85 },
    series: [{
      type: "line" as const,
      data,
      showSymbol: false,
      smooth: true,
      lineStyle: { color: "#34d399", width: fullscreenGraph ? 3 : 2 }
    }]
  });

  return (
    <div className="h-full w-full bg-[#F8FAFC] text-slate-900 font-sans flex flex-col justify-between overflow-hidden selection:bg-cyan-500/20">
      
      {/* Fullscreen Telemetry Waveform Overlay Modal */}
      {fullscreenGraph && (
        <div className="fixed inset-0 z-50 bg-[#090D16] text-slate-100 flex flex-col p-6 space-y-4">
          <div className="flex justify-between items-center border-b border-slate-800 pb-4">
            <div className="flex items-center space-x-3">
              <Activity className="w-6 h-6 text-cyan-400 animate-pulse" />
              <h2 className="text-lg font-bold text-slate-100 tracking-wide uppercase">
                High-Resolution Telemetry Waveforms (Fullscreen)
              </h2>
            </div>
            <button 
              onClick={() => setFullscreenGraph(null)}
              className="flex items-center px-4 py-2 bg-slate-800 hover:bg-slate-700 text-slate-200 rounded-lg transition-colors border border-slate-700 font-semibold text-xs"
            >
              <Minimize2 className="w-4 h-4 mr-2" /> Close Fullscreen
            </button>
          </div>

          <div className="flex-1 grid grid-rows-3 gap-4 min-h-0">
            <div className="bg-slate-950/80 border border-slate-800 rounded-xl p-4 flex flex-col relative overflow-hidden">
              <div className="flex justify-between text-xs text-slate-400 font-mono mb-2">
                <span className="text-cyan-400 font-bold">ECG Lead I (Raw Unfiltered)</span>
                <span>Gain: 10mm/mV • Speed: 25mm/s • Rate: 250Hz</span>
              </div>
              <div className="flex-1 w-full h-full">
                <EChart option={getEcgGridOption(ecgRaw, "#00f2fe")} />
              </div>
            </div>

            <div className="bg-slate-950/80 border border-slate-800 rounded-xl p-4 flex flex-col relative overflow-hidden">
              <div className="flex justify-between text-xs text-slate-400 font-mono mb-2">
                <span className="text-blue-400 font-bold">ECG Lead I (DSP Filtered)</span>
                <span>Bandpass Filter 0.5-40Hz • QRS Detection Active</span>
              </div>
              <div className="flex-1 w-full h-full">
                <EChart option={getEcgGridOption(ecgFilt, "#38bdf8")} />
              </div>
            </div>

            <div className="bg-slate-950/80 border border-slate-800 rounded-xl p-4 flex flex-col relative overflow-hidden">
              <div className="flex justify-between text-xs text-slate-400 font-mono mb-2">
                <span className="text-emerald-400 font-bold">PPG Plethysmograph Waveform</span>
                <span>Auto Gain Control • SpO2 Pulse Sync</span>
              </div>
              <div className="flex-1 w-full h-full">
                <EChart option={getPpgOption(ppg)} />
              </div>
            </div>
          </div>
        </div>
      )}

      {/* 1. TOP PATIENT HEADER BANNER */}
      <section className="bg-white border-b border-slate-200/80 px-6 py-3 shrink-0 shadow-sm">
        <div className="w-full flex items-center justify-between">
          
          {/* Patient Details */}
          <div className="flex items-center space-x-4">
            <div className="w-10 h-10 rounded-xl bg-gradient-to-br from-cyan-600 to-blue-700 flex items-center justify-center font-extrabold text-sm text-white shadow-sm shadow-cyan-600/20 shrink-0">
              SJ
            </div>
            <div>
              <div className="flex items-center space-x-2">
                <h1 className="text-xl font-extrabold text-slate-900 tracking-tight">{PATIENT_DATA.name}</h1>
                <span className="bg-slate-100 text-slate-700 text-xs px-2.5 py-0.5 rounded-md font-mono font-bold border border-slate-200">
                  {PATIENT_DATA.age} • {PATIENT_DATA.sex}
                </span>
                <span className="text-xs text-slate-500 font-mono font-semibold ml-2">{PATIENT_DATA.mrn}</span>
              </div>
              <div className="flex items-center text-xs text-slate-500 mt-0.5 space-x-3 font-medium">
                <span>DOB: {PATIENT_DATA.dob}</span>
                <span>•</span>
                <span>Ht/Wt: {PATIENT_DATA.height} / {PATIENT_DATA.weight}</span>
              </div>
            </div>
          </div>

          {/* Right Status Controls */}
          <div className="flex items-center space-x-3">
            <span className="inline-flex items-center px-3 py-1 rounded-lg text-xs font-semibold bg-[#FEF2F2] text-[#DC2626] border border-[#FECACA] shadow-xs animate-pulse">
              <span className="w-2 h-2 rounded-full bg-[#EF4444] mr-2"></span>
              Live Telemetry Active
            </span>
            <button 
              onClick={() => setFullscreenGraph("ecg_raw")}
              className="flex items-center space-x-1.5 px-3 py-1.5 bg-slate-900 hover:bg-slate-800 text-white rounded-xl text-xs font-bold transition-all shadow-sm"
            >
              <Maximize2 className="w-3.5 h-3.5 text-cyan-400" />
              <span>Fullscreen Telemetry</span>
            </button>
          </div>

        </div>
      </section>

      {/* 2. MAIN DASHBOARD BODY (FIT ALL REMAINING DETAILS IN 1 VIEWPORT) */}
      <div className="flex-1 p-4 md:p-5 flex flex-col justify-between space-y-4 min-h-0 overflow-hidden">
        
        {/* ROW A: LIVE VITALS MONITORING (BP, HR, SPO2) - Matching Image Card Aesthetics */}
        <div className="shrink-0">
          <div className="flex items-center justify-between mb-3">
            <h2 className="text-xs font-extrabold uppercase tracking-[0.14em] text-[#1E293B] flex items-center">
              <Stethoscope className="w-4 h-4 mr-2 text-[#64748B]" />
              CURRENT VITALS
            </h2>
            <span className="text-[11px] text-[#64748B] font-mono font-medium">Synced Continuous Telemetry</span>
          </div>

          <div className="grid grid-cols-1 md:grid-cols-3 gap-4">
            
            {/* 1. BLOOD PRESSURE CARD */}
            <div className="relative p-4 rounded-2xl border border-[#FCA5A5]/60 bg-[#FEF2F2]/30 shadow-sm flex flex-col justify-between space-y-3 transition-all hover:border-red-300">
              <span className="absolute top-4 right-4 flex h-2.5 w-2.5">
                <span className="relative inline-flex rounded-full h-2.5 w-2.5 bg-[#EF4444] shadow-[0_0_6px_rgba(239,68,68,0.6)]"></span>
              </span>

              <div className="flex justify-between items-center">
                <span className="text-[11px] font-extrabold text-[#64748B] uppercase tracking-[0.12em]">
                  BLOOD PRESSURE
                </span>
              </div>

              <div className="flex items-baseline space-x-1.5 my-0.5">
                <span className="text-4xl font-extrabold tabular-nums tracking-tight text-[#DC2626]">
                  82/45
                </span>
                <span className="text-sm text-[#64748B] font-bold">mmHg</span>
              </div>

              <div className="border-t border-[#FECACA]/60 pt-2 flex justify-between items-center text-[11px] text-[#94A3B8] font-medium">
                <span>Ref: 120/80</span>
                <span>Just now</span>
              </div>
            </div>

            {/* 2. HEART RATE CARD */}
            <div className="relative p-4 rounded-2xl border border-slate-200/90 bg-white shadow-sm flex flex-col justify-between space-y-3 transition-all hover:border-slate-300">
              <div className="flex justify-between items-center">
                <span className="text-[11px] font-extrabold text-[#64748B] uppercase tracking-[0.12em]">
                  HEART RATE
                </span>
              </div>

              <div className="flex items-baseline space-x-2 my-0.5">
                <span className="text-4xl font-extrabold tabular-nums tracking-tight text-[#D97706]">
                  128
                </span>
                <span className="text-sm text-[#64748B] font-bold">bpm</span>
                <ArrowUp className="w-5 h-5 text-[#D97706] stroke-[2.8] ml-1" />
              </div>

              <div className="border-t border-slate-100 pt-2 flex justify-between items-center text-[11px] text-[#94A3B8] font-medium">
                <span>Ref: 60-100</span>
                <span>Continuous</span>
              </div>
            </div>

            {/* 3. SPO2 CARD */}
            <div className="relative p-4 rounded-2xl border border-slate-200/90 bg-white shadow-sm flex flex-col justify-between space-y-3 transition-all hover:border-slate-300">
              <div className="flex justify-between items-center">
                <span className="text-[11px] font-extrabold text-[#64748B] uppercase tracking-[0.12em]">
                  SPO2
                </span>
              </div>

              <div className="flex items-baseline space-x-1.5 my-0.5">
                <span className="text-4xl font-extrabold tabular-nums tracking-tight text-[#0F172A]">
                  94
                </span>
                <span className="text-sm text-[#64748B] font-bold">%</span>
              </div>

              <div className="border-t border-slate-100 pt-2 flex justify-between items-center text-[11px] text-[#94A3B8] font-medium">
                <span>Ref: &gt;95%</span>
                <span>Continuous</span>
              </div>
            </div>

          </div>
        </div>

        {/* ROW B: REAL-TIME WAVEFORMS (8 COLS) + AI RHYTHM ANALYSIS (4 COLS) */}
        <div className="flex-1 grid grid-cols-1 lg:grid-cols-12 gap-4 min-h-0 overflow-hidden">
          
          {/* Real-time Waveforms */}
          <div className="lg:col-span-8 bg-white border border-slate-200/80 rounded-2xl p-4 flex flex-col justify-between space-y-2 min-h-0 overflow-hidden shadow-sm">
            <div className="flex items-center justify-between border-b border-slate-100 pb-2">
              <div className="flex items-center space-x-2">
                <Activity className="w-4 h-4 text-[#0284C7]" />
                <h3 className="text-xs font-extrabold uppercase tracking-[0.12em] text-[#1E293B]">
                  Real-Time Waveform Streaming
                </h3>
              </div>
              <div className="flex items-center space-x-3 text-[10px] text-[#64748B] font-mono font-medium">
                <span>10mm/mV</span>
                <span>25mm/s</span>
                <button 
                  onClick={() => setFullscreenGraph("ecg_raw")}
                  className="p-1 text-[#64748B] hover:text-[#0F172A] hover:bg-slate-100 rounded transition-colors"
                  title="Fullscreen"
                >
                  <Maximize2 className="w-3.5 h-3.5" />
                </button>
              </div>
            </div>

            {/* Lead I Filtered Waveform (Sleek Dark Clinical Viewport for ECG) */}
            <div className="flex-1 bg-[#090D16] border border-slate-800 rounded-xl relative overflow-hidden p-1.5 min-h-0">
              <div className="absolute top-1.5 left-3 text-[10px] text-cyan-400 font-bold font-mono z-10">
                Lead I (Filtered DSP)
              </div>
              <div className="w-full h-full">
                <EChart option={getEcgGridOption(ecgFilt, "#00f2fe")} />
              </div>
            </div>

            {/* PPG Plethysmograph Waveform */}
            <div className="flex-1 bg-[#090D16] border border-slate-800 rounded-xl relative overflow-hidden p-1.5 min-h-0">
              <div className="absolute top-1.5 left-3 text-[10px] text-emerald-400 font-bold font-mono z-10">
                PPG Plethysmograph Pulse
              </div>
              <div className="w-full h-full">
                <EChart option={getPpgOption(ppg)} />
              </div>
            </div>
          </div>

          {/* AI Rhythm Analysis */}
          <div className="lg:col-span-4 bg-white border border-slate-200/80 rounded-2xl p-4 flex flex-col justify-between space-y-3 min-h-0 overflow-hidden shadow-sm">
            <div className="flex items-center justify-between border-b border-slate-100 pb-2">
              <h3 className="text-xs font-extrabold uppercase tracking-[0.12em] text-[#1E293B] flex items-center">
                <Sparkles className="w-4 h-4 mr-2 text-[#0284C7]" />
                AI Rhythm Analysis
              </h3>
              <span className="text-[9px] bg-cyan-50 text-[#0284C7] border border-cyan-200 px-2 py-0.5 rounded font-bold">
                EDGE ML
              </span>
            </div>

            <div className="space-y-4 my-auto">
              <div>
                <span className="text-[10px] text-[#64748B] uppercase font-extrabold tracking-[0.12em] block mb-1">
                  Current Rhythm Classification
                </span>
                <div className="text-lg font-extrabold text-[#0F172A] flex items-center">
                  <span className="w-2.5 h-2.5 rounded-full bg-emerald-500 mr-2 animate-pulse"></span>
                  Normal Sinus Rhythm
                </div>
                <span className="text-[11px] text-[#64748B] font-medium mt-1 block">Occasional Premature Ventricular Complexes</span>
              </div>

              <div>
                <span className="text-[10px] text-[#64748B] uppercase font-extrabold tracking-[0.12em] block mb-2">
                  Arrhythmia Screening Flags
                </span>
                <div className="flex gap-2">
                  <span className="px-2.5 py-1 rounded-md bg-slate-100 border border-slate-200 text-[10px] font-bold text-slate-600">
                    AFIB
                  </span>
                  <span className="px-2.5 py-1 rounded-md bg-amber-50 border border-amber-300 text-[10px] font-bold text-amber-800">
                    PVC (Freq)
                  </span>
                  <span className="px-2.5 py-1 rounded-md bg-slate-100 border border-slate-200 text-[10px] font-bold text-slate-600">
                    BIGEM
                  </span>
                </div>
              </div>

              <div>
                <div className="flex justify-between text-xs text-[#64748B] mb-1.5 font-bold">
                  <span>AI Confidence Metric</span>
                  <span className="text-[#0284C7] font-mono">99.6%</span>
                </div>
                <div className="w-full bg-slate-100 h-2 rounded-full overflow-hidden border border-slate-200">
                  <div className="bg-gradient-to-r from-blue-600 to-cyan-500 h-full rounded-full w-[99.6%]"></div>
                </div>
              </div>
            </div>

            <div className="text-[10px] text-[#94A3B8] border-t border-slate-100 pt-2 font-mono font-medium">
              Model: Tarang-CardioML-v2.1 • Inference &lt; 8ms
            </div>
          </div>

        </div>

        {/* ROW C: SESSION SCRUBBING TIMELINE BAR */}
        <div className="bg-white border border-slate-200 rounded-2xl px-4 py-2.5 flex items-center space-x-5 shrink-0 shadow-sm">
          <div className="flex items-center space-x-2 shrink-0">
            <Sliders className="w-4 h-4 text-[#0284C7]" />
            <span className="text-xs font-bold text-[#1E293B] uppercase tracking-wider font-mono">
              Session Scrubbing
            </span>
          </div>

          <div className="flex-1 flex flex-col justify-center">
            <div className="w-full h-1.5 bg-slate-100 border border-slate-200 rounded-full relative">
              <div className="absolute top-1/2 -translate-y-1/2 left-[20%] w-3 h-3 rounded-full bg-slate-400 border border-slate-300"></div>
              <div className="absolute top-1/2 -translate-y-1/2 left-[60%] w-3 h-3 rounded-full bg-slate-400 border border-slate-300"></div>
              <div className="absolute top-1/2 -translate-y-1/2 left-[95%] w-3.5 h-3.5 rounded-full bg-[#0284C7] shadow-md"></div>
            </div>
            <div className="flex justify-between text-[10px] text-[#64748B] font-mono font-medium mt-1">
              <span>08:00 AM (Admission)</span>
              <span>09:30 AM (Medication)</span>
              <span className="text-[#0284C7] font-bold">11:00 AM (Live Now)</span>
            </div>
          </div>
        </div>

      </div>

    </div>
  );
}
