// TARANG Mode A (Event-Driven) Data Types

export interface VitalsSample {
  id?: number;
  deviceId?: string;
  sessionId?: string;
  ts?: string | null;
  heartRateBpm?: number | null;
  spo2Pct?: number | null;
}

export interface Analytics5Min {
  id?: number;
  deviceId?: string;
  sessionId?: string;
  ts?: string | null;
  pvcBurdenPct: number;
  pacBurdenPct: number;
  sdnn: number;
  rmssd: number;
  prr50: number;
  aiDutyCyclePct: number;
  em2SleepPct: number;
}

export interface BeatAnnotation {
  id?: number;
  snippetId?: number;
  offsetMs: number;
  label: 'N' | 'V' | 'S' | 'Q';
  confidence: number;
}

export interface EcgSnippet {
  id?: number;
  eventId?: number;
  deviceId?: string;
  tsStart?: string | null;
  sampleRateHz: number;
  waveform?: number[];
  annotations?: BeatAnnotation[];
}

export interface ClinicalEvent {
  id?: number;
  deviceId?: string;
  sessionId?: string;
  ts?: string | null;
  rhythmStatus: number; // 0=NSR, 1=AFib, 2=VT, etc.
  patternType?: string | null; // Couplet, Triplet, Bigeminy, Trigeminy, Run, VT, null
  confidence?: number;
  snippet?: EcgSnippet | null;
}

export interface ClinicalTelemetryPacket {
  timestamp_ms: number;
  beat_class: 0 | 1 | 2 | 3;
  confidence: number;
  rr_interval_ms: number;
  rhythm_flags: number;
  pac_burden_pct: number;
  pvc_burden_pct: number;
  current_hr: number;
  sdnn_ms: number;
  rmssd_ms: number;
  spo2_pct?: number;
  resp_rate?: number;
  bp_systolic?: number;
  bp_diastolic?: number;
}

export interface PatientInfo {
  name: string;
  age: number;
  gender: 'Male' | 'Female' | 'Other';
  id: string;
  bed: string;
  admitDate: string;
  attendingPhysician: string;
  bloodType: string;
  allergies: string[];
  medicalHistory: string[];
}

export interface TelemetryDiagnostics {
  bleConnected: boolean;
  deviceName: string;
  deviceMac: string;
  firmwareVersion: string;
  rssiDbm: number;
  packetsReceived: number;
  packetsDropped: number;
  latencyMs: number;
  batteryPct: number;
  ecgDmaHealth: boolean;
  ppgI2cHealth: boolean;
  imuFifoHealth: boolean;
  lastSyncTimestamp: string;
}

export interface DeviceHealthTelemetry {
  uptimeS: number;
  ecgLeadOff: boolean;
  ecgSqi: number;
  ppgFingerPresent: boolean;
  imuOk: boolean;
  i2cFailureCount: number;
  dspOverflowCount: number;
  ecgOverrunCount: number;
  bleRssi?: number | null;
  batteryPct?: number | null;
  fwVersion: string;
  sessionId?: string | null;
}

export interface SystemSettings {
  hrLowThreshold: number;
  hrHighThreshold: number;
  spo2LowThreshold: number;
  rrLowThreshold: number;
  rrHighThreshold: number;
  bleSyncIntervalMs: number;
  gridDensity: 'dense' | 'standard' | 'relaxed';
  audioAlertsEnabled: boolean;
  attendingDoctor: string;
}

export type InitializationStageId =
  | 'connecting'
  | 'sensor_detected'
  | 'signal_initializing'
  | 'calibrating'
  | 'ai_ready'
  | 'ready'
  | 'disconnected'
  | 'error';

export interface InitializationStageInfo {
  id: InitializationStageId;
  title: string;
  description: string;
  completed: boolean;
  current: boolean;
}

export interface DeviceStatusMessage {
  type: 'device_status';
  status: InitializationStageId;
  progress?: number;
  message?: string;
  uptime_s?: number;
  ecg_sqi?: number;
}
