export interface ClinicalTelemetryPacket {
  timestamp_ms: number;
  beat_class: 0 | 1 | 2; // 0 = Normal, 1 = PAC (Premature Atrial), 2 = PVC (Premature Ventricular)
  confidence: number; // 0 - 255
  rr_interval_ms: number;
  rhythm_flags: number; // Bitmask: 0x01 Normal, 0x02 Brady, 0x04 Tachy, 0x08 Arrhythmia
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
